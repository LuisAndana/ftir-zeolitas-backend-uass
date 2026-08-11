"""
Seed del catálogo de referencia de familias de zeolitas (ZeoliteFamily).

ANTES: este archivo estaba vacío (0 bytes) — GET /api/zeolites devolvía
siempre lista vacía y GET /{code} siempre 404 (ver CLAUDE.md, gotcha conocida).

Datos verificados contra:
- IZA "Characterization by IR spectroscopy" (iza-online.org/synthesis/VS_2ndEd/
  IR_Spectroscopy.htm) para los rangos Flanigen-Khatami-Szymanski.
- Literatura específica de banda de anillo doble para LTA (D4R ~592 cm⁻¹) y
  FAU (D6R ~555 cm⁻¹) — ver docstring de ZeoliteDatasetLoader.
- IZA Structure Database (europe.iza-structure.org) para tamaño de poro,
  dimensionalidad de canal y tamaño de anillo — valores de uso común en la
  literatura de zeolitas, no todos re-verificados individualmente en esta sesión.

typical_bands se calcula con las MISMAS funciones que usa el generador del
dataset sintético (ZeoliteDatasetLoader.ring_band_for_framework /
asymmetric_stretch_cm1 / pore_opening_cm1), para que el catálogo de referencia
y el dataset de espectros sean coherentes entre sí.

Uso: python seed_data.py
"""
import logging
import sys

from app.core.database import SessionLocal, init_db
from app.models.zeolite_family import ZeoliteFamily
from app.services.zeolite_dataset_loader import ZeoliteDatasetLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _typical_bands(structure_type: str, si_al_mid: float, pore_max: float) -> list:
    """Bandas diagnósticas (cm⁻¹), consistentes con generate_family_bands.

    Las 5 sílices mesoporosas amorfas (AMORPHOUS_MESOPOROUS_CODES) no tienen
    anillos D4R/D6R cristalinos — generate_family_bands les da un perfil fijo
    de sílice amorfa en vez de las bandas paramétricas por Si/Al y tamaño de
    poro; replicamos aquí las 3 bandas "estructurales" (se omiten O-H/H2O por
    ser dependientes de hidratación, igual que en la rama cristalina)."""
    if structure_type in ZeoliteDatasetLoader.AMORPHOUS_MESOPOROUS_CODES:
        return sorted([800.0, 960.0, 1080.0])
    ring = ZeoliteDatasetLoader.ring_band_for_framework(structure_type)
    asym = ZeoliteDatasetLoader.asymmetric_stretch_cm1(si_al_mid)
    pore = ZeoliteDatasetLoader.pore_opening_cm1(pore_max)
    return sorted([round(pore, 1), 460.0, round(ring, 1), 685.0, round(asym, 1)])


