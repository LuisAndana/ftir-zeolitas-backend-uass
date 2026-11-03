"""
Rutas de Proyectos: espacio de trabajo personal del investigador.

Reglas de diseño:
- Todo se filtra por dueño (Project.user_id == current_user.id); un proyecto o
  archivo ajeno responde 404, nunca 403 (no revela que existe).
- Los datos nunca se sobrescriben: cada edición crea una versión nueva con su
  motivo (obligatorio) y su hash SHA-256; la bitácora solo se agrega.
- Los archivos se aceptan por el mismo parser que la carga de espectros, así que
  los formatos soportados son exactamente los mismos (ver parse_spectrum_file).
"""

import hashlib
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.project import Project, ProjectFile, ProjectFileVersion, ProjectActivity
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routes.spectra import parse_spectrum_file
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["proyectos"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SPECTRUM_POINTS = 100_000
MAX_NOTE_CHARS = 200_000
MAX_FILES_PER_PROJECT = 200
FAMILY_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")


# ---------------------------------------------------------------- esquemas

class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)
    reason: Optional[str] = Field(None, max_length=500)


class DuplicateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)


class NoteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field("", max_length=MAX_NOTE_CHARS)
    reason: Optional[str] = Field(None, max_length=500)


class NoteEdit(BaseModel):
    content: str = Field(..., max_length=MAX_NOTE_CHARS)
    reason: str = Field(..., max_length=500)


class CropIn(BaseModel):
    min_wavenumber: float
    max_wavenumber: float
    reason: str = Field(..., max_length=500)


class FileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_reference: Optional[bool] = None
    family_code: Optional[str] = Field(None, max_length=10)
    reason: str = Field(..., max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(..., max_length=500)


# ---------------------------------------------------------------- utilidades

def _clean_reason(reason: Optional[str], required: bool) -> Optional[str]:
    text = (reason or "").strip()
    if required and len(text) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Indica el motivo del cambio (mínimo 3 caracteres): queda registrado en la bitácora.")
    return text[:500] or None


def _clean_name(name: str) -> str:
    # Solo el nombre base: sin rutas, sin caracteres de control.
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    if not base or base in (".", ".."):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El nombre no es válido.")
    return base[:255]


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _commit(db: Session, what: str):
    try:
        db.commit()
    except SQLAlchemyError:
        logger.error(f"❌ Error en proyectos al {what}", exc_info=True)
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"No se pudo {what}. Intenta de nuevo en unos segundos.")


def _own_project(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado.")
    return project


def _own_file(db: Session, project: Project, file_id: int) -> ProjectFile:
    f = db.query(ProjectFile).filter(ProjectFile.id == file_id, ProjectFile.project_id == project.id).first()
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado en este proyecto.")
    return f


def _version(db: Session, f: ProjectFile, number: int) -> ProjectFileVersion:
    v = db.query(ProjectFileVersion).filter(
        ProjectFileVersion.file_id == f.id, ProjectFileVersion.version == number).first()
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Versión no encontrada.")
    return v


def _log(db: Session, project: Project, user: User, action: str,
         reason: Optional[str] = None, f: Optional[ProjectFile] = None, file_name: Optional[str] = None):
    db.add(ProjectActivity(
        project_id=project.id, file_id=f.id if f else None,
        file_name=(f.name if f else file_name), user_id=user.id, action=action, reason=reason,
    ))
    project.updated_at = func.now()


def _iso(dt):
    return dt.isoformat() if dt else None


def _file_dict(f: ProjectFile) -> dict:
    return {
        "id": f.id, "name": f.name, "kind": f.kind, "current_version": f.current_version,
        "is_reference": bool(f.is_reference), "family_code": f.family_code,
        "created_at": _iso(f.created_at), "updated_at": _iso(f.updated_at),
    }


def _version_dict(v: ProjectFileVersion) -> dict:
    return {
        "version": v.version, "change_reason": v.change_reason, "content_hash": v.content_hash,
        "created_by": v.created_by, "created_at": _iso(v.created_at), "size": len(v.content or ""),
    }


def _project_dict(p: Project, file_count: int) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "derived_from_id": p.derived_from_id, "file_count": file_count,
        "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at),
    }


