# FTIR Zeolitas — backend

API FastAPI para indexar zeolitas comparando espectros FTIR (coseno/Pearson/euclídea) contra un
dataset de referencia. MySQL. Informe de diagnóstico completo (2026-08-09, commit 72c6809):
https://claude.ai/code/artifact/1c930869-c4cb-4758-be39-22a6a2009e88 — consultarlo antes de re-analizar.

## PRIMERO: consultar el grafo, no leer archivos

Existe un grafo de conocimiento del repo en `graphify-out/` (643 nodos, 1079 aristas, 66 comunidades,
actualizado 2026-08-09 — sesión completa: P0+P2+P3). **Antes de abrir archivos buscando dónde está algo,
pregúntale al grafo** — devuelve `archivo:línea` directamente y cuesta ~2k tokens en vez de decenas
de miles leyendo archivos uno por uno.

```bash
python -m graphify query "donde se valida el token JWT"
```

- `query "..."` → BFS, contexto amplio (añadir `--budget 4000` si trunca, `--dfs` para seguir una ruta).
- `path "DatasetMatrixCache" "Spectrum"` → camino más corto entre dos símbolos.
- `explain "SimilarityCalculator"` → qué es y con qué se conecta.
- Tras cambiar código: `python -m graphify . --update` (incremental). Reconstrucción completa: `/graphify .`
- `graphify-out/GRAPH_REPORT.md` → god nodes, conexiones inesperadas, huecos de documentación.

Quirks: el CLI `graphify` no está en PATH (instalado con `pip --user`) → usar siempre `python -m graphify`.
`query`/`explain` salen con código 255 aunque la salida sea correcta: leer la salida, no el exit code.
Si `explain` dice «Ambiguous», repetir con el id completo (`app_routes_similarity_datasetmatrixcache`),
porque los conceptos de CLAUDE.md comparten nombre con los símbolos del código.
La extracción AST avisa `BrokenProcessPool` en Windows y cae a modo secuencial: es inofensivo.
Las 118 aristas colgantes del informe de salud son referencias a librerías externas (numpy, FastAPI)
que no están en el corpus — esperado, no es corrupción.

### Mapa de comunidades (dónde vive cada cosa)

| Buscas | Comunidad | Archivo principal |
|---|---|---|
| Búsqueda, caché matricial, picos | Motor de búsqueda de similitud | `app/routes/similarity.py` |
| Métricas de espectros de usuario | Calculador de similitud espectral | `app/services/similarity_calculator.py` |
| Dataset sintético, tablas crudas | Generador de dataset sintético | `app/services/zeolite_dataset_loader.py` |
| Endpoints load/clear/status | Gestión del dataset | `app/routes/dataset.py` |
| Login, tokens, verificación | Autenticación y login · Gestión de tokens JWT | `app/routes/auth.py`, `app/core/security.py` |
| `require_admin`, roles | Autorización y modelo de usuario | `app/routes/admin.py:23` |
| Subida y parseo de espectros | Subida y parseo de espectros | `app/routes/spectra.py` |
| Catálogo de familias | Sesiones de BD y catálogo | `app/routes/zeolites.py` |
| Settings, `.env` | Configuración centralizada | `app/core/config.py` |

God nodes (los que más conectan, tocar con cuidado): `User` (34 aristas), `SuccessResponse` (22),
`ZeoliteDatasetLoader` (18), `SimilarityCalculator` (15), `DatasetMatrixCache` (13).

## Arquitectura

- `app/routes/similarity.py` — todo el motor de búsqueda: `DatasetMatrixCache` (matriz numpy en RAM +
  `.npz` en disco, rejilla fija 400–4000 cm⁻¹ paso 2) y endpoints. Sin ruta de respaldo: si el caché no
  ha cargado, `/search` responde 503+Retry-After.
- `app/services/similarity_calculator.py` — métricas para espectros de usuario; usa el MISMO
  preprocesamiento y las mismas fórmulas que el caché (pipeline unificado desde 2026-08-09).
- `app/services/spectral_preprocessing.py` — módulo compartido nuevo: `preprocess_spectrum` (arPLS +
  Savitzky-Golay + SNV), `mask_atmospheric_co2`, `interpolate_and_preprocess`, `vectorized_similarity`
  (HQI = r² para Pearson), `compute_window_scores`/`weighted_matrix_similarity` (ventanas Flanigen,
  ponderación 0.7 región estructural 400-1300 cm⁻¹ / 0.3 resto). Toda la lógica de similitud pasa por aquí.
- `app/services/zeolite_dataset_loader.py` — genera el dataset sintético con `mysql.connector` crudo
  (tablas `zeolite_types/zeolite_samples/ftir_spectra/ftir_peaks/ftir_analysis`, sin modelos SQLAlchemy).
  Bandas paramétricas por familia (`generate_family_bands`), no un patrón único — ver P3 en pendientes.
- `app/models/zeolite_family.py` + `seed_data.py` — catálogo de referencia (10 familias IZA pobladas).
  `GET /api/zeolites/{code}/structure` sirve metadatos + CIF (si existe en `static/structures/`).
- Espectros de usuario: JSON en columna `TEXT` (`spectrum.wavenumber_data`), claves `wavenumbers` +
  `absorbance`/`intensities` (ambas conviven).