# (code, name, category, chemical_formula, si_al_ratio, pore_size, ring_size,
#  channel_dimensionality, si_al_mid_for_bands, pore_max_for_bands, description)
FAMILIES = [
    ("LTA", "Linde Type A", "poro pequeño", "Na12[(AlO2)12(SiO2)12]·27H2O",
     "1.0-1.5", "4.1 Å (ventana 8-MR)", "8-MR", "3D", 1.0, 4.0,
     "Zeolita A; anillos dobles D4R muy característicos (~592 cm⁻¹). Deshidratación, "
     "separación de gases. Miembros comunes: 3A/4A/5A según catión de compensación."),
    ("FAU", "Faujasita", "poro grande", "Na58[(AlO2)58(SiO2)134]·240H2O",
     "1.0-3.0+", "7.4 Å (ventana 12-MR)", "12-MR", "3D", 1.5, 7.4,
     "Zeolitas X (Si/Al bajo) e Y (Si/Al alto); anillos dobles D6R (~555 cm⁻¹). "
     "Craqueo catalítico (FCC), adsorción de alta capacidad."),
    ("MFI", "ZSM-5 / Silicalita", "poro mediano", "Nan[AlnSi96-nO192]·16H2O",
     "10-∞ (silicalita: Si puro)", "5.1×5.6 Å (10-MR)", "10-MR", "3D", 20.0, 5.5,
     "Canales intersectantes rectos y en zigzag (pentasil); catálisis ácida, "
     "conversión de metanol a hidrocarburos."),
    ("MOR", "Mordenita", "poro grande/mediano", "Na8[(AlO2)8(SiO2)40]·24H2O",
     "5.0-10.0", "6.5×7.0 Å (12-MR) + 2.6×5.7 Å (8-MR)", "12-MR/8-MR", "1D (canal principal)", 5.0, 6.7,
     "Estructura cuasi-unidimensional; craqueo, isomerización, deshidratación."),
    ("CHA", "Chabazita", "poro pequeño", "Ca2[(AlO2)4(SiO2)8]·13H2O",
     "1.0-∞ (SAPO-34/SSZ-13 muy silíceas)", "3.8 Å (ventana 8-MR)", "8-MR", "3D", 1.5, 3.8,
     "Anillos dobles D6R como FAU pero con arreglo distinto; catálisis MTO, "
     "reducción catalítica selectiva (SCR) de NOx (Cu-CHA)."),
    ("BEA", "Beta", "poro grande", "Nan[AlnSi64-nO128]·nH2O",
     "5.0-∞", "5.5×7.6 Å y 5.6×5.6 Å (12-MR)", "12-MR", "3D", 12.0, 6.5,
     "Estructura intercrecida (polimorfos A/B); síntesis orgánica, alquilación."),
    ("FER", "Ferrierita", "poro mediano", "Na1.5Mg2[(AlO2)5.5(SiO2)30.5]·18H2O",
     "~8.0-10.0", "4.2×5.4 Å (10-MR) + 3.5×4.8 Å (8-MR)", "10-MR/8-MR", "2D", 8.5, 5.0,
     "Poros elípticos intersectantes; isomerización de olefinas."),
    ("HEU", "Heulandita / Clinoptilolita", "poro mediano", "Ca4[(AlO2)8(SiO2)28]·24H2O",
     "~3.0-4.5", "4.4×7.2 Å (10-MR)", "10-MR", "2D", 4.0, 5.5,
     "Zeolita natural muy abundante; tratamiento de aguas, agricultura."),
    ("GIS", "Gismondina", "poro pequeño", "Ca4[(AlO2)8(SiO2)8]·16H2O",
     "~1.0", "2.8×4.7 Å (8-MR)", "8-MR", "3D", 1.0, 3.5,
     "Zeolita P; estructura policatiónica de poro pequeño."),
    ("SOD", "Sodalita", "poro muy pequeño", "Na8[(AlO2)6(SiO2)6]Cl2",
     "~1.0-2.0", "2.2-2.8 Å (ventana 6-MR a la caja sodalita)", "6-MR", "caja (0D efectivo)", 1.5, 2.4,
     "Unidad de construcción (β-cage) presente en LTA, FAU y otras; poro "
     "prácticamente inaccesible a temperatura ambiente."),

    # ------------------------------------------------------------------
    # Expansión 2026-08-09: 25 familias más (10 -> 35), investigadas para
    # cubrir los 24 framework_code que aparecen en zeolite_types pero no
    # tenían entrada de catálogo (GET /{code}/structure devolvía 404 "no
    # encontrada" para la mayoría de resultados de búsqueda) + MER (el
    # código correcto para "Zeolita W" en zeolite_dataset_loader.py — el
    # dataset persistido en MySQL todavía tiene la fila vieja con EAB
    # porque nunca se regeneró tras esa corrección; se cataloga EAB aquí
    # como código heredado/obsoleto y también MER para cuando se regenere).
    # si_al_mid/pore_max tomados de ZEOLITE_TYPES en zeolite_dataset_loader.py
    # (mismos valores que usa generate_family_bands) para coherencia
    # catálogo↔dataset; campos condensados para caber en los VARCHAR reales
    # (ver test_seed_data_fields_fit_column_limits) — el detalle completo de
    # cada verificación queda en el historial de la sesión, no en la BD.
    # ------------------------------------------------------------------
    ("AEI", "SSZ-39 (AEI)", "poro pequeño", "Mx[(AlO2)x(SiO2)y]·wH2O (SDA: TMAda+, tipo SSZ-39)",
     "2.0-4.0", "3.8×3.8 Å (ventana 8-MR)", "8-MR", "3D", 2.5, 3.8,
     "Capas de dobles anillos D6R apiladas ABABAB (a diferencia de CHA), generan cajas 'aei' y "
     "canales 8-MR 3D. Su forma Cu-SSZ-39 es catalizador comercial de SCR de NOx."),
    ("ATN", "MAPO-39 (ATN)", "poro pequeño",
     "Prototipo aluminofosfato Al7MgHP8O32 (no aluminosilicato clásico); análogo Mx[(AlO2)x(SiO2)y]·wH2O",
     "2.0-4.0", "~4.0 Å (ventana 8-MR)", "8-MR", "1D", 3.0, 4.5,
     "Canales 1D de ~4 Å a lo largo del eje c, sin interconexión entre canales. Prototipo real es "
     "el aluminofosfato metálico MAPO-39 (Mg,Al-P-O), no un aluminosilicato clásico."),
    ("EAB", "Bellbergita (EAB)", "poro pequeño", "(K,Ba,Sr)2Sr2Ca2(Ca,Na)4[Al18Si18O72]·30H2O",
     "1.0-2.0", "~3.9-4.0 Å (ventana 8-MR)", "8-MR", "3D", 1.5, 4.0,
     "Familia ABC-6 emparentada con cancrinita/erionita/gmelinita. Código legado: el dataset "
     "sintético mapeaba antes 'Zeolita W' a EAB; ya corregido a MER en el generador, pendiente "
     "regenerar el dataset para que desaparezca de zeolite_types."),
    ("MER", "Merlinoita (Zeolita W)", "poro pequeño",
     "Mx[(AlO2)x(SiO2)y]·wH2O (K10[(AlO2)10(SiO2)22]·nH2O en zeolita-W sintética)",
     "1.0-2.5", "3.4×5.1 + 2.7×3.6 + 3.1×3.5 Å (3 canales 8-MR)", "8-MR", "3D", 1.5, 3.6,
     "Cadenas dobles 'cigüeñal' de anillos de 4, con tres sistemas de canales 8-MR que se "
     "intersectan. Su análogo sintético 'Zeolita W' se usa en separación de gases y como "
     "intercambiador K+/NH4+."),
    ("NAT", "Natrolita", "poro pequeño", "Na2[(AlO2)2(SiO2)3]·2H2O",
     "1.0-1.5", "2.6×3.9 Å (ventana 8-MR)", "8-MR", "3D", 1.0, 2.6,
     "Zeolita fibrosa mineral tipo del grupo natrolita (junto con mesolita y escolecita); cadenas "
     "de tetraedros con canales 8-MR a lo largo del eje c. Modelo clásico en transiciones de fase "
     "por presión/deshidratación."),
    ("GON", "Gonnardita", "poro pequeño", "(Na,Ca)2(Al,Si)5O10·3H2O (Si/Al desordenado)",
     "1.4-2.2", "~3.5 Å (topología tipo NAT, 8-MR)", "8-MR", "3D", 1.8, 3.5,
     "Zeolita fibrosa del grupo natrolita, con Si/Al desordenado (confirmado por RMN). El código "
     "IZA oficial 'GON' corresponde en realidad a GUS-1 (galosilicato no relacionado); esta "
     "entrada describe la gonnardita mineral (topología NAT)."),
    ("LAU", "Laumontita", "poro mediano", "Ca[(AlO2)2(SiO2)4]·4H2O",
     "1.6-2.2", "4.6×6.3 Å (ventana 10-MR)", "10-MR", "1D", 1.8, 4.8,
     "Zeolita natural de poro mediano, común en rocas de bajo grado metamórfico. Canal 1D de 10 "
     "anillos que se colapsa parcialmente al deshidratarse (variedad leonhardita). Muy sensible a "
     "la humedad ambiental."),
    ("LEO", "Leonhardita (laumontita deshidratada)", "poro mediano", "Ca[(AlO2)2(SiO2)4]·3.5H2O",
     "1.7-2.3", "~4.1 Å (10-MR contraído, estimado)", "10-MR", "1D", 2.0, 4.1,
     "No es un framework IZA independiente: es la forma parcialmente deshidratada de LAU (pérdida "
     "de agua del sitio W1). El colapso parcial del canal reduce la apertura efectiva frente a la "
     "laumontita hidratada."),
    ("BRE", "Brewsterita", "poro pequeño", "(Ba0.5,Sr1.5)[(AlO2)4(SiO2)12]·10H2O",
     "2.0-3.0", "2.3×5.0 + 2.8×4.1 Å (2 canales 8-MR)", "8-MR", "2D", 2.5, 4.7,
     "Zeolita natural rara de poro pequeño (solo 8-MR), con dos sistemas de canales que se "
     "cruzan. Catión extra-red dominante Sr/Ba, de interés para intercambio catiónico de "
     "alcalinotérreos pesados."),
    ("HAR", "Harmotoma", "poro pequeño", "Ba2[(AlO2)4(SiO2)12]·12H2O (extremo Ba idealizado)",
     "1.0-2.0", "3.8×3.8 + 3.0×4.3 + 3.2×3.3 Å (3 canales 8-MR)", "8-MR", "3D", 1.5, 4.1,
     "Zeolita natural del grupo phillipsita, distinguida por Ba2+ como catión dominante. La IZA "
     "no le asigna código de framework propio — comparte oficialmente el código PHI con la "
     "phillipsita; se usa 'HAR' por convención de este dataset."),
    ("STI", "Estilbita", "poro mediano", "(Na4,Ca8)[(AlO2)20(SiO2)52]·56H2O",
     "2.0-3.0", "4.7×5.0 Å (10-MR) + 2.7×5.6 Å (8-MR)", "10-MR/8-MR", "2D", 2.0, 6.6,
     "Una de las zeolitas naturales más comunes, típica de amígdalas en rocas volcánicas "
     "basálticas. Deshidratación/rehidratación reversible sin colapso estructural. Serie con "
     "estelerita y barrerita según el catión dominante."),
    ("MEL", "ZSM-11 (MEL)", "poro mediano", "Mx/n[(AlO2)x(SiO2)96-x]·wH2O (alta sílice, tipo pentasil)",
     "8.0-20.0", "5.3×5.4 Å (ventana 10-MR)", "10-MR", "2D", 14.0, 5.3,
     "Emparentada con ZSM-5 (MFI), con la que suele intercrecer. A diferencia del canal "
     "sinusoidal de MFI, MEL tiene dos sistemas de canales rectos de 10-MR que se intersectan. "
     "Catálisis ácida y adsorbente hidrófobo (silicalita-2)."),
    ("MTT", "ZSM-23 (MTT)", "poro mediano", "Mx/n[(AlO2)x(SiO2)y]·wH2O (alta sílice; SSZ-32)",
     "10.0-20.0", "4.5×5.2 Å (ventana 10-MR)", "10-MR", "1D", 16.0, 5.1,
     "Canal 1D estrecho de 10-MR elíptico, alta selectividad de forma. Uso industrial en "
     "desparafinado catalítico e isomerización de n-parafinas de cadena larga en lubricantes."),
    ("TON", "ZSM-22 / Theta-1 (TON)", "poro mediano",
     "Mx/n[(AlO2)x(SiO2)y]·wH2O (alta sílice; isoestructural con Theta-1, NU-10)",
     "10.0-40.0", "4.6×5.7 Å (ventana 10-MR elíptica)", "10-MR", "1D", 20.0, 5.0,
     "Canal 1D elíptico de 10-MR, cadenas en zigzag de dobles anillos de 5. Fuertes limitaciones "
     "difusionales por su geometría estrecha no intersectada. Hidroisomerización de n-parafinas "
     "en desparafinado de lubricantes."),
    ("AFI", "AFI (AlPO4-5 / SAPO-5)", "poro grande",
     "AlPO4-5: Al12P12O48 (aluminofosfato neutro, sin Si); variante SAPO-5 con Si de baja carga",
     "~6.0-10.0", "7.3 Å (ventana 12-MR)", "12-MR", "1D", 8.0, 13.0,
     "Tamiz molecular de referencia con canal 1D de 12 anillos casi circular. Sistema modelo "
     "clásico para difusión en zeolitas de poro grande; SAPO-5 aporta acidez Brønsted útil en "
     "craqueo/isomerización."),
    ("LTL", "Zeolita L (LTL)", "poro grande", "K9[(AlO2)9(SiO2)27]·21H2O",
     "1.5-3.5", "7.1 Å (ventana 12-MR)", "12-MR", "1D", 1.3, 7.1,
     "Soporte clásico del catalizador Pt/KL para aromatización no ácida de n-parafinas; el canal "
     "1D de 12 anillos confina clústeres subnanométricos de Pt. También matriz huésped para "
     "colorantes fluorescentes."),
    ("MWW", "MCM-22 (MWW)", "poro mediano", "Nax[(AlO2)x(SiO2)y]·wH2O (Si/Al síntesis ~9-30)",
     "9.0-20.0", "4.0×5.5 Å (10-MR) + supercaja 12-MR (7.1×18.2 Å)", "10-MR/12-MR", "2D + cajas", 12.0, 7.2,
     "Combina canales sinusoidales 2D de 10 anillos con supercajas internas de 12 anillos "
     "accesibles solo por ventanas de 10-MR. Base de la familia MCM-22/ITQ-2/MCM-36; catálisis "
     "ácida industrial (alquilación de benceno)."),
    ("NU10", "NU-10 (framework TON)", "poro mediano", "Nax[AlxSi(24-x)O48]·yH2O (celda tipo TON, 24 T)",
     "~6.0-15.0", "4.6×5.7 Å (ventana 10-MR)", "10-MR", "1D", 10.0, 8.0,
     "Zeolita sintética de ICI, isoestructural con Theta-1/ZSM-22/KZ-2/ISI-1 (framework TON "
     "real). Hidroisomerización de n-parafinas, metilación selectiva de tolueno a para-xileno."),
    ("NU86", "NU-86 (sin código IZA asignado)", "poro mediano",
     "Composición Si,Al variable (posible sustitución Fe/Ga/B)",
     "~5.0-12.0", "4.8×5.8 (10-MR) + 5.5×6.2 (11-MR) + 5.7×5.7 Å (12-MR)", "12-MR/11-MR/10-MR", "3D", 8.0, 7.0,
     "Zeolita de alta sílice del IFP/ICI con sistema 3D único de canales entrelazados de "
     "10/11/12 anillos. Sin código de framework IZA de 3 letras oficial (patentes lo confirman). "
     "Hidroconversión de cargas petrolíferas."),
    ("ERI", "Erionita", "poro pequeño", "(Na2,K2,Ca)4.5[Al9Si27O72]·27H2O",
     "2.5-3.5", "3.6×5.1 Å (ventana 8-MR)", "8-MR", "3D", 2.5, 4.8,
     "Zeolita natural fibrosa, columnas de cajas cancrinita unidas por D6R. Tamiz molecular "
     "industrial para separación n-parafinas/isoparafinas. ADVERTENCIA: la erionita fibrosa "
     "natural es carcinógeno humano Grupo 1 (IARC)."),
    ("MCM41", "MCM-41", "sílice mesoporosa", "SiO2 amorfo mesoestructurado (hexagonal p6mm)",
     "~3.0-8.0", "~20-100 Å (mesoporo cilíndrico, no ventana cristalina)", "N/A", "1D (hexagonal)", 5.0, 100.0,
     "Sílice mesoporosa ordenada (Mobil, 1992), canales cilíndricos hexagonales sin orden atómico "
     "de largo alcance — NO es zeolita cristalina. Muy usada como soporte catalítico por su gran "
     "área superficial (~1000 m²/g)."),
    ("SBA15", "SBA-15", "sílice mesoporosa", "SiO2 amorfo mesoestructurado (hexagonal p6mm, pared gruesa)",
     "~4.0-9.0", "~50-300 Å (mesoporo cilíndrico + microporos de pared)", "N/A", "1D (hexagonal)", 6.0, 300.0,
     "Misma simetría hexagonal que MCM-41 pero paredes mucho más gruesas (3-6 nm), mayor "
     "estabilidad hidrotérmica. Sintetizada con copolímero tribloque P123. NO es cristalina."),
    ("FDU12", "FDU-12", "sílice mesoporosa", "SiO2 amorfo mesoestructurado (cúbico Fm-3m, tipo jaula)",
     "~5.0-12.0", "~99-260 Å (cavidades esféricas interconectadas)", "N/A", "3D (cúbico Fm-3m)", 8.0, 500.0,
     "Sílice mesoporosa tipo jaula en red cúbica Fm-3m, cavidades esféricas grandes "
     "interconectadas por ventanas de tamaño controlable. NO es cristalina. Útil para "
     "inmovilizar enzimas o nanopartículas grandes."),
    ("HMS", "HMS (sílice mesoporosa hexagonal)", "sílice mesoporosa",
     "SiO2 amorfo mesoestructurado (poros tipo wormhole)",
     "~1.5-5.0", "~29-58 Å (poro irregular, orden de corto alcance)", "N/A", "3D (tipo gusano)", 3.0, 50.0,
     "Sílice mesoporosa con poros tipo 'gusano' de orden solo de corto alcance, ruta de plantilla "
     "neutra con aminas (dodecilamina). Paredes más gruesas y síntesis más simple que la ruta "
     "iónica clásica (MCM-41)."),
    ("KIT6", "KIT-6", "sílice mesoporosa", "SiO2 amorfo mesoestructurado (cúbico Ia-3d, giroide bicontinuo)",
     "~4.5-10.0", "~56-113 Å (dos redes de canales bicontinuas)", "N/A", "3D (bicontinuo)", 7.0, 200.0,
     "Sílice mesoporosa cúbica bicontinua (giroide Ia-3d), dos redes de canales 3D interpenetradas "
     "conectadas por microporos de pared. NO es cristalina. Mejor accesibilidad difusional que "
     "fases hexagonales 1D (SBA-15/MCM-41)."),
]


def seed(db=None) -> int:
    """Inserta las familias si no existen ya (idempotente por `code`). Devuelve
    el número de filas insertadas. Acepta una sesión opcional (para tests)."""
    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    inserted = 0
    try:
        for (code, name, category, formula, si_al_ratio, pore_size, ring_size,
             channel_dim, si_al_mid, pore_max, description) in FAMILIES:
            existing = db.query(ZeoliteFamily).filter(ZeoliteFamily.code == code).first()
            if existing:
                logger.info(f"  ⏭  {code} ya existe, se omite")
                continue

            bands = _typical_bands(code, si_al_mid, pore_max)
            family = ZeoliteFamily(
                code=code, name=name, category=category, chemical_formula=formula,
                si_al_ratio=si_al_ratio, pore_size=pore_size, ring_size=ring_size,
                channel_dimensionality=channel_dim, typical_bands=bands,
                description=description,
            )
            db.add(family)
            inserted += 1
            logger.info(f"  ✓ {code} — {name} (bandas: {bands})")

        db.commit()
        return inserted
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    logger.info("🌱 Poblando catálogo de familias de zeolitas...")
    try:
        init_db()
        n = seed()
        logger.info(f"✅ {n} familias nuevas insertadas (de {len(FAMILIES)} definidas)")
    except Exception as e:
        logger.error(f"❌ Error poblando catálogo: {e}", exc_info=True)
        sys.exit(1)
