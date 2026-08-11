# Estructuras cristalográficas (CIF)

Este directorio aloja los archivos `.cif` de las familias de zeolitas servidos
por `GET /api/zeolites/{code}/structure` para el visor 3D banda↔estructura.

## Estado (2026-08-10)

✅ **29 de las 35 familias del catálogo tienen CIF real**, descargados con el
proyecto separado `C:\Users\luis_\iza-cif-downloader\descargar_iza.py` (271
frameworks IZA descargados en total, se copiaron aquí los que corresponden a
`seed_data.py`). Fuente: `https://europe.iza-structure.org/IZA-SC/download_cif.php?ID=<id>`.
Estructuras idealizadas SiO2 puro (DLS76) — no incluyen Al ni cationes de
compensación. Cada archivo trae la atribución original de Baerlocher/McCusker.

- **25 códigos directos** (el código de catálogo es el framework IZA real):
  LTA, FAU, MFI, MOR, CHA, FER, HEU, GIS, SOD, AEI, ATN, EAB, MER, NAT, GON,
  LAU, BRE, STI, MEL, MTT, TON, AFI, LTL, MWW, ERI.
- **BEA**: no tiene CIF idealizado propio — Beta es un intercrecimiento de
  polimorfos (A/B/CH) sin una única estructura ordenada, gestionado por la
  IZA en su base de datos de estructuras *desordenadas*
  (`DO_structures/DO_family.php?ID=1`), no en la tabla de frameworks normal.
  Se usa el polimorfo mayoritario **Beta_A** como representación 3D razonable
  (`Download_DO_cif.php?ID=10001`).
- **3 alias** — no son códigos de framework IZA independientes, reutilizan el
  CIF real del framework del que son sinónimo (mismo archivo físico, ver
  `confidence_note` de cada uno en `seed_data.py`):
  - `LEO.cif` = copia de `LAU.cif` (Leonhardita es la laumontita deshidratada,
    la IZA no le da código propio).
  - `HAR.cif` = copia de `PHI.cif` (Harmotoma comparte oficialmente el código
    de framework PHI con la phillipsita).
  - `NU10.cif` = copia de `TON.cif` (NU-10 es isoestructural con Theta-1/
    ZSM-22, framework IZA real = TON).

⛔ **6 códigos sin CIF, permanentemente** (no es un pendiente, es una
limitación real de los materiales):
- `NU86` — la IZA nunca le asignó código de framework de 3 letras (confirmado
  en patentes ICI/IFP US6165439 y US6337428).
- `MCM41`, `SBA15`, `FDU12`, `HMS`, `KIT6` — sílices mesoporosas **amorfas**,
  sin cristalinidad de largo alcance. No existe un CIF que descargar porque no
  hay una estructura cristalina periódica que describir; el visor 3D siempre
  mostrará solo metadatos para estas 5.

Protegido por 3 grupos de tests en `tests/test_zeolite_structure.py`: códigos
directos, códigos alias (verifican que apuntan al `data_` tag del framework
real, no al código de catálogo), y códigos sin CIF (verifican que
*siguen sin existir* — si alguno aparece con `.cif` en el futuro sin que se
haya investigado por qué, es una señal de alerta, no una mejora silenciosa).

## Cómo añadir más CIF

1. Buscar el ID numérico del framework en
   https://europe.iza-structure.org/IZA-SC/ftc_table.php (la URL usa
   `framework.php?ID=<numero>`, no el código directamente).
2. Descargar de `https://europe.iza-structure.org/IZA-SC/download_cif.php?ID=<id>`.
3. Guardar aquí como `{CODE}.cif` (mayúsculas, p.ej. `BEA.cif`).

El endpoint detecta automáticamente el archivo por el campo `cif_filename` de
`ZeoliteFamily` (por defecto `{code}.cif`) y responde con metadatos + CIF si
existe, o con un mensaje claro (`cif_available: false` + `cif_source_hint`) si
todavía no se ha añadido. Protegido por `tests/test_zeolite_structure.py`.
