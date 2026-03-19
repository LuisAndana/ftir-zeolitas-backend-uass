"""
Calculador de similitud espectral FTIR - VERSIÓN MEJORADA 2024
Implementa algoritmos de comparación: coseno, Pearson, euclidea
Con logging detallado y validación robusta de datos
"""

import json
import math
import numpy as np
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class SimilarityCalculator:
    """Calculador de similitud entre espectros FTIR"""

    def __init__(self):
        self.tolerance = 4  # Tolerancia en cm⁻¹
        self.peak_threshold = 0.01  # Umbral para detección de picos (REDUCIDO)

    # ====================================================
    # ALGORITMOS DE SIMILITUD
    # ====================================================

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """
        Similitud coseno: rango 0-1
        Mide el ángulo entre dos vectores
        """
        if len(a) == 0 or len(b) == 0:
            return 0.0

        # Producto escalar
        dot_product = sum(x * y for x, y in zip(a, b))

        # Normas
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    @staticmethod
    def pearson_correlation(a: List[float], b: List[float]) -> float:
        """
        Correlación de Pearson: normalizado a 0-1
        Mide la relación lineal entre dos series
        """
        if len(a) < 2 or len(b) < 2 or len(a) != len(b):
            return 0.0

        n = len(a)
        mean_a = sum(a) / n
        mean_b = sum(b) / n

        # Covarianza
        numerator = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))

        # Desviaciones estándar
        denom_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
        denom_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))

        if denom_a == 0 or denom_b == 0:
            return 0.0

        # Correlación (-1 a 1) normalizada a (0 a 1)
        correlation = numerator / (denom_a * denom_b)
        return (correlation + 1) / 2

    @staticmethod
    def euclidean_similarity(a: List[float], b: List[float]) -> float:
        """
        Distancia euclidiana convertida a similitud: 0-1
        Mide la distancia directa entre dos puntos
        """
        if len(a) == 0 or len(b) == 0:
            return 0.0

        sum_sq_diff = sum((x - y) ** 2 for x, y in zip(a, b))
        distance = math.sqrt(sum_sq_diff / len(a))

        return 1 / (1 + distance)

    # ====================================================
    # PROCESAMIENTO DE ESPECTROS
    # ====================================================

    @staticmethod
    def parse_wavenumber_data(wavenumber_data) -> tuple:
        """
        Parsear datos de wavenumber desde JSON o dict
        ✅ MEJORADO: Soporta ambos formatos (wavenumbers + intensities)
        Retorna: (wavenumbers, absorbance)
        """
        try:
            if isinstance(wavenumber_data, str):
                data = json.loads(wavenumber_data)
            else:
                data = wavenumber_data

            # ✅ Soportar ambos formatos
            wavenumbers = data.get("wavenumbers", [])
            absorbance = data.get("absorbance", [])

            # Si no hay wavenumbers, intentar con intensities (formato dataset)
            if not wavenumbers and "intensities" in data:
                intensities = data.get("intensities", [])
                if intensities:
                    logger.debug("⚠️ Usando formato 'intensities' en lugar de 'wavenumbers'")
                    return list(range(len(intensities))), intensities

            if not wavenumbers or not absorbance:
                logger.warning(f"⚠️ Datos incompletos: wavenumbers={len(wavenumbers)}, absorbance={len(absorbance)}")
                return [], []

            return wavenumbers, absorbance
        except Exception as e:
            logger.error(f"❌ Error parseando wavenumber_data: {e}")
            return [], []

    @staticmethod
    def filter_by_range(wavenumbers: List[float], absorbance: List[float],
                       range_min: int, range_max: int) -> tuple:
        """Filtrar datos por rango de wavenumber"""
        if not wavenumbers or not absorbance:
            return [], []

        indices = [i for i, w in enumerate(wavenumbers) if range_min <= w <= range_max]

        if not indices:
            logger.warning(f"⚠️ Sin datos en rango {range_min}-{range_max}")
            return [], []

        filtered_wn = [wavenumbers[i] for i in indices]
        filtered_abs = [absorbance[i] for i in indices]

        return filtered_wn, filtered_abs

    @staticmethod
    def align_spectra(wn1: List[float], abs1: List[float],
                     wn2: List[float], abs2: List[float],
                     tolerance: float) -> tuple:
        """
        ✅ MEJORADO: Alineación más robusta usando numpy
        Retorna: (aligned_abs1, aligned_abs2)
        """
        if not wn1 or not abs1 or not wn2 or not abs2:
            return [], []

        try:
            # Convertir a numpy para eficiencia
            wn1_arr = np.array(wn1, dtype=float)
            abs1_arr = np.array(abs1, dtype=float)
            wn2_arr = np.array(wn2, dtype=float)
            abs2_arr = np.array(abs2, dtype=float)

            aligned1 = []
            aligned2 = []

            # Usar el espectro más denso como referencia
            if len(wn1) >= len(wn2):
                ref_wn, ref_abs = wn1_arr, abs1_arr
                query_wn, query_abs = wn2_arr, abs2_arr
                swap = False
            else:
                ref_wn, ref_abs = wn2_arr, abs2_arr
                query_wn, query_abs = wn1_arr, abs1_arr
                swap = True

            # Alineación por nearest neighbor
            for i, target_wn in enumerate(ref_wn):
                distances = np.abs(query_wn - target_wn)
                min_idx = np.argmin(distances)
                min_dist = distances[min_idx]

                # Solo alinear si está dentro de tolerancia
                if min_dist <= tolerance:
                    if swap:
                        aligned1.append(float(query_abs[min_idx]))
                        aligned2.append(float(ref_abs[i]))
                    else:
                        aligned1.append(float(ref_abs[i]))
                        aligned2.append(float(query_abs[min_idx]))

            logger.debug(f"🔗 Puntos alineados: {len(aligned1)}")
            return aligned1, aligned2

        except Exception as e:
            logger.error(f"❌ Error en alineación: {e}")
            return [], []

    @staticmethod
    def detect_peaks(wavenumbers: List[float], absorbance: List[float],
                    threshold: float = 0.01) -> List[float]:
        """
        ✅ MEJORADO: Detección con normalización automática
        Threshold REDUCIDO de 0.05 a 0.01 (configurable)
        """
        if len(absorbance) < 3:
            logger.debug(f"⚠️ Espectro muy corto: {len(absorbance)} puntos")
            return []

        try:
            # ✅ Normalizar absorbance a 0-1
            abs_arr = np.array(absorbance, dtype=float)
            max_abs = np.max(abs_arr)
            min_abs = np.min(abs_arr)

            if max_abs == min_abs:
                logger.debug("⚠️ Todos los valores de absorbance son iguales")
                return []

            # Normalizar a rango 0-1
            norm_abs = (abs_arr - min_abs) / (max_abs - min_abs)

            peaks = []

            for i in range(1, len(norm_abs) - 1):
                # Detección de máximos locales
                if (norm_abs[i] > norm_abs[i-1] and
                    norm_abs[i] > norm_abs[i+1] and
                    norm_abs[i] > threshold):
                    peaks.append(wavenumbers[i])

            logger.debug(f"🎯 Picos detectados: {len(peaks)}")
            return peaks

        except Exception as e:
            logger.error(f"❌ Error detectando picos: {e}")
            return []

    @staticmethod
    def match_peaks(peaks1: List[float], peaks2: List[float],
                   tolerance: float) -> Dict:
        """
        Emparejar picos entre dos espectros con tolerancia
        """
        matched = []
        unmatched = []

        for p1 in peaks1:
            found = False
            for p2 in peaks2:
                if abs(p1 - p2) <= tolerance:
                    matched.append(p1)
                    found = True
                    break

            if not found:
                unmatched.append(p1)

        return {
            "matched": matched,
            "unmatched": unmatched,
            "total": len(peaks1),
            "matched_count": len(matched)
        }

    # ====================================================
    # MÉTODO PRINCIPAL: CALCULAR SIMILITUD
    # ====================================================

    def calculate_similarity(self, spectrum1, spectrum2, method: str = "cosine",
                            tolerance: float = 4, range_min: int = 400,
                            range_max: int = 4000, peak_threshold: float = None) -> Optional[Dict]:
        """
        ✅ VERSIÓN MEJORADA CON LOGGING DETALLADO EN 6 FASES
        Calcula similitud entre dos espectros
        """
        if peak_threshold is None:
            peak_threshold = self.peak_threshold

        try:
            logger.info("="*70)
            logger.info(f"📊 INICIANDO CÁLCULO DE SIMILITUD")
            logger.info(f"   Spectrum1: {spectrum1.id}")
            logger.info(f"   Spectrum2: {spectrum2.id}")
            logger.info(f"   Método: {method}, Tolerancia: {tolerance}")
            logger.info("="*70)

            # 1️⃣ PARSEAR DATOS
            wn1, abs1 = self.parse_wavenumber_data(spectrum1.wavenumber_data)
            wn2, abs2 = self.parse_wavenumber_data(spectrum2.wavenumber_data)

            logger.info(f"1️⃣ PARSEO:")
            logger.info(f"   Spectrum1: {len(wn1)} wavenumbers, {len(abs1)} absorbance")
            logger.info(f"   Spectrum2: {len(wn2)} wavenumbers, {len(abs2)} absorbance")

            if not wn1 or not abs1 or not wn2 or not abs2:
                logger.error(f"❌ FALLÓ: Datos incompletos en parseo")
                return None

            # 2️⃣ FILTRAR POR RANGO
            wn1, abs1 = self.filter_by_range(wn1, abs1, range_min, range_max)
            wn2, abs2 = self.filter_by_range(wn2, abs2, range_min, range_max)

            logger.info(f"2️⃣ FILTRADO (rango {range_min}-{range_max}):")
            logger.info(f"   Spectrum1: {len(wn1)} puntos")
            logger.info(f"   Spectrum2: {len(wn2)} puntos")

            if not wn1 or not wn2:
                logger.error(f"❌ FALLÓ: Datos vacíos después de filtrar")
                return None

            # 3️⃣ ALINEAR ESPECTROS
            aligned1, aligned2 = self.align_spectra(wn1, abs1, wn2, abs2, tolerance)

            logger.info(f"3️⃣ ALINEAMIENTO (tolerancia {tolerance} cm⁻¹):")
            logger.info(f"   Puntos alineados: {len(aligned1)}")

            if not aligned1 or not aligned2:
                logger.error(f"❌ FALLÓ: No se alinearon espectros")
                return None

            # 4️⃣ CALCULAR SIMILITUD
            if method == "cosine":
                score = self.cosine_similarity(aligned1, aligned2)
            elif method == "pearson":
                score = self.pearson_correlation(aligned1, aligned2)
            elif method == "euclidean":
                score = self.euclidean_similarity(aligned1, aligned2)
            else:
                score = self.cosine_similarity(aligned1, aligned2)

            logger.info(f"4️⃣ CÁLCULO DE SIMILITUD:")
            logger.info(f"   Score ({method}): {score:.4f} ({score*100:.2f}%)")

            # 5️⃣ DETECTAR PICOS
            peaks1 = self.detect_peaks(wn1, abs1, threshold=peak_threshold)
            peaks2 = self.detect_peaks(wn2, abs2, threshold=peak_threshold)

            logger.info(f"5️⃣ DETECCIÓN DE PICOS (threshold {peak_threshold}):")
            logger.info(f"   Spectrum1 picos: {len(peaks1)}")
            logger.info(f"   Spectrum2 picos: {len(peaks2)}")

            # 6️⃣ EMPAREJAR PICOS
            peak_match = self.match_peaks(peaks1, peaks2, tolerance)

            logger.info(f"6️⃣ EMPAREJAMIENTO DE PICOS:")
            logger.info(f"   Coincidencias: {peak_match['matched_count']}/{len(peaks1)}")
            logger.info("="*70)
            logger.info(f"✅ CÁLCULO COMPLETADO EXITOSAMENTE")
            logger.info("="*70)

            return {
                "global_score": max(0, min(1, score)),
                "window_scores": [],
                "matching_peaks": len(peak_match["matched"]),
                "total_peaks": peak_match["total"],
                "matched_peaks": peak_match["matched"],
                "unmatched_peaks": peak_match["unmatched"]
            }

        except Exception as e:
            logger.error(f"❌ EXCEPCIÓN: {str(e)}", exc_info=True)
            return None