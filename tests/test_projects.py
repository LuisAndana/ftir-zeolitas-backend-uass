"""
Tests del módulo Proyectos (app/routes/projects.py): propiedad por usuario,
versiones inmutables con motivo obligatorio, bitácora, límites y referencias.
"""
import asyncio
import io
import json

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import text

from app.models.project import ProjectActivity, ProjectFileVersion
from app.models.user import User
from app.routes import projects as P
from tests.conftest import make_user_spectrum

CSV = b"wavenumber,absorbance\n400,0.10\n500,0.20\n600,0.30\n700,0.40\n800,0.50\n" \
      b"900,0.60\n1000,0.70\n1100,0.60\n1200,0.50\n1300,0.40\n1400,0.30\n"


def upload(name=b"x.csv", content=CSV):
    return UploadFile(filename=name.decode() if isinstance(name, bytes) else name, file=io.BytesIO(content))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def project(db_session, test_user):
    r = P.create_project(P.ProjectIn(name="Serie Cu"), db=db_session, current_user=test_user)
    return r.data["project"]["id"]


@pytest.fixture()
def other_user(db_session):
    u = User(email="otro@example.com", password_hash="x", name="Otro", role="investigador",
             is_active=True, is_verified=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def add_spectrum(db, user, project_id, name="s.csv"):
    r = run(P.upload_file(project_id, upload(name), None, db=db, current_user=user))
    return r.data["file"]["id"]


def test_project_is_private_to_owner(db_session, test_user, other_user, project):
    with pytest.raises(HTTPException) as e:
        P.get_project(project, db=db_session, current_user=other_user)
    assert e.value.status_code == 404
    listed = P.list_projects(db=db_session, current_user=other_user).data["projects"]
    assert listed == []


def test_upload_creates_version_one_and_log(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    detail = P.get_file(project, fid, db=db_session, current_user=test_user).data
    assert detail["file"]["current_version"] == 1
    assert len(detail["content"]["wavenumbers"]) == 11
    acts = P.project_activity(project, 0, 50, db=db_session, current_user=test_user).data["activity"]
    assert [a["action"] for a in acts][:2] == ["file_added", "project_created"]


def test_unsupported_format_rejected(db_session, test_user, project):
    with pytest.raises(HTTPException) as e:
        run(P.upload_file(project, upload("datos.xlsx", b"PK\x03\x04"), None, db=db_session, current_user=test_user))
    assert e.value.status_code == 422 and "no es compatible" in e.value.detail


def test_oversize_upload_rejected(db_session, test_user, project, monkeypatch):
    monkeypatch.setattr(P, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(HTTPException) as e:
        run(P.upload_file(project, upload(), None, db=db_session, current_user=test_user))
    assert e.value.status_code == 413


def test_edit_requires_reason_and_keeps_old_version(db_session, test_user, project):
    r = P.create_note(project, P.NoteIn(name="n.md", content="uno"), db=db_session, current_user=test_user)
    fid = r.data["file"]["id"]
    with pytest.raises(HTTPException) as e:
        P.edit_note(project, fid, P.NoteEdit(content="dos", reason=" "), db=db_session, current_user=test_user)
    assert e.value.status_code == 422
    P.edit_note(project, fid, P.NoteEdit(content="dos", reason="Corregí la dosis"), db=db_session, current_user=test_user)
    detail = P.get_file(project, fid, db=db_session, current_user=test_user).data
    assert detail["content"]["text"] == "dos" and detail["file"]["current_version"] == 2
    old = P.get_file_version(project, fid, 1, db=db_session, current_user=test_user).data
    assert old["content"]["text"] == "uno"
    assert detail["versions"][0]["change_reason"] == "Corregí la dosis"


def test_crop_creates_derived_version_original_untouched(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    P.crop_spectrum(project, fid, P.CropIn(min_wavenumber=400, max_wavenumber=1300, reason="Quitar bordes ruidosos"),
                    db=db_session, current_user=test_user)
    cur = P.get_file(project, fid, db=db_session, current_user=test_user).data
    assert cur["file"]["current_version"] == 2 and len(cur["content"]["wavenumbers"]) == 10
    v1 = P.get_file_version(project, fid, 1, db=db_session, current_user=test_user).data
    assert len(v1["content"]["wavenumbers"]) == 11


def test_crop_too_small_range_rejected(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    with pytest.raises(HTTPException) as e:
        P.crop_spectrum(project, fid, P.CropIn(min_wavenumber=400, max_wavenumber=450, reason="prueba"),
                        db=db_session, current_user=test_user)
    assert e.value.status_code == 422


def test_restore_creates_new_version(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    P.crop_spectrum(project, fid, P.CropIn(min_wavenumber=400, max_wavenumber=1300, reason="recorte"),
                    db=db_session, current_user=test_user)
    P.restore_version(project, fid, 1, P.ReasonIn(reason="El recorte quitó una banda"),
                      db=db_session, current_user=test_user)
    cur = P.get_file(project, fid, db=db_session, current_user=test_user).data
    assert cur["file"]["current_version"] == 3 and len(cur["content"]["wavenumbers"]) == 11


def test_hash_matches_content(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    v = db_session.query(ProjectFileVersion).filter_by(file_id=fid, version=1).one()
    assert v.content_hash == P._hash(v.content)


def test_reference_requires_family(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    with pytest.raises(HTTPException):
        P.update_file(project, fid, P.FileUpdate(is_reference=True, reason="confirmada"),
                      db=db_session, current_user=test_user)
    r = P.update_file(project, fid, P.FileUpdate(is_reference=True, family_code="mfi", reason="Confirmada por DRX"),
                      db=db_session, current_user=test_user)
    assert r.data["file"]["is_reference"] and r.data["file"]["family_code"] == "MFI"


def test_invalid_family_code_rejected(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    with pytest.raises(HTTPException):
        P.update_file(project, fid, P.FileUpdate(family_code="MF I;--", reason="prueba"),
                      db=db_session, current_user=test_user)


def test_file_of_another_users_project_is_404(db_session, test_user, other_user, project):
    fid = add_spectrum(db_session, test_user, project)
    with pytest.raises(HTTPException) as e:
        P.get_file(project, fid, db=db_session, current_user=other_user)
    assert e.value.status_code == 404


def test_name_is_stripped_of_path_components(db_session, test_user, project):
    r = P.create_note(project, P.NoteIn(name="..\\..\\etc/passwd", content=""), db=db_session, current_user=test_user)
    assert r.data["file"]["name"] == "passwd"


def test_delete_file_keeps_log_entry_with_name(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project, "borrar.csv")
    P.delete_file(project, fid, "Duplicado", db=db_session, current_user=test_user)
    acts = P.project_activity(project, 0, 50, db=db_session, current_user=test_user).data["activity"]
    assert acts[0]["action"] == "file_deleted" and acts[0]["file_name"] == "borrar.csv"


def test_duplicate_copies_latest_version_and_links_origin(db_session, test_user, project):
    fid = add_spectrum(db_session, test_user, project)
    P.crop_spectrum(project, fid, P.CropIn(min_wavenumber=400, max_wavenumber=1300, reason="recorte"),
                    db=db_session, current_user=test_user)
    r = P.duplicate_project(project, P.DuplicateIn(), db=db_session, current_user=test_user)
    new_id = r.data["project"]["id"]
    assert r.data["project"]["derived_from_id"] == project and r.data["project"]["file_count"] == 1
    copied = P.get_project(new_id, db=db_session, current_user=test_user).data["files"][0]
    content = P.get_file(new_id, copied["id"], db=db_session, current_user=test_user).data["content"]
    assert len(content["wavenumbers"]) == 10


def test_add_from_existing_spectrum(db_session, test_user, project, wn_grid, synthetic_lta_spectrum):
    s = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "lta.txt", material="LTA")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    r = P.add_from_spectrum(project, s.id, db=db_session, current_user=test_user)
    assert r.data["file"]["family_code"] == "LTA"


def test_delete_project_cascades(db_session, test_user, project):
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    add_spectrum(db_session, test_user, project)
    P.delete_project(project, db=db_session, current_user=test_user)
    assert db_session.query(ProjectFileVersion).count() == 0
    assert db_session.query(ProjectActivity).count() == 0


def test_verified_reference_participates_in_search(db_session, test_user, project, wn_grid, synthetic_lta_spectrum):
    from app.routes import similarity as sim
    from app.schemas.similarity import SimilaritySearchRequest, SimilarityConfig

    sim.dataset_matrix_cache.loaded = False
    sim.dataset_matrix_cache.matrix = None

    content = json.dumps({"wavenumbers": wn_grid.tolist(), "absorbance": synthetic_lta_spectrum.tolist()})
    f = P._new_file(db_session, db_session.get(P.Project, project), test_user, "ref_lta.txt", "spectrum",
                    content, "referencia", "file_added")
    f.is_reference, f.family_code = True, "LTA"
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(query)
    db_session.commit()
    db_session.refresh(query)

    req = SimilaritySearchRequest(query_spectrum_id=query.id,
                                  config=SimilarityConfig(method="pearson", min_similarity=0.0))
    out = sim.search_similarity(req, db=db_session, current_user=test_user)
    refs = [r for r in out["data"]["results"] if r["source"] == "project_reference"]
    assert len(refs) == 1 and refs[0]["framework_code"] == "LTA" and refs[0]["global_score"] > 0.9
