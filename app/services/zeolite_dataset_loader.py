"""
Servicio para cargar dataset completo de zeolitas FTIR
Genera datos realistas de 3000+ muestras con 9000+ espectros
"""

import logging
import json
import mysql.connector
from mysql.connector import Error
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import random

logger = logging.getLogger(__name__)

class ZeoliteDatasetLoader:
    """Cargador de dataset de zeolitas FTIR con datos realistas"""

    # 45+ tipos de zeolitas
    ZEOLITE_TYPES = [
        ("4A (LTA)", "LTA", 1.0, 3.0, 4.0, "Zeolita de poro pequeño, excelente para deshidratación"),
        ("5A (LTA)", "LTA", 1.0, 5.0, 5.0, "Zeolita de poro mediano, usada en separaciones moleculares"),
        ("13X (FAU)", "FAU", 1.23, 7.4, 7.4, "Zeolita de poro grande, alta capacidad de adsorción"),
        ("Y (FAU)", "FAU", 1.56, 7.4, 7.4, "Zeolita Y de alta sílice, usada en refinería"),
        ("ZSM-5 (MFI)", "MFI", 15.0, 5.1, 5.6, "Zeolita de poro mediano, importante en síntesis química"),
        ("Mordenita", "MOR", 5.0, 6.7, 7.0, "Zeolita con poros unidimensionales"),
        ("Clinoptilolita", "HEU", 4.0, 3.6, 7.6, "Zeolita natural, uso en tratamiento de aguas"),
        ("Sodalita", "SOD", 2.0, 2.4, 2.4, "Zeolita de poro muy pequeño"),
        ("Beta", "BEA", 12.5, 5.5, 7.6, "Zeolita de poro grande, síntesis orgánica"),
        ("Ferrierita", "FER", 8.5, 4.2, 10.0, "Zeolita con poros elípticos"),
        ("Chabazita", "CHA", 1.5, 3.8, 3.8, "Zeolita de poro pequeño, catálisis"),
        ("Erionita", "ERI", 2.5, 4.8, 4.8, "Zeolita fibrosa natural"),
        ("Laumontita", "LAU", 1.8, 2.6, 4.8, "Zeolita con poros grandes"),
        ("Natrolita", "NAT", 1.0, 2.6, 2.6, "Zeolita fibrosa de poro pequeño"),
        ("Heulandita", "HEU", 3.0, 4.4, 7.2, "Zeolita laminada, uso industrial"),
        ("Stilbita", "STI", 2.0, 2.8, 6.6, "Zeolita en forma de cristales"),
        ("Harmotoma", "HAR", 1.5, 4.1, 4.1, "Zeolita de estructura compleja"),
        ("Brewsterita", "BRE", 2.5, 3.0, 4.7, "Zeolita monoclínica"),
        ("Leonhardita", "LEO", 2.0, 4.1, 4.1, "Zeolita hidratada"),
        ("Gonnardita", "GON", 1.8, 3.5, 3.5, "Zeolita de estructura lineal"),
        ("ZSM-11", "MEL", 14.0, 5.3, 5.3, "Zeolita similar a ZSM-5"),
        ("ZSM-22", "TON", 20.0, 4.7, 5.0, "Zeolita de poro pequeño"),
        ("ZSM-23", "MTT", 16.0, 4.2, 5.1, "Zeolita de estructura compleja"),
        ("MCM-22", "MWW", 12.0, 4.0, 7.2, "Zeolita mesoporosa organizada"),
        ("MCM-41", "MCM41", 5.0, 10.0, 100.0, "Zeolita mesoporosa de poro grande"),
        ("SBA-15", "SBA15", 6.0, 15.0, 300.0, "Zeolita mesoporosa hexagonal"),
        ("FDU-12", "FDU12", 8.0, 20.0, 500.0, "Zeolita mesoporosa cúbica"),
        ("HMS", "HMS", 3.0, 8.0, 50.0, "Zeolita hexagonal mesoporosa"),
        ("KIT-6", "KIT6", 7.0, 12.0, 200.0, "Zeolita mesoporosa cúbica"),
        ("Zeolita L", "LTL", 1.3, 7.1, 7.1, "Zeolita hexagonal de poro grande"),
        ("Zeolita T", "TON", 2.0, 4.6, 6.0, "Zeolita de estructura TON"),
        ("Zeolita W", "EAB", 1.5, 3.5, 3.5, "Zeolita de estructura EAB"),
        ("Zeolita X", "FAU", 1.0, 7.4, 7.4, "Zeolita X baja en sílice"),
        ("Zeolita P", "GIS", 1.0, 2.8, 4.7, "Zeolita policatiónica"),
        ("Erionita sintética", "ERI", 3.0, 4.8, 4.8, "Erionita preparada sinteticamente"),
        ("β-Zeolita", "BEA", 12.0, 5.5, 7.6, "Beta zeolita de alta pureza"),
        ("NU-10", "NU10", 10.0, 6.0, 8.0, "Zeolita diseñada estructuralmente"),
        ("NU-86", "NU86", 8.0, 5.0, 7.0, "Zeolita sintética de estructura novel"),
        ("MFI (Sintética)", "MFI", 20.0, 5.1, 5.6, "MFI sintética de alta pureza"),
        ("FAU (Sintética)", "FAU", 1.5, 7.4, 7.4, "FAU sintética tipo X/Y"),
        ("CHA (Sintética)", "CHA", 1.3, 3.8, 3.8, "CHA sintética para catálisis"),
        ("AFI (Sintética)", "AFI", 8.0, 13.0, 13.0, "AFI con poros unidimensionales"),
        ("AEI (Sintética)", "AEI", 2.5, 3.8, 3.8, "AEI para síntesis selectiva"),
        ("ATN (Sintética)", "ATN", 3.0, 4.5, 4.5, "ATN estructura laminada"),
    ]

    PREPARATION_METHODS = [
        "Calcinación directa",
        "Intercambio iónico + calcinación",
        "Síntesis hidrotermal",
        "Síntesis de Gel",
        "Intercambio con ácido",
        "Impregnación",
        "Reactivación térmica",
        "Intercambio con base",
        "Síntesis sol-gel",
        "Deshidratación in-situ",
    ]

    EQUIPMENT_LIST = [
        "Thermo Nicolet iS5",
        "Bruker ALPHA",
        "PerkinElmer Spectrum Two",
        "Jasco FT/IR-4200",
        "Shimadzu IRPrestige-21",
        "Agilent Cary 630",
        "Thermo Fisher Nicolet iS50",
        "Bruker Vertex 70",
    ]

    SOURCES = [
        "Síntesis local laboratorio",
        "Zeolita Peruana S.A.",
        "Proveedores internacionales",
        "Zeolitas naturales - Tingo María",
        "Síntesis en laboratorio UASS",
        "Minas del Perú",
        "Importación industrial",
        "Producción local",
    ]

    # Picos característicos por tipo de zeolita (posiciones FTIR realistas)
    CHARACTERISTIC_PEAKS = {
        "Si-O stretching (asimétrico)": (1200, 0.70, "Vibración de red Si-O"),
        "Si-O stretching (simétrico)": (1000, 0.98, "Pico principal Si-O"),
        "Si-O bending (externo)": (800, 0.65, "Flexión externa"),
        "Framework vibration": (600, 0.45, "Vibración de red general"),
        "Si-O bending (interno)": (450, 0.40, "Flexión interna"),
        "O-H stretching": (3600, 0.95, "Grupos hidroxilo"),
        "H2O bending": (1640, 0.80, "Agua adsorbida"),
        "C-H stretching": (3000, 0.85, "Contaminación orgánica"),
    }

    ANALYSIS_PARAMETERS = [
        ("Surface Area", "BET_area", (50, 1000), "m²/g"),
        ("Pore Volume", "micropore_volume", (0.05, 0.8), "cm³/g"),
        ("Total Acidity", "total_acidity", (0.1, 10.0), "mmol/g"),
        ("Water Content", "moisture_content", (0.01, 15.0), "%"),
        ("Crystallinity", "crystallinity_index", (60, 99.5), "%"),
        ("Si/Al Ratio", "si_al_ratio", (1.0, 100.0), ""),
        ("Density", "bulk_density", (0.6, 1.3), "g/cm³"),
        ("Porosity", "total_porosity", (30, 85), "%"),
        ("Mechanical Strength", "crushing_strength", (10, 500), "N"),
        ("Selectivity", "product_selectivity", (40, 99.9), "%"),
    ]

    def __init__(self, host: str, user: str, password: str, database: str):
        """Inicializar conexión"""
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self.cursor = None
        self.start_time = None

    def connect(self):
        """Conectar a la base de datos"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database
            )
            self.cursor = self.connection.cursor()
            logger.info("✓ Conexión exitosa a base de datos")
            return True
        except Error as e:
            logger.error(f"✗ Error de conexión: {e}")
            return False

    def disconnect(self):
        """Cerrar conexión"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            logger.info("✓ Conexión cerrada")

    def clear_all_data(self):
        """Limpiar todos los datos (cuidado!)"""
        try:
            logger.info("⚠️  Limpiando todos los datos...")
            queries = [
                "DELETE FROM ftir_analysis",
                "DELETE FROM ftir_peaks",
                "DELETE FROM ftir_spectra",
                "DELETE FROM zeolite_samples",
                "DELETE FROM zeolite_types",
            ]
            for query in queries:
                self.cursor.execute(query)
            self.connection.commit()
            logger.info("✓ Datos limpiados exitosamente")
            return True
        except Error as e:
            logger.error(f"✗ Error limpiando datos: {e}")
            return False

    def create_tables(self):
        """Crear tablas necesarias"""
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS zeolite_types (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    structure_type VARCHAR(50),
                    si_al_ratio DECIMAL(5, 2),
                    pore_size_min DECIMAL(4, 2),
                    pore_size_max DECIMAL(4, 2),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS zeolite_samples (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    zeolite_type_id INT NOT NULL,
                    sample_code VARCHAR(50) UNIQUE NOT NULL,
                    source VARCHAR(100),
                    preparation_method VARCHAR(100),
                    activation_temperature INT,
                    activation_time INT,
                    purity_percent DECIMAL(5, 2),
                    batch_date DATE,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (zeolite_type_id) REFERENCES zeolite_types(id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ftir_spectra (
                                                            id INT PRIMARY KEY AUTO_INCREMENT,
                                                            sample_id INT NOT NULL,
                                                            wavenumber_range_start DECIMAL(6,2),
                    wavenumber_range_end DECIMAL(6, 2),
                    measurement_date DATETIME,
                    equipment VARCHAR(100),
                    resolution INT,
                    accumulations INT,
                    spectrum_data LONGTEXT,
                    baseline_corrected BOOLEAN DEFAULT 0,
                    normalized BOOLEAN DEFAULT 0,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sample_id) REFERENCES zeolite_samples(id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ftir_peaks (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    spectrum_id INT NOT NULL,
                    wavenumber DECIMAL(6, 2),
                    intensity DECIMAL(6, 4),
                    width DECIMAL(5, 2),
                    assignment VARCHAR(100),
                    confidence_percent INT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (spectrum_id) REFERENCES ftir_spectra(id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ftir_analysis (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    spectrum_id INT NOT NULL,
                    analysis_type VARCHAR(50),
                    parameter_name VARCHAR(100),
                    parameter_value DECIMAL(10, 4),
                    unit VARCHAR(50),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (spectrum_id) REFERENCES ftir_spectra(id)
                )
            """)

            self.connection.commit()
            logger.info("✓ Tablas creadas exitosamente")
            return True

        except Error as e:
            logger.error(f"✗ Error creando tablas: {e}")
            return False

    def insert_zeolite_types(self):
        """Insertar tipos de zeolitas"""
        try:
            logger.info(f"Insertando {len(self.ZEOLITE_TYPES)} tipos de zeolitas...")

            for name, structure, ratio, pore_min, pore_max, desc in self.ZEOLITE_TYPES:
                try:
                    self.cursor.execute("""
                        INSERT IGNORE INTO zeolite_types 
                        (name, structure_type, si_al_ratio, pore_size_min, pore_size_max, description)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (name, structure, ratio, pore_min, pore_max, desc))
                except Error:
                    pass

            self.connection.commit()
            logger.info(f"✓ Insertados {len(self.ZEOLITE_TYPES)} tipos de zeolitas")
            return True

        except Error as e:
            logger.error(f"✗ Error insertando tipos: {e}")
            return False

    def generate_spectrum_data(self, start_wn: int = 4000, end_wn: int = 400,
                               points: int = 1200) -> str:
        """Generar datos realistas de espectro FTIR"""
        wavenumbers = np.linspace(start_wn, end_wn, points)
        spectrum = np.ones_like(wavenumbers) + np.random.normal(0, 0.002, len(wavenumbers))

        # Añadir picos característicos
        for peak_name, (wn, intensity, _) in self.CHARACTERISTIC_PEAKS.items():
            idx = np.argmin(np.abs(wavenumbers - wn))
            width = np.random.randint(30, 80)
            variation = np.random.uniform(0.8, 1.1)
            peak = intensity * variation * np.exp(-((wavenumbers - wn)**2) / (2 * width**2))
            spectrum += peak

        # Normalizar
        spectrum = spectrum / np.max(spectrum)

        data = {
            "wavenumbers": wavenumbers.tolist(),
            "intensities": spectrum.tolist(),
            "start": int(start_wn),
            "end": int(end_wn),
            "points": int(points),
            "unit": "cm-1"
        }

        return json.dumps(data)

    def generate_samples(self, num_samples: int = 3000):
        """Generar muestras"""
        try:
            self.cursor.execute("SELECT id, name FROM zeolite_types")
            zeolite_types = self.cursor.fetchall()

            logger.info(f"Generando {num_samples} muestras...")

            for i in range(num_samples):
                zeolite_type = zeolite_types[i % len(zeolite_types)]
                sample_code = f"ZEO-{zeolite_type[1][:3].upper()}-{i+1:05d}"

                self.cursor.execute("""
                    INSERT INTO zeolite_samples
                    (zeolite_type_id, sample_code, source, preparation_method, 
                     activation_temperature, activation_time, purity_percent, batch_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    zeolite_type[0],
                    sample_code,
                    random.choice(self.SOURCES),
                    random.choice(self.PREPARATION_METHODS),
                    random.randint(200, 600),
                    random.randint(2, 24),
                    round(random.uniform(85, 99.9), 2),
                    datetime.now().date() - timedelta(days=random.randint(0, 730))
                ))

                if (i + 1) % 500 == 0:
                    self.connection.commit()
                    logger.info(f"  {i+1}/{num_samples} muestras procesadas...")

            self.connection.commit()
            logger.info(f"✓ {num_samples} muestras insertadas")
            return True

        except Error as e:
            logger.error(f"✗ Error generando muestras: {e}")
            return False

    def generate_ftir_spectra(self, num_spectra: int = 9000):
        """Generar espectros FTIR"""
        try:
            self.cursor.execute("SELECT id FROM zeolite_samples")
            sample_ids = [row[0] for row in self.cursor.fetchall()]

            logger.info(f"Generando {num_spectra} espectros FTIR...")

            for i in range(min(num_spectra, len(sample_ids) * 3)):
                spectrum_data = self.generate_spectrum_data()

                self.cursor.execute("""
                    INSERT INTO ftir_spectra
                    (sample_id, wavenumber_range_start, wavenumber_range_end,
                     measurement_date, equipment, resolution, accumulations,
                     spectrum_data, baseline_corrected, normalized)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    sample_ids[i % len(sample_ids)],
                    4000, 400,
                    datetime.now() - timedelta(days=random.randint(0, 365)),
                    random.choice(self.EQUIPMENT_LIST),
                    random.choice([2, 4, 8, 16]),
                    random.choice([32, 64, 128, 256]),
                    spectrum_data,
                    random.choice([0, 1]),
                    random.choice([0, 1])
                ))

                if (i + 1) % 1000 == 0:
                    self.connection.commit()
                    logger.info(f"  {i+1}/{min(num_spectra, len(sample_ids) * 3)} espectros...")

            self.connection.commit()
            logger.info(f"✓ Espectros generados exitosamente")
            return True

        except Error as e:
            logger.error(f"✗ Error generando espectros: {e}")
            return False

    def generate_ftir_peaks(self):
        """Generar picos identificados"""
        try:
            self.cursor.execute("SELECT id FROM ftir_spectra LIMIT 9000")
            spectrum_ids = [row[0] for row in self.cursor.fetchall()]

            logger.info(f"Generando picos FTIR para {len(spectrum_ids)} espectros...")

            peaks_inserted = 0
            for spectrum_id in spectrum_ids:
                for peak_name, (wn, default_intensity, desc) in self.CHARACTERISTIC_PEAKS.items():
                    wn_var = wn + np.random.normal(0, 5)
                    intensity = default_intensity * np.random.uniform(0.6, 1.1)
                    width = np.random.uniform(20, 100)
                    confidence = np.random.randint(70, 99)

                    self.cursor.execute("""
                        INSERT INTO ftir_peaks
                        (spectrum_id, wavenumber, intensity, width, assignment, confidence_percent)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (spectrum_id, round(wn_var, 2), round(intensity, 4), round(width, 2), peak_name, confidence))

                    peaks_inserted += 1

                if peaks_inserted % 10000 == 0:
                    self.connection.commit()
                    logger.info(f"  {peaks_inserted} picos insertados...")

            self.connection.commit()
            logger.info(f"✓ {peaks_inserted} picos generados")
            return True

        except Error as e:
            logger.error(f"✗ Error generando picos: {e}")
            return False

    def generate_analysis(self):
        """Generar análisis"""
        try:
            self.cursor.execute("SELECT id FROM ftir_spectra LIMIT 9000")
            spectrum_ids = [row[0] for row in self.cursor.fetchall()]

            logger.info(f"Generando análisis para {len(spectrum_ids)} espectros...")

            analysis_inserted = 0
            for spectrum_id in spectrum_ids:
                for analysis_type, param_name, (min_val, max_val), unit in self.ANALYSIS_PARAMETERS:
                    value = round(np.random.uniform(min_val, max_val), 4)

                    self.cursor.execute("""
                        INSERT INTO ftir_analysis
                        (spectrum_id, analysis_type, parameter_name, parameter_value, unit)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (spectrum_id, analysis_type, param_name, value, unit))

                    analysis_inserted += 1

                if analysis_inserted % 15000 == 0:
                    self.connection.commit()
                    logger.info(f"  {analysis_inserted} análisis insertados...")

            self.connection.commit()
            logger.info(f"✓ {analysis_inserted} análisis generados")
            return True

        except Error as e:
            logger.error(f"✗ Error generando análisis: {e}")
            return False

    def get_summary(self) -> Dict:
        """Obtener resumen de datos"""
        try:
            queries = {
                "zeolite_types": "SELECT COUNT(*) FROM zeolite_types",
                "samples": "SELECT COUNT(*) FROM zeolite_samples",
                "spectra": "SELECT COUNT(*) FROM ftir_spectra",
                "peaks": "SELECT COUNT(*) FROM ftir_peaks",
                "analysis_records": "SELECT COUNT(*) FROM ftir_analysis",
            }

            summary = {}
            for key, query in queries.items():
                self.cursor.execute(query)
                summary[key] = self.cursor.fetchone()[0]

            summary["total_records"] = sum(summary.values())
            return summary

        except Error as e:
            logger.error(f"✗ Error obteniendo resumen: {e}")
            return {}

    def run(self, num_samples: int = 3000, num_spectra: int = 9000):
        """Ejecutar carga completa"""
        self.start_time = datetime.now()

        if not self.connect():
            return False

        try:
            logger.info("🚀 Iniciando carga del dataset...\n")

            self.create_tables()
            self.insert_zeolite_types()
            self.generate_samples(num_samples)
            self.generate_ftir_spectra(num_spectra)
            self.generate_ftir_peaks()
            self.generate_analysis()

            summary = self.get_summary()
            duration = (datetime.now() - self.start_time).total_seconds()

            logger.info("\n" + "="*60)
            logger.info("📊 DATASET CARGADO EXITOSAMENTE")
            logger.info("="*60)
            logger.info(f"✓ Tipos de zeolitas:     {summary.get('zeolite_types', 0)}")
            logger.info(f"✓ Muestras:             {summary.get('samples', 0)}")
            logger.info(f"✓ Espectros FTIR:       {summary.get('spectra', 0)}")
            logger.info(f"✓ Picos identificados:  {summary.get('peaks', 0)}")
            logger.info(f"✓ Análisis realizados:  {summary.get('analysis_records', 0)}")
            logger.info(f"✓ Total registros:      {summary.get('total_records', 0)}")
            logger.info(f"✓ Duración:             {duration:.2f} segundos")
            logger.info("="*60 + "\n")

            return True

        except Exception as e:
            logger.error(f"❌ Error en la carga: {e}")
            return False
        finally:
            self.disconnect()