def _content_payload(f: ProjectFile, v: ProjectFileVersion) -> dict:
    """Contenido listo para el frontend (espectro como arreglos, nota como texto)."""
    if f.kind == "note":
        return {"text": v.content}
    data = json.loads(v.content)
    return {"wavenumbers": data["wavenumbers"], "absorbance": data["absorbance"]}


def _check_capacity(db: Session, project: Project):
    count = db.query(func.count(ProjectFile.id)).filter(ProjectFile.project_id == project.id).scalar() or 0
    if count >= MAX_FILES_PER_PROJECT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Un proyecto admite hasta {MAX_FILES_PER_PROJECT} archivos.")


def _spectrum_json(wavenumbers: list, absorbance: list) -> str:
    if len(wavenumbers) != len(absorbance) or not wavenumbers:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El espectro no contiene datos válidos.")
    if len(wavenumbers) > MAX_SPECTRUM_POINTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"El espectro tiene demasiados puntos (máximo {MAX_SPECTRUM_POINTS}).")
    return json.dumps({"wavenumbers": wavenumbers, "absorbance": absorbance})


async def _read_spectrum_upload(file: UploadFile) -> str:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "El archivo supera el tamaño máximo de 5 MB.")
    try:
        parsed = parse_spectrum_file(raw, file.filename or "")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return _spectrum_json(parsed["wavenumbers"], parsed["absorbance"])


def _new_file(db: Session, project: Project, user: User, name: str, kind: str,
              content: str, reason: Optional[str], action: str) -> ProjectFile:
    f = ProjectFile(project_id=project.id, name=name, kind=kind, current_version=1)
    db.add(f)
    db.flush()
    db.add(ProjectFileVersion(
        file_id=f.id, version=1, content=content, content_hash=_hash(content),
        change_reason=reason or "Versión inicial", created_by=user.id,
    ))
    _log(db, project, user, action, reason, f)
    return f


def _append_version(db: Session, f: ProjectFile, user: User, content: str, reason: str):
    f.current_version += 1
    db.add(ProjectFileVersion(
        file_id=f.id, version=f.current_version, content=content,
        content_hash=_hash(content), change_reason=reason, created_by=user.id,
    ))


# ---------------------------------------------------------------- proyectos

@router.get("", response_model=SuccessResponse, summary="Listar mis proyectos")
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    counts = dict(
        db.query(ProjectFile.project_id, func.count(ProjectFile.id))
        .join(Project, Project.id == ProjectFile.project_id)
        .filter(Project.user_id == current_user.id)
        .group_by(ProjectFile.project_id).all()
    )
    projects = (db.query(Project).filter(Project.user_id == current_user.id)
                .order_by(Project.updated_at.desc()).all())
    return SuccessResponse(message="Proyectos obtenidos",
                           data={"projects": [_project_dict(p, counts.get(p.id, 0)) for p in projects]})


@router.post("", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED,
             summary="Crear proyecto")
def create_project(body: ProjectIn, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    project = Project(user_id=current_user.id, name=body.name.strip(),
                      description=(body.description or "").strip() or None)
    if not project.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El nombre del proyecto es obligatorio.")
    db.add(project)
    db.flush()
    _log(db, project, current_user, "project_created", "Proyecto creado")
    _commit(db, "crear el proyecto")
    db.refresh(project)
    return SuccessResponse(message="Proyecto creado", data={"project": _project_dict(project, 0)})


@router.get("/{project_id}", response_model=SuccessResponse, summary="Detalle de proyecto")
def get_project(project_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    files = (db.query(ProjectFile).filter(ProjectFile.project_id == project.id)
             .order_by(ProjectFile.updated_at.desc()).all())
    return SuccessResponse(message="Proyecto obtenido", data={
        "project": _project_dict(project, len(files)),
        "files": [_file_dict(f) for f in files],
    })


@router.put("/{project_id}", response_model=SuccessResponse, summary="Editar proyecto")
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    reason = _clean_reason(body.reason, required=False)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El nombre del proyecto es obligatorio.")
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description.strip() or None
    _log(db, project, current_user, "project_updated", reason or "Datos del proyecto editados")
    _commit(db, "editar el proyecto")
    db.refresh(project)
    count = db.query(func.count(ProjectFile.id)).filter(ProjectFile.project_id == project.id).scalar() or 0
    return SuccessResponse(message="Proyecto actualizado", data={"project": _project_dict(project, count)})


@router.delete("/{project_id}", response_model=SuccessResponse, summary="Eliminar proyecto")
def delete_project(project_id: int, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    db.delete(project)
    _commit(db, "eliminar el proyecto")
    return SuccessResponse(message="Proyecto eliminado")


@router.post("/{project_id}/duplicate", response_model=SuccessResponse,
             status_code=status.HTTP_201_CREATED, summary="Duplicar proyecto para una nueva investigación")
def duplicate_project(project_id: int, body: DuplicateIn, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    src = _own_project(db, project_id, current_user)
    new = Project(user_id=current_user.id, name=(body.name or f"{src.name} (copia)").strip()[:150],
                  description=src.description, derived_from_id=src.id)
    db.add(new)
    db.flush()
    _log(db, new, current_user, "project_created", f"Derivado del proyecto «{src.name}»")
    for f in db.query(ProjectFile).filter(ProjectFile.project_id == src.id).all():
        latest = _version(db, f, f.current_version)
        copy = _new_file(db, new, current_user, f.name, f.kind, latest.content,
                         f"Copiado de «{src.name}» (v{f.current_version})", "file_added")
        copy.is_reference, copy.family_code = f.is_reference, f.family_code
    _commit(db, "duplicar el proyecto")
    db.refresh(new)
    count = db.query(func.count(ProjectFile.id)).filter(ProjectFile.project_id == new.id).scalar() or 0
    return SuccessResponse(message="Proyecto duplicado", data={"project": _project_dict(new, count)})


@router.get("/{project_id}/activity", response_model=SuccessResponse, summary="Bitácora del proyecto")
def project_activity(project_id: int, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                     db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    q = db.query(ProjectActivity).filter(ProjectActivity.project_id == project.id)
    total = q.count()
    rows = q.order_by(ProjectActivity.created_at.desc(), ProjectActivity.id.desc()).offset(skip).limit(limit).all()
    return SuccessResponse(message="Bitácora obtenida", data={
        "total": total,
        "activity": [{
            "id": a.id, "action": a.action, "reason": a.reason, "file_id": a.file_id,
            "file_name": a.file_name, "created_at": _iso(a.created_at),
        } for a in rows],
    })


# ---------------------------------------------------------------- archivos

@router.post("/{project_id}/files", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED,
             summary="Subir un espectro al proyecto")
async def upload_file(project_id: int, file: UploadFile = File(...), reason: Optional[str] = Form(None),
                      db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    _check_capacity(db, project)
    content = await _read_spectrum_upload(file)
    f = _new_file(db, project, current_user, _clean_name(file.filename or "espectro"), "spectrum",
                  content, _clean_reason(reason, required=False) or "Archivo cargado", "file_added")
    _commit(db, "guardar el archivo")
    db.refresh(f)
    return SuccessResponse(message="Archivo agregado", data={"file": _file_dict(f)})


@router.post("/{project_id}/files/note", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED,
             summary="Crear una nota en el proyecto")
def create_note(project_id: int, body: NoteIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    _check_capacity(db, project)
    f = _new_file(db, project, current_user, _clean_name(body.name), "note", body.content,
                  _clean_reason(body.reason, required=False) or "Nota creada", "file_added")
    _commit(db, "crear la nota")
    db.refresh(f)
    return SuccessResponse(message="Nota creada", data={"file": _file_dict(f)})


@router.post("/{project_id}/files/from-spectrum/{spectrum_id}", response_model=SuccessResponse,
             status_code=status.HTTP_201_CREATED, summary="Agregar al proyecto un espectro ya cargado")
def add_from_spectrum(project_id: int, spectrum_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    _check_capacity(db, project)
    spectrum = db.query(Spectrum).filter(Spectrum.id == spectrum_id, Spectrum.user_id == current_user.id).first()
    if not spectrum:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Espectro no encontrado.")
    try:
        data = json.loads(spectrum.wavenumber_data or "{}")
        wn = data.get("wavenumbers") or []
        ab = data.get("absorbance") or data.get("intensities") or []
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El espectro no contiene datos válidos.")
    content = _spectrum_json(wn, ab)
    f = _new_file(db, project, current_user, _clean_name(spectrum.filename), "spectrum", content,
                  "Importado desde Mis espectros", "file_added")
    code = (spectrum.material or "").strip()
    if FAMILY_RE.match(code) and code.lower() != "desconocido":
        f.family_code = code.upper()
    _commit(db, "agregar el espectro")
    db.refresh(f)
    return SuccessResponse(message="Espectro agregado al proyecto", data={"file": _file_dict(f)})


@router.get("/{project_id}/files/{file_id}", response_model=SuccessResponse, summary="Detalle de archivo")
def get_file(project_id: int, file_id: int, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    current = _version(db, f, f.current_version)
    versions = (db.query(ProjectFileVersion).filter(ProjectFileVersion.file_id == f.id)
                .order_by(ProjectFileVersion.version.desc()).all())
    return SuccessResponse(message="Archivo obtenido", data={
        "file": _file_dict(f),
        "content": _content_payload(f, current),
        "versions": [_version_dict(v) for v in versions],
    })


@router.get("/{project_id}/files/{file_id}/versions/{version}", response_model=SuccessResponse,
            summary="Contenido de una versión anterior")
def get_file_version(project_id: int, file_id: int, version: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    v = _version(db, f, version)
    return SuccessResponse(message="Versión obtenida", data={
        "version": _version_dict(v), "content": _content_payload(f, v),
    })


@router.patch("/{project_id}/files/{file_id}", response_model=SuccessResponse,
              summary="Renombrar o marcar como referencia verificada")
def update_file(project_id: int, file_id: int, body: FileUpdate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    reason = _clean_reason(body.reason, required=True)
    old_name = f.name
    if body.name is not None:
        f.name = _clean_name(body.name)
    if body.family_code is not None:
        code = body.family_code.strip()
        if code and not FAMILY_RE.match(code):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "El código de familia debe tener entre 2 y 10 letras o números (p. ej. MFI).")
        f.family_code = code.upper() or None
    if body.is_reference is not None:
        if body.is_reference and (f.kind != "spectrum" or not (body.family_code or f.family_code)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Para usar un espectro como referencia verificada indica su familia confirmada.")
        f.is_reference = body.is_reference
    if f.is_reference and not f.family_code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Una referencia verificada necesita su código de familia.")
    action = "reference_changed" if body.is_reference is not None or body.family_code is not None else "file_renamed"
    detail = reason if action == "reference_changed" or old_name == f.name else f"{reason} (antes: «{old_name}»)"
    _log(db, project, current_user, action, detail, f)
    _commit(db, "actualizar el archivo")
    db.refresh(f)
    return SuccessResponse(message="Archivo actualizado", data={"file": _file_dict(f)})


@router.put("/{project_id}/files/{file_id}/note", response_model=SuccessResponse,
            summary="Editar el texto de una nota (crea una versión nueva)")
def edit_note(project_id: int, file_id: int, body: NoteEdit, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    if f.kind != "note":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Este archivo no es una nota.")
    reason = _clean_reason(body.reason, required=True)
    _append_version(db, f, current_user, body.content, reason)
    _log(db, project, current_user, "file_edited", reason, f)
    _commit(db, "guardar la nota")
    db.refresh(f)
    return SuccessResponse(message="Nota actualizada", data={"file": _file_dict(f)})


@router.post("/{project_id}/files/{file_id}/versions", response_model=SuccessResponse,
             status_code=status.HTTP_201_CREATED, summary="Reemplazar un espectro por una versión nueva")
async def replace_spectrum(project_id: int, file_id: int, file: UploadFile = File(...),
                           reason: str = Form(...), db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    if f.kind != "spectrum":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Solo se pueden reemplazar espectros.")
    clean = _clean_reason(reason, required=True)
    content = await _read_spectrum_upload(file)
    _append_version(db, f, current_user, content, clean)
    _log(db, project, current_user, "file_edited", clean, f)
    _commit(db, "guardar la nueva versión")
    db.refresh(f)
    return SuccessResponse(message="Versión nueva guardada", data={"file": _file_dict(f)})


@router.post("/{project_id}/files/{file_id}/crop", response_model=SuccessResponse,
             status_code=status.HTTP_201_CREATED, summary="Recortar el rango espectral (versión derivada)")
def crop_spectrum(project_id: int, file_id: int, body: CropIn, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    if f.kind != "spectrum":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Solo se pueden recortar espectros.")
    reason = _clean_reason(body.reason, required=True)
    if body.min_wavenumber >= body.max_wavenumber:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El rango no es válido: el mínimo debe ser menor que el máximo.")
    data = json.loads(_version(db, f, f.current_version).content)
    pairs = [(w, a) for w, a in zip(data["wavenumbers"], data["absorbance"])
             if body.min_wavenumber <= w <= body.max_wavenumber]
    if len(pairs) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "El rango elegido deja menos de 10 puntos; amplíalo.")
    content = _spectrum_json([p[0] for p in pairs], [p[1] for p in pairs])
    note = f"{reason} (recorte {body.min_wavenumber:g}–{body.max_wavenumber:g} cm⁻¹)"
    _append_version(db, f, current_user, content, note[:500])
    _log(db, project, current_user, "file_edited", note[:500], f)
    _commit(db, "guardar el recorte")
    db.refresh(f)
    return SuccessResponse(message="Recorte guardado como versión nueva", data={"file": _file_dict(f)})


@router.post("/{project_id}/files/{file_id}/restore/{version}", response_model=SuccessResponse,
             status_code=status.HTTP_201_CREATED, summary="Restaurar una versión anterior (crea una nueva)")
def restore_version(project_id: int, file_id: int, version: int, body: ReasonIn,
                    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    old = _version(db, f, version)
    reason = _clean_reason(body.reason, required=True)
    note = f"Restaurada la v{version}: {reason}"[:500]
    _append_version(db, f, current_user, old.content, note)
    _log(db, project, current_user, "version_restored", note, f)
    _commit(db, "restaurar la versión")
    db.refresh(f)
    return SuccessResponse(message="Versión restaurada como versión nueva", data={"file": _file_dict(f)})


@router.delete("/{project_id}/files/{file_id}", response_model=SuccessResponse, summary="Eliminar archivo")
def delete_file(project_id: int, file_id: int, reason: str = Query(...),
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _own_project(db, project_id, current_user)
    f = _own_file(db, project, file_id)
    clean = _clean_reason(reason, required=True)
    _log(db, project, current_user, "file_deleted", clean, file_name=f.name)
    db.delete(f)
    _commit(db, "eliminar el archivo")
    return SuccessResponse(message="Archivo eliminado")