- Arrancar: `uvicorn main:app --reload --port 8000` (o launch.json "FastAPI Backend").
- Tests: `pip install -r requirements-dev.txt && pytest` (100 tests). Migraciones: `alembic/` (4 revisiones
  encadenadas; ver pendiente #9 para el flujo de adopción `stamp head` vs `upgrade head`).

## Gotchas (verificadas — no re-descubrir)

- Dataset 100% sintético: mismos 8 picos para las 44 familias (`CHARACTERISTIC_PEAKS`) → no discrimina
  familias. Sigue sin resolver (P3 #10) — el pipeline de score ya es correcto, pero no hay nada real que
  el score pueda distinguir todavía.
- ~~`seed_data.py` vacío~~ — RESUELTO 2026-08-09: poblado con 10 familias IZA, modelo↔schema alineados.
  Correr `python seed_data.py` para poblarlo (idempotente, se salta códigos ya existentes).
- `.env` estaba versionado en git con secretos reales (historial público) — sigue sin purgarse del
  historial ni rotarse las credenciales (P0 #1, requiere acción del usuario, ver pendientes).
- Sin tests, sin Alembic; esquema por `create_all` + scripts manuales en raíz.
- `cleanup_similarity.py` reescribe código fuente en caliente: no ejecutarlo.
- Repo tiene `.pyc` compilados versionados pese a `__pycache__/` en `.gitignore` (mismo patrón que
  `.env` — se commitearon antes de que la regla existiera). No tocado; limpieza pendiente si se quiere.
- Verificación de cambios: no hay venv del proyecto en el repo. Usar un venv temporal
  (`python -m venv /tmp/x && /tmp/x/Scripts/python.exe -m pip install -r requirements.txt`) para probar
  imports/lógica sin instalar nada en el Python del sistema; borrarlo al terminar.

## Pendientes (orden de prioridad)

### P0 — seguridad (antes que nada)
1. **[PENDIENTE — requiere al usuario]** Rotar credenciales expuestas (Gmail app password, MySQL,
   SECRET_KEY) y purgar `.env` del historial (`git rm --cached .env` + filter-repo, con confirmación
   explícita por ser destructivo/force-push); `.env.example` con valores ficticios.
2. ✅ Hecho: `Depends(require_admin)` en `/api/dataset/*` (load/status/summary/clear) y
   `/api/similarity/cache/reload`.
3. ✅ Hecho: `DEBUG=False` por defecto; `str(e)` quitado de todos los `detail` expuestos al cliente
   (queda en logs con `exc_info=True`).
4. ✅ Hecho: bug Pearson vectorizado (`similarity.py` `calculate_similarities_vectorized`, dividir cov
   por N) — verificado con test numérico (antes saturaba a 0/1). Bug `Form()` en upload
   (`spectra.py:upload_spectrum`) corregido.

### P2 — que el score signifique algo (científico)
5. ✅ Hecho: preprocesamiento arPLS + Savitzky-Golay + SNV en `spectral_preprocessing.py`, aplicado en
   ambos pipelines (usuario y dataset), solo sobre la región con datos reales (no sobre el relleno de
   ceros — evita artefactos de suavizado en el salto abrupto).
6. ✅ Hecho: pipeline unificado — espectros de usuario también interpolan a `FIXED_GRID` y usan
   `vectorized_similarity`/`weighted_matrix_similarity`, misma escala que el dataset. Se retiró
   `search_similar_in_dataset_ultra_fast` (y `calculate_similarities_vectorized`,
   `normalize_spectra_batch`, que solo ella usaba); si el caché no cargó, `/search` responde 503 +
   `Retry-After: 5` (solo si tampoco hay resultados de usuario que devolver).
7. ✅ Hecho: `window_scores` real (`compute_window_scores`) con las 5 ventanas Flanigen + región
   estructural/no-estructural; score global ponderado 0.7/0.3 vía `weighted_matrix_similarity` para
   toda la matriz del dataset (2 operaciones matriciales, sigue siendo rápido) y `compute_window_scores`
   para el desglose de los top_n resultados finales y para comparaciones de un solo par.
8. ✅ Hecho: HQI = r² en las 3 rutas (`SimilarityCalculator.pearson_correlation`,
   `DatasetMatrixCache.search`, `vectorized_similarity`) en vez de `(r+1)/2`. Máscara de CO₂ atmosférico
   (2300-2400 cm⁻¹) aplicada antes de toda métrica.
9. ✅ Hecho: `tests/` con 48 tests pytest (preprocesamiento, SimilarityCalculator, endpoint `/search`
   completo con SQLite en memoria — incluye el caso 503 y la regresión directa del bug de Pearson).
   Correr con `pip install -r requirements-dev.txt && pytest`. Alembic inicializado en `alembic/`
   (`env.py` importa `Base` + todos los modelos, URL desde `settings.database_url`, override por
   `ALEMBIC_DATABASE_URL` para CI/tests). Migración baseline generada y verificada contra SQLite.
   **Importante al desplegar**: la BD de producción ya tiene las tablas (vía `create_all` +
   `migrate_users.py`) — correr `alembic stamp head`, NUNCA `upgrade head` directo (fallaría con
   "tabla ya existe"). Detalle completo en el docstring de la migración baseline. Las tablas del
   dataset (`zeolite_types` etc., creadas con SQL crudo en `zeolite_dataset_loader.py`) siguen sin
   modelo SQLAlchemy — Alembic no las gestiona (pendiente, no bloqueante).
10. **No estaba en el plan de esta sesión** (mencionado en el informe original pero no en el plan
    ejecutado): máscara de validez por espectro en el caché — el relleno con ceros fuera del rango
    medido sigue sesgando ligeramente normas/medias. Menor ahora que el score pondera por ventana.

### P3 — credibilidad científica y 3D
11. ✅ Hecho: dataset paramétrico por familia — `ZeoliteDatasetLoader.generate_family_bands()` sustituye
    el antiguo `CHARACTERISTIC_PEAKS` único (44 familias idénticas). Banda de anillo doble específica
    por framework (`ring_band_for_framework`: LTA=592, FAU=555 verificados por literatura; resto,
    posición determinista distinta por framework dentro del rango IZA 500-650, no verificada
    individualmente — ver docstring). ν_asym desplazada con Si/Al (`asymmetric_stretch_cm1`, dentro de
    920-1250 IZA). Mesoporosos amorfos (MCM-41/SBA-15/FDU-12/HMS/KIT-6) usan un perfil de sílice amorfa
    sin banda de anillo ficticia (`AMORPHOUS_MESOPOROUS_CODES`). Cada muestra/espectro se marca
    explícitamente `SYNTHETIC_DATA_NOTICE` en su columna `notes`. Códigos corregidos con fuente
    verificada: Zeolita T→OFF (intergrowth OFF/ERI), Zeolita W→MER. `generate_analysis` ya no asigna
    Si/Al aleatorio 1-100 independiente de la familia — usa el ratio real ±10% de jitter.
    19 tests en `tests/test_zeolite_dataset_loader.py`. **Pendiente** (no seleccionado esta sesión):
    corregir el resto de códigos IZA no verificados y espectros reales con DOI en vez de sintéticos.
12. ✅ Hecho: `seed_data.py` poblado (antes vacío, 0 bytes) con 10 familias IZA (LTA, FAU, MFI, MOR, CHA,
    BEA, FER, HEU, GIS, SOD) — Si/Al, tamaño/dimensionalidad de poro, `typical_bands` calculadas con las
    MISMAS funciones que el generador del dataset (coherencia catálogo↔espectros). Modelo `ZeoliteFamily`
    alineado con `ZeoliteFamilyResponse` (antes el schema exigía `si_al_ratio`/`pore_size`/`typical_bands`
    que no existían en el modelo → `ValidationError` en cuanto hubiera filas). Migración Alembic generada
    y verificada. Bug `db.func.count` corregido (`AttributeError`, faltaba `from sqlalchemy import func`).
    10 tests en `tests/test_zeolite_structure.py`.
13. ✅ Hecho: ingesta JCAMP-DX (.jdx/.dx/.jcm, vía librería `jcamp` — maneja SQZ/DIF/DUP y compound files,
    no reinventado) con conversión automática %T/Transmitancia→Absorbancia; CSV/TSV con sniffer de
    delimitador (`csv.Sniffer`, soporta coma decimal europea con `;`). El parser de texto plano original
    se mantiene intacto como fallback final. `parse_spectrum_file` en `spectra.py` ahora delega a
    `_parse_jcamp_dx`/`_parse_delimited_text`/`_parse_whitespace_columns` según detección de
    extensión+contenido. 13 tests en `tests/test_spectrum_parsing.py`.
    **Almacenamiento binario — alcance reducido deliberadamente**: migrar a binario comprimido
    (float32+zlib) tocaría prácticamente todo el código que lee/escribe `wavenumber_data` (spectra.py,
    similarity.py, similarity_calculator.py, schemas/spectrum.py) con alto riesgo de regresión sutil sin
    poder probar contra MySQL real. En su lugar apliqué el "mínimo inmediato" que el propio informe
    sugería: `spectrum.wavenumber_data` es ahora `Text().with_variant(LONGTEXT, "mysql")` (antes `Text`,
    límite real de 64 KB en MySQL con truncamiento SILENCIOSO — el bug real). Sigue siendo JSON de texto
    plano, cero cambios de serialización. Migración a binario comprimido queda como mejora de rendimiento
    futura, no de corrección.
14. ✅ Hecho: `/search` ahora persiste cada búsqueda en `SimilarityResult` (antes código muerto, el modelo
    existía pero ninguna ruta lo instanciaba) con `algorithm_version` (constante `ALGORITHM_VERSION` en
    `spectral_preprocessing.py`, incrementar el mayor si un cambio futuro altera scores existentes) y
    `min_similarity` real (antes hardcodeado a 0.5 en dos sitios, ahora expuesto en `SimilarityConfig` y
    respetado). Persistencia best-effort: un fallo al guardar el historial no rompe la respuesta al
    usuario (verificado con test). 4 tests en `tests/test_similarity_persistence.py`.
15. **Visor 3D — Fase 0 backend completa, incluye 5 CIF reales descargados**:
    - ✅ `GET /api/zeolites/{code}/structure` (`?format=json|cif`): metadatos + CIF si existe en
      `static/structures/{code}.cif`; 404 con instrucciones si no.
    - ✅ **5 CIF reales descargados** (con tu confirmación explícita) de la IZA Structure Database:
      `LTA.cif`, `FAU.cif`, `MFI.cif`, `MOR.cif`, `CHA.cif` — fuente
      `europe.iza-structure.org/IZA-SC/download_cif.php?ID=<id>`. Protegidos por
      `tests/test_zeolite_structure.py::test_downloaded_cif_exists_and_is_valid`. Pendientes: BEA, FER,
      HEU, GIS, SOD (instrucciones en `static/structures/README.md`).
    - `pymatgen` deliberadamente NO añadido a requirements.txt todavía — sería una dependencia pesada sin
      código que la use hasta que se implemente `scripts/expand_structures.py` (Fase 1: expansión de
      celda con índices atómicos estables para el mapeo banda↔átomos).
    - Pendiente: tablas `structural_units`/`band_assignments`/`atom_selections` (Fase 2, mapeo
      interactivo banda↔átomos).
16. ✅ Hecho: **frontend integrado y verificado en vivo** (proyecto Angular aparte en
    `C:\Users\luis_\ftir-zeolitas-uas\`, no vive en este repo). `Estructura3dComponent`
    (`shared/components/estructura-3d/`) con 3Dmol.js (npm `3dmol`, no CDN — evita tocar la CSP),
    llama a `GET /zeolites/{code}/structure` vía `ZeolitesService.getStructure()`, montado como modal
    en `busqueda.html` con botón "3D" por resultado (habilitado solo si `result.framework_code` viene
    del backend). Verificado extremo a extremo con navegador real: login, upload de espectro, búsqueda
    de similitud, click en "3D", canvas WebGL con la celda LTA renderizada (confirmado por muestreo de
    píxeles — color no blanco exactamente en el centro tras `zoomTo()`, no solo por presencia del canvas).
    - **Bug real encontrado y corregido**: `@ViewChild('viewerContainer', { static: true })` en
      `estructura-3d.ts` — el div `#viewerContainer` vive dentro de `*ngIf="!loading && !error &&
      structure"`, así que con `static: true` Angular resuelve la query ANTES de que el CIF llegue
      (async) y `viewerContainer` queda `undefined` para siempre; `renderStructure()` salía en silencio
      sin crear el canvas. Fix: `static: false` (default) + `ChangeDetectorRef.detectChanges()` síncrono
      justo antes de `renderStructure()` para forzar que Angular actualice el DOM (y por tanto la
      ViewChild query) antes de leer `viewerContainer.nativeElement`. Sin este fix el modal mostraba
      metadatos correctos pero el visor 3D quedaba vacío sin ningún error visible.
    - **Gotcha de entorno, no de código — RECURRENTE, revisar en cada sesión**: procesos uvicorn
      huérfanos ocupando el puerto 8000 en paralelo al servidor correcto. Windows permite que un
      proceso ligado a `127.0.0.1:8000` y otro ligado a `0.0.0.0:8000` coexistan "LISTENING" a la vez
      (`netstat -ano | grep :8000` los muestra a ambos); como `localhost` resuelve a `127.0.0.1`, las
      peticiones pueden caer en el proceso viejo con código desactualizado en vez del actual, dando
      404/500 "raros" que no calzan con el código en disco. Pasó DOS VECES en la misma sesión (2026-08-09):
      la primera vez el proceso viejo corría desde el repo principal (`C:\...\ftir-zeolitas-backend-uas\`,
      SIN `.claude\worktrees\...`, branch `main`, `.venv` propio) en vez de este worktree — probablemente
      una config de ejecución de PyCharm apuntando al repo raíz; la segunda vez fue el mismo patrón vía
      `uvicorn --reload` (el proceso reloader padre + su hijo worker sobreviven a un `taskkill` del PID
      "visible" en `tasklist` — hay que matar el PID que aparece en `netstat`, no asumir que el padre
      alcanza). Antes de diagnosticar cualquier 404/500 inesperado en zeolitas: `netstat -ano | grep
      :8000 | grep LISTENING` y matar TODO lo que no sea el servidor que tú arrancaste desde este
      worktree.
    - **Catálogo IZA expandido de 10 a 35 familias (2026-08-09)**: `seed_data.py` cubre ahora los ~34
      framework_code que aparecen en `zeolite_types` (antes solo 10, el botón "3D" fallaba con "familia
      no encontrada" para ~70% de los resultados de búsqueda: MCM-22/MWW, FDU-12/FDU12, etc.). Datos
      investigados vía workflow multi-agente (7 agentes, fuentes primarias IZA/patentes/papers cuando
      fue posible, con `confidence_note` documentando qué se verificó vs qué es aproximación coherente
      con el generador — detalle completo en el historial de sesión, no en la BD). `si_al_mid`/`pore_max`
      tomados de `ZEOLITE_TYPES` en `zeolite_dataset_loader.py` (misma fuente que usa
      `generate_family_bands`) para que catálogo y dataset sintético sigan siendo coherentes entre sí.
      Caso especial: el código `MER` (framework correcto para "Zeolita W" tras el fix ya aplicado en
      `zeolite_dataset_loader.py`) se catalogó también aunque **todavía no existe en la BD real** — el
      dataset persistido nunca se regeneró tras ese fix, así que `zeolite_types` sigue teniendo la fila
      vieja con el código `EAB` (catalogado igualmente, marcado como legado en su `description`).
      Pendiente si se quiere corregir del todo: `POST /api/dataset/clear` + `/load` para regenerar el
      dataset sintético con el mapeo correcto (acción no trivial — ~100s, invalida el caché `.npz` y
      cualquier `SimilarityResult`/IDs de espectro referenciados en pruebas en curso, por eso no se hizo
      sin pedirlo explícitamente).
    - **UX del modal 3D mejorada (2026-08-10)**, a partir de feedback directo del usuario:
      - `GET /{code}/structure` ahora expone `cif_permanently_unavailable` + `cif_unavailable_reason`
        (`app/routes/zeolites.py`, dict `NO_CIF_POSSIBLE_REASONS`) para los 6 códigos que NUNCA tendrán
        CIF — antes mostraban el mismo mensaje "todavía no descargado" + link a la IZA que las familias
        genuinamente pendientes, lo cual era engañoso (la IZA no tiene nada que encontrar para una sílice
        amorfa). El frontend (`estructura-3d.html`) ahora distingue ambos casos.
      - `Estructura3dComponent` (`estructura-3d.ts`) — `code` pasó a ser opcional
        (`@Input() code: string | null`). Cuando un espectro propio no tiene familia detectada
        ("Desconocido"), antes el botón "3D" quedaba deshabilitado sin más; ahora siempre se puede abrir
        y el componente muestra un `<select>` con las 35 familias del catálogo (`GET /api/zeolites`) para
        explorar cualquier estructura de referencia manualmente. El mismo selector queda disponible como
        "cambiar familia" en la cabecera una vez cargada una estructura, para comparar otras sin cerrar
        el modal. `busqueda.ts` `openStructure3d()` ya no bloquea con un mensaje de error si falta
        `framework_code` — abre el modal igual pasando `code: null`.
      - Bug de scroll corregido: el modal (`position: fixed`) no bloqueaba el scroll del `body`, así que
        hacer scroll con el mouse sobre el modal desplazaba la página de fondo por debajo del overlay —
        se sentía como que "todo se deslizaba". Fix: `document.body.style.overflow = 'hidden'` al abrir
        el modal (`openStructure3d`), restaurado al cerrar y en `ngOnDestroy`. También se igualó el
        `min-height` de los estados cargando/error/sin-código/sin-CIF (`estructura-3d.css`) para reducir
        el salto de tamaño entre el spinner inicial y el contenido final.
      - **Root cause real del "modal se desliza" (2026-08-10, segunda vuelta)**: el fix anterior
        (bloquear `document.body.style.overflow`) no era suficiente — el usuario reportó capturas donde
        el modal aparecía cortado/desplazado según el scroll de la tabla de resultados. Causa real:
        `dashboard.css` usa `backdrop-filter: blur(...)` en `.main-content`/`.sidebar`/header (efecto
        glassmorphism), y por spec de CSS `backdrop-filter`/`filter`/`transform` != none en un ancestro
        crean un nuevo *containing block* para descendientes `position: fixed` — el overlay casero de
        `busqueda.html` quedaba posicionado relativo a `.main-content` (que tiene su propio scroll) en
        vez del viewport real. Fix definitivo: reemplazar el `*ngIf` casero por **Angular Material
        `MatDialog`** (`estructura-3d.ts` ahora recibe `MAT_DIALOG_DATA`/`MatDialogRef` en vez de
        `@Input() code`) — CDK Overlay siempre monta el panel como hijo directo de `<body>`, inmune al
        problema. De paso resuelve el pedido de "modal más grande": `dialog.open(..., {width: '92vw',
        maxWidth: '1100px', height: '88vh', maxHeight: '850px'})` en `busqueda.ts`. Requirió agregar
        `provideAnimationsAsync()` a `app.config.ts` (Material lo necesita) y overrides en `styles.css`
        global (`.estructura-3d-dialog-panel .mdc-dialog__surface { padding: 0; }`, ya que Material
        pone ~24px de padding por defecto y el componente ya maneja su propio `.dialog-header`/
        `.dialog-body`). `@angular/cdk`/`@angular/material` ya estaban en package.json (instalados sin
        usar, per nota previa de esta sesión) — no se agregó dependencia nueva. Verificado en navegador
        real reproduciendo exactamente el bug (`document.body.scrollTop = 900` antes de abrir el
        diálogo): el panel queda perfectamente centrado en el viewport real, no en el contenedor
        scrolleado. La CSS del modal casero (`.modal-overlay`/`.modal-3d*` en `busqueda.css`) y el
        `document.body.style.overflow` manual se eliminaron por completo — CDK Overlay ya bloquea el
        scroll de fondo correctamente por sí solo.
      - **Recordatorio operativo**: el backend de este worktree NO corre con `--reload` (para evitar el
        patrón de conflicto de puerto con PyCharm ya documentado arriba) — cualquier cambio en archivos
        `.py` requiere matar y relanzar manualmente el proceso (`taskkill //PID <pid> //F` + volver a
        `uvicorn main:app --host 0.0.0.0 --port 8000`) para que se refleje. Los cambios de frontend
        (Angular) sí se recargan solos vía HMR de `ng serve`.
    - **Bug de URL corregido**: `cif_source_hint` en `GET /{code}/structure` incluía el texto humano
      `"(buscar 'CODE')"` concatenado dentro de la propia URL — el frontend lo usaba tal cual como
      `[href]`, y el navegador codificaba el paréntesis como parte de la ruta → 404 en el sitio de la
      IZA al hacer clic en "Ver en la IZA Structure Database". Fix: el backend devuelve solo la URL
      limpia; el código a buscar se muestra aparte en el texto visible del link (`estructura-3d.html`).
    - **Proyecto nuevo, separado de este repo**: `C:\Users\luis_\iza-cif-downloader\` —
      `descargar_iza.py` descarga los ~271 CIF de framework idealizado de la IZA-SC completa (no solo
      los usados por este dataset), con `metadata.csv` (fórmula/grupo espacial/celda vía `gemmi`) y
      `README.txt`. Corrido completo (2026-08-10): 258 descargados, 2 sin CIF, 10 ya existían.
    - **`static/structures/` ampliado a 29/35 familias (2026-08-10)** — antes solo 5. Copiados desde
      `iza-cif-downloader/cif/` los 25 códigos directos + 3 alias (LEO→LAU, HAR→PHI, NU10→TON, mismo
      framework real, código de catálogo no es un framework IZA independiente) + BEA (caso especial:
      Beta es un intercrecimiento de polimorfos sin CIF idealizado propio, se usa el polimorfo
      mayoritario Beta_A vía `DO_structures/Download_DO_cif.php?ID=10001`, no la ruta normal
      `download_cif.php`). Los 6 restantes (NU86, MCM41, SBA15, FDU12, HMS, KIT6) NUNCA tendrán CIF —
      no es un pendiente, es una limitación real (NU86 sin código IZA asignado; las 5 sílices son
      amorfas, sin estructura cristalina que describir). Detalle completo y fuente de cada uno en
      `static/structures/README.md`. Protegido por 3 grupos de tests en
      `tests/test_zeolite_structure.py` (directos/alias/sin-CIF-permanente). Verificado en navegador
      real: canvas WebGL con contenido no-blanco para Laumontita (antes mostraba el fallback "CIF aún
      no descargado").
17. ✅ Hecho (2026-08-11): **auto-clasificación de familia al subir un espectro sin material** — antes
    todo espectro subido sin campo material explícito quedaba "Desconocido" para siempre y el visor 3D
    exigía elegir la familia a mano. `app/routes/spectra.py` añade `_suggest_family(wavenumbers,
    absorbance)`: si `dataset_matrix_cache.loaded`, reutiliza el MISMO motor que `/search`
    (`dataset_matrix_cache.search(..., method="cosine", min_similarity=0.5, top_n=1)`) para comparar el
    espectro recién subido contra el dataset de referencia; best-effort (cualquier excepción se loguea y
    devuelve `None`, nunca rompe la subida). `upload_spectrum` solo la invoca cuando no llega `material`;
    si hay sugerencia, `spectrum.material` se guarda como el `framework_code` sugerido (no "Desconocido");
    la respuesta incluye `material_suggestion: {code, zeolite_name, confidence}` para que el frontend
    muestre la sugerencia como tal (con % de confianza), no como un hecho — mismo patrón de transparencia
    que `cif_unavailable_reason`. 4 tests nuevos en `tests/test_spectrum_auto_classification.py` (137
    tests totales).
    **Bug real encontrado y corregido, causa raíz de por qué NUNCA se veía en la práctica**:
    `cargar-espectro.ts` (frontend) tenía `material = 'Zeolita Y'` hardcodeado como default — el
    formulario de carga no tiene NINGÚN campo editable para material, así que ese literal se enviaba
    siempre, jamás vacío, y por tanto `_suggest_family` nunca se ejecutaba (la condición es "material no
    especificado"). Fix: `material = ''`. Sin este fix el backend funcionaba perfectamente pero era
    inalcanzable desde la UI real.
    Frontend: `spectra-backend.service.ts` añade `MaterialSuggestion` y
    `UploadResponse.data.material_suggestion?`; `cargar-espectro.ts` guarda la sugerencia por ítem de la
    cola (`UploadQueueItem.materialSuggestion`); `cargar-espectro.html` muestra un badge
    "🧬 {nombre} ({código}) · {confianza}% confianza" junto al mensaje de éxito de cada archivo, con
    tooltip explicando que es una sugerencia por similitud y que se puede cambiar desde el visor 3D.
    Verificado backend con curl end-to-end (`material_suggestion` presente y `spectrum.material` seteado
    al código sugerido). Verificado que el frontend compila sin errores nuevos en consola tras los
    cambios (solo warnings preexistentes: plotly CDN, CSP `frame-ancestors` en `<meta>`, `NG0100`, ninguno
    relacionado). **No verificado con clic real de extremo a extremo en el navegador** — el flujo de login
    de la UI requiere escribir credenciales en el formulario, acción que el harness bloquea por política
    de seguridad (entrada de credenciales en campos de login); pendiente que el usuario confirme
    visualmente el badge en su propia sesión autenticada.
18. **PENDIENTE — mejoras para exactitud científica real, no solo transparencia sobre la incertidumbre**
    (surgió al verificar manualmente si un espectro real de laboratorio, "EL-17 Cu00", correspondía a la
    familia MWW que la auto-clasificación le asignó con 69% de confianza — la banda diagnóstica principal
    del espectro real, 999 cm⁻¹, no calzaba ni con el valor sintético de MWW (~1042 cm⁻¹) ni con literatura
    real de MCM-22 (~1090-1230 cm⁻¹), aunque otras bandas sí coincidían razonablemente):
    - **Reemplazar el dataset sintético por espectros reales de referencia — cambio de mayor impacto.**
      Cada "familia" hoy es una fórmula matemática (`asymmetric_stretch_cm1`, `ring_band_for_framework`
      en `zeolite_dataset_loader.py`), no una medición real; por eso las posiciones de banda pueden
      desviarse de literatura para frameworks no verificados individualmente (solo LTA=592 y FAU=555 en
      `VERIFIED_RING_BAND_CM1` están confirmados por fuente). Si el usuario tiene acceso a estándares
      comerciales o muestras de composición conocida (p.ej. zeolita Y, ZSM-5, mordenita, ferrierita —
      típicas en catálisis Cu-SCR), medirlas y cargarlas como referencia verificada movería el sistema de
      "aproximación matemática" a "comparación real". Requiere trabajo de datos del usuario, no solo código.
    - **Complementar con una técnica ortogonal — XRD como estándar de oro para identificar framework.**
      FTIR solo mide entorno vibracional T-O-T local; nunca distingue con certeza total entre familias de
      topología similar. Si hay (o se pueden conseguir) difractogramas XRD de las muestras, podrían usarse
      para confirmar/descartar la sugerencia de FTIR en vez de depender de una sola técnica.
    Ninguna de las dos se implementó esta sesión — ambas requieren datos que el usuario todavía no ha
    proporcionado (espectros de referencia medidos, o difractogramas). Ver también pendiente #10 (máscara
    de validez) y la limitación ya documentada arriba: "Dataset 100% sintético... no discrimina familias".
19. ✅ Hecho (2026-08-11/12): **eliminar espectro con historial de búsquedas asociado, formatos no
    soportados en la subida, y auditoría de mensajes de error backend↔frontend** — a partir de un
    traceback real del usuario (`IntegrityError` al hacer `DELETE /spectra/{id}`).
    - **Bug real: `DELETE /spectra/{id}` fallaba con 500 si el espectro ya tenía una búsqueda de
      similitud guardada.** `similarity_results.query_spectrum_id` (FK a `spectra.id`) no tenía
      `ondelete` definido → MySQL rechazaba el DELETE (`IntegrityError 1451`). Fix: `ondelete="CASCADE"`
      en el modelo (`app/models/similarity_result.py`) + migración `f20fcc4f3e94` (DROP/CREATE de la FK
      `similarity_results_ibfk_2` con `ON DELETE CASCADE`), aplicada contra la BD real y verificada
      (`DELETE_RULE='CASCADE'` en `information_schema.REFERENTIAL_CONSTRAINTS`). Borrar un espectro ahora
      borra en cascada su historial de búsquedas — no tiene sentido sin el espectro que lo originó.
      Catch defensivo adicional de `IntegrityError` en `delete_spectrum` (409, mensaje claro) por si en el
      futuro otra tabla referencia `spectra.id` sin cascada. 2 tests nuevos en `tests/test_spectrum_deletion.py`
      (cascada real contra SQLite con `PRAGMA foreign_keys=ON`, y regresión del caso sin historial).
    - **Formatos sin parser real (`.xlsx`, `.json`, ofrecidos por el selector de archivos del frontend
      pero nunca soportados) fallaban con "no se encontraron datos numéricos válidos" — engañoso para un
      binario, y además se devolvía como 500 genérico, no 422.** `parse_spectrum_file`
      (`app/routes/spectra.py`) ahora rechaza explícitamente `UNSUPPORTED_EXTENSIONS` (xlsx, xls, json,
      pdf, doc, docx, png, jpg, jpeg) con un mensaje que nombra el formato y lista los soportados
      (JCAMP-DX, CSV/TSV, texto plano). `upload_spectrum` captura `ValueError` de `parse_spectrum_file` y
      lo expone como 422 con el mensaje real, en vez de caer al catch-all genérico (500 "Error al cargar
      espectro"). Frontend: `cargar-espectro.html` quitó `.json`/`.xlsx` del `accept` del input de
      archivo (nunca funcionaron) y agregó tarjetas informativas para CSV/TSV y JCAMP-DX (soportados pero
      no documentados antes) más una nota explícita de formatos no compatibles. 4 tests nuevos en
      `tests/test_spectrum_parsing.py` + 1 en `tests/test_spectrum_auto_classification.py` (ruta
      `upload_spectrum` completa, vía `asyncio.run` — el proyecto no tiene `pytest-asyncio` configurado,
      se evitó agregarlo por una sola prueba).
    - **Bug real encontrado al auditar: `spectra-backend.service.ts` (frontend) NUNCA leía
      `error.error.detail` del backend** — hardcodeaba un mensaje genérico por código HTTP (404/401/403/
      500) y para cualquier otro código (como los 422/409 nuevos) mostraba
      `Error ${status}: ${error.message}` (el `.message` genérico de Angular, tipo "Http failure
      response for ...", NO el mensaje del backend). Esto habría hecho invisibles todos los mensajes
      claros agregados en esta sesión. Corregido para priorizar `error.error.detail` (mismo patrón ya
      usado correctamente en `similarity-backend.service.ts`/`zeolites.service.ts`/
      `auth-backend.service.ts`, que no se tocaron por ya estar bien). Además, `cargar-espectro.ts` tenía
      una SEGUNDA capa de traducción (`getErrorMessage`) que pisaba el mensaje específico de 422/500 con
      uno genérico propio — simplificada para confiar en el mensaje ya final del servicio
      (`error?.message`).
    - **Bug de diseño real: `.queue-message` en `cargar-espectro.css` tenía `white-space: nowrap` sin
      max-width, dentro de una fila con `overflow: hidden`** — un mensaje de error largo y claro (el
      objetivo mismo de esta sesión) se habría cortado en silencio. Fix: los mensajes de error ahora se
      muestran en `.queue-error-message`, una fila completa propia (mismo patrón `grid-column: 1 / -1`
      que ya usa `.queue-suggestion`) con `white-space: normal` para que el texto envuelva.
    - Auditoría del resto de `raise HTTPException` en `app/routes/` (51 en total): reescritos los
      genéricos poco accionables ("Error en base de datos", "Error obteniendo dataset", etc.) a mensajes
      en español que dicen qué falló y qué hacer, en `spectra.py`, `similarity.py`, `dataset.py`,
      `zeolites.py`. `admin.py` y `auth.py` ya estaban en buen estado — **no tocar**
      `detail="EMAIL_NOT_VERIFIED"`/`"ACCOUNT_PENDING_APPROVAL"` en `auth.py`: son sentinels literales que
      `login-modal.ts` compara con `===` para decidir qué UI mostrar, no texto para el usuario.
    Suite completa: 146 tests pasan (137 + 9 nuevos). Verificado end-to-end con curl contra el servidor
    real (`127.0.0.1:8000`, main, tras merge): `DELETE` de un espectro con historial real → 200 y
    cascada confirmada en BD; subida de `.xlsx` → 422 con el mensaje exacto esperado. **No verificado con
    clic real en el navegador** (mismo bloqueo de seguridad que el pendiente #17: el harness no permite
    escribir credenciales en el formulario de login) — sí se confirmó que el frontend compila sin errores
    nuevos en consola tras los cambios de HTML/CSS/TS.
    **Revisión de seguridad (`/security-review`, 2026-08-12)** sobre este mismo diff: sin hallazgos con
    confianza ≥8 (cascada de FK no permite borrar datos de otro usuario — sigue acotada por
    `Spectrum.user_id == current_user.id`; `str(e)` en el 422 solo refleja el propio archivo del usuario
    o texto estático). Un candidato de higiene de código sí se corrigió de todas formas: el
    `except ValueError` en `upload_spectrum` envolvía toda la función, incluyendo
    `SpectrumResponse.model_validate(...)` DESPUÉS del `db.commit()` — como `pydantic_core.ValidationError`
    es subclase de `ValueError` en Pydantic v2, un fallo de validación ahí habría reexpuesto texto interno
    de Pydantic en el 422 en vez de caer al catch-all genérico. Acotado: el `try/except ValueError` ahora
    envuelve solo la llamada a `parse_spectrum_file`.
20. ✅ Hecho (2026-11-02): **módulo Proyectos** (cuaderno de laboratorio personal, opciones A+B acordadas con
    el usuario: proyectos personales, mismos formatos que "Cargar espectro"). Backend: `app/models/project.py`
    (`projects`, `project_files`, `project_file_versions`, `project_activity`; migración `a91c3d5e7b02`,
    aplicada), `app/routes/projects.py` (`/api/projects`). Reglas de diseño: todo filtrado por dueño y lo ajeno
    responde 404 (no 403); los datos NUNCA se sobrescriben — cada edición (nota, reemplazo, recorte de rango,
    restauración) crea una versión nueva con SHA-256 y `change_reason` OBLIGATORIO (≥3 caracteres); la bitácora
    (`project_activity`) solo se agrega y conserva `file_name` aunque el archivo se borre. Archivos = espectros
    (se parsean con `parse_spectrum_file`, así que los formatos son exactamente los de la carga normal;
    límite 5 MB, 100 000 puntos, 200 archivos/proyecto) y notas de texto (200 000 caracteres). Nombres
    se reducen al nombre base (sin rutas). Contenido en LONGTEXT (no en disco → sin path traversal).
    "Duplicar" copia la última versión de cada archivo a un proyecto nuevo (`derived_from_id`) para reutilizar
    en investigaciones futuras. **Biblioteca de referencia verificada**: un espectro del proyecto marcado
    `is_reference` con `family_code` (confirmado por el investigador, p. ej. con DRX) entra como candidato en
    `/api/similarity/search` (`source: "project_reference"`, `spectrum_id: null`, trae `project_id`/`file_id`),
    solo para su dueño — es el primer paso real hacia el pendiente #18 (espectros reales como referencia).
    18 tests en `tests/test_projects.py` (163 en total). Frontend (`ftir-zeolitas-uas`, sin commitear):
    `core/services/projects.service.ts`, `modules/proyectos/` (lista, detalle con arrastrar y soltar +
    bitácora, archivo con gráfica Chart.js, versiones, recorte, reemplazo, referencia), rutas
    `/dashboard/proyectos[/:id[/archivo/:fid]]` y entrada "Proyectos" en el menú. Verificado: API de
    punta a punta con curl contra servidor real (crear, subir, recortar, restaurar, 404 de otro usuario,
    rechazo de .xlsx, borrado en cascada) y Angular compila sin errores. **No verificado con clic real en el
    navegador** (mismo bloqueo de login que #17). En Búsqueda, los resultados `project_reference` se etiquetan
    "Referencia verificada" y su botón Ver queda deshabilitado (no tienen `spectrum_id`).
21. Preparado (2026-11-22), NO ejecutado todavia: **despliegue en VPS de Hostinger** desde PowerShell. Todo en
    `deploy/` (ver `deploy/README.md`): Docker Compose con MySQL 9.4 + backend + Caddy (HTTPS automatico),
    scripts `deploy/scripts/00..04*.ps1` (preparar servidor, migrar BD local con mysqldump -> gzip -> scp ->
    import, desplegar con `git archive` + `ng build`, estado, respaldo). Secretos solo en `/opt/ftir/.env` del
    servidor (generados al azar, nunca viajan desde el PC). Cambios de codigo: `CORS_ORIGINS` por variable de
    entorno y freno en `app/core/config.py` (con `ENVIRONMENT=production` no arranca con `SECRET_KEY` por
    defecto o corta); frontend `environment.prod.ts` -> `apiUrl: '/api'` (repo del frontend, sin commitear).
    El proyecto gym-app-heros (ATDLRUT) se desplego en Render+Neon, no en Hostinger: no hay precedente a copiar.
    Pendiente: dominio, IP/usuario SSH del VPS y rellenar `deploy.config.ps1`. Probado localmente: sintaxis de
    los .ps1, `git archive` sin `.env`, `mysqldump` real (443 MB, 15 tablas); NO probado contra un servidor.

