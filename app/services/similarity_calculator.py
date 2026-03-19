"""
Calculador de similitud espectral FTIR
Implementa algoritmos de comparación: coseno, Pearson, euclidea
"""

import json
import math
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class SimilarityCalculator:
    """Calculador de similitud entre espectros FTIR"""

    def __init__(self):
        self.tolerance = 4  # Tolerancia en cm⁻¹

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
        Retorna: (wavenumbers, absorbance)
        """
        try:
            if isinstance(wavenumber_data, str):
                data = json.loads(wavenumber_data)
            else:
                data = wavenumber_data

            wavenumbers = data.get("wavenumbers", [])
            absorbance = data.get("absorbance", [])

            return wavenumbers, absorbance
        except Exception as e:
            logger.error(f"Error parseando wavenumber_data: {e}")
            return [], []

    @staticmethod
    def filter_by_range(wavenumbers: List[float], absorbance: List[float],
                       range_min: int, range_max: int) -> tuple:
        """Filtrar datos por rango de wavenumber"""
        if not wavenumbers or not absorbance:
            return [], []

        indices = [i for i, w in enumerate(wavenumbers) if range_min <= w <= range_max]

        if not indices:
            return [], []

        filtered_wn = [wavenumbers[i] for i in indices]
        filtered_abs = [absorbance[i] for i in indices]

        return filtered_wn, filtered_abs

    @staticmethod
    def align_spectra(wn1: List[float], abs1: List[float],
                     wn2: List[float], abs2: List[float],
                     tolerance: float) -> tuple:
        """
        Alinear dos espectros usando nearest-neighbor con tolerancia
        Retorna: (aligned_abs1, aligned_abs2)
        """
        aligned1 = []
        aligned2 = []

        for target_wn, target_abs in zip(wn1, abs1):
            best_idx = -1
            best_dist = float('inf')

            for j, ref_wn in enumerate(wn2):
                dist = abs(ref_wn - target_wn)
                if dist < best_dist and dist <= tolerance:
                    best_dist = dist
                    best_idx = j

            if best_idx >= 0:
                aligned1.append(target_abs)
                aligned2.append(abs2[best_idx])

        return aligned1, aligned2

    @staticmethod
    def detect_peaks(wavenumbers: List[float], absorbance: List[float],
                    threshold: float = 0.05) -> List[float]:
        """
        Detectar picos (máximos locales) en un espectro
        Retorna lista de wavenumbers de los picos
        """
        if len(absorbance) < 3:
            return []

        peaks = []

        for i in range(1, len(absorbance) - 1):
            if (absorbance[i] > absorbance[i-1] and
                absorbance[i] > absorbance[i+1] and
                absorbance[i] > threshold):
                peaks.append(wavenumbers[i])

        return peaks

    @staticmethod
    def match_peaks(peaks1: List[float], peaks2: List[float],
                   tolerance: float) -> Dict:
        """
        Emparejar picos entre dos espectros con tolerancia
        Retorna dict con: matched, unmatched, total
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
            "total": len(peaks1)
        }

    # ====================================================
    # MÉTODO PRINCIPAL: CALCULAR SIMILITUD
    # ====================================================

    def calculate_similarity(self, spectrum1, spectrum2, method: str = "cosine",
                            tolerance: float = 4, range_min: int = 400,
                            range_max: int = 4000) -> Optional[Dict]:
        """
        Calcular similitud entre dos espectros

        Args:
            spectrum1: Objeto Spectrum (query)
            spectrum2: Objeto Spectrum (referencia)
            method: "cosine", "pearson", o "euclidean"
            tolerance: Tolerancia en cm⁻¹ para alineación
            range_min: Rango mínimo de wavenumber
            range_max: Rango máximo de wavenumber

        Returns:
            Dict con similitud global, window_scores, matched_peaks, etc.
        """
        try:
            # Parsear datos
            wn1, abs1 = self.parse_wavenumber_data(spectrum1.wavenumber_data)
            wn2, abs2 = self.parse_wavenumber_data(spectrum2.wavenumber_data)

            if not wn1 or not abs1 or not wn2 or not abs2:
                logger.warning(f"Espectro sin datos: {spectrum1.id} o {spectrum2.id}")
                return None

            # Filtrar por rango
            wn1, abs1 = self.filter_by_range(wn1, abs1, range_min, range_max)
            wn2, abs2 = self.filter_by_range(wn2, abs2, range_min, range_max)

            if not wn1 or not wn2:
                logger.warning(f"Datos vacíos después de filtrar rango")
                return None

            # Alinear espectros
            aligned1, aligned2 = self.align_spectra(wn1, abs1, wn2, abs2, tolerance)

            if not aligned1 or not aligned2:
                logger.warning(f"No se pudieron alinear espectros")
                return None

            # Calcular similitud según método
            if method == "cosine":
                score = self.cosine_similarity(aligned1, aligned2)
            elif method == "pearson":
                score = self.pearson_correlation(aligned1, aligned2)
            elif method == "euclidean":
                score = self.euclidean_similarity(aligned1, aligned2)
            else:
                score = self.cosine_similarity(aligned1, aligned2)

            # Detectar picos
            peaks1 = self.detect_peaks(wn1, abs1)
            peaks2 = self.detect_peaks(wn2, abs2)
            peak_match = self.match_peaks(peaks1, peaks2, tolerance)

            return {
                "global_score": max(0, min(1, score)),  # Asegurar rango 0-1
                "window_scores": [],
                "matching_peaks": len(peak_match["matched"]),
                "total_peaks": peak_match["total"],
                "matched_peaks": peak_match["matched"],
                "unmatched_peaks": peak_match["unmatched"]
            }

        except Exception as e:
            logger.error(f"Error calculando similitud: {e}")
            return None