"""
Calculador de similitud espectral FTIR - VERSIÓN MEJORADA 2024
Implementa algoritmos de comparación: coseno, Pearson, euclidea
Con logging detallado y validación robusta de datos
"""

import json
import math
import numpy as np
from typing import Optional, List, Dict
from scipy.interpolate import interp1d
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
        ✅ MEJORADO: Validaciones robustas
        """
        if len(a) < 2 or len(b) < 2 or len(a) != len(b):
            logger.warning(f"⚠️ Pearson: Datos insuficientes - len(a)={len(a)}, len(b)={len(b)}")
            return 0.0

        try:
            a_arr = np.array(a, dtype=float)
            b_arr = np.array(b, dtype=float)

            # Validar que no sean constantes
            if np.std(a_arr) == 0 or np.std(b_arr) == 0:
                logger.warning("⚠️ Pearson: Uno de los arrays tiene desviación estándar 0")
                return 0.0

            n = len(a_arr)
            mean_a = np.mean(a_arr)
            mean_b = np.mean(b_arr)

            # Covarianza
            numerator = np.sum((a_arr - mean_a) * (b_arr - mean_b))

            # Desviaciones estándar
            denom_a = np.sqrt(np.sum((a_arr - mean_a) ** 2))
            denom_b = np.sqrt(np.sum((b_arr - mean_b) ** 2))

            if denom_a == 0 or denom_b == 0:
                logger.warning("⚠️ Pearson: Denominador es 0")
                return 0.0

            # Correlación (-1 a 1) normalizada a (0 a 1)
            correlation = numerator / (denom_a * denom_b)
            result = (correlation + 1) / 2

            logger.debug(f"   Pearson raw: {correlation:.4f}, normalized: {result:.4f}")
            return float(result)

        except Exception as e:
            logger.error(f"❌ Error en pearson_correlation: {e}")
            return 0.0

    @staticmethod
    def euclidean_similarity(a: List[float], b: List[float]) -> float:
        """
        Distancia euclidiana convertida a similitud: 0-1
        Mide la distancia directa entre dos puntos
        ✅ MEJORADO: Mejor manejo de excepciones
        """
        if len(a) == 0 or len(b) == 0:
            return 0.0

        try:
            a_arr = np.array(a, dtype=float)
            b_arr = np.array(b, dtype=float)

            sum_sq_diff = np.sum((a_arr - b_arr) ** 2)
            distance = math.sqrt(sum_sq_diff / len(a_arr))

            result = 1 / (1 + distance)
            logger.debug(f"   Euclidean distance: {distance:.4f}, similarity: {result:.4f}")
            return float(result)
        except Exception as e:
            logger.error(f"❌ Error en euclidean_similarity: {e}")
            return 0.0

    # ====================================================
    # PROCESAMIENTO DE ESPECTROS
    # ====================================================

    @staticmethod
    def parse_wavenumber_data(wavenumber_data) -> tuple:
        """
        ✅ MEJORADO: Parsear datos con mejor validación
        Retorna: (wavenumbers, intensities)
        """
        try:
            # Asegúrate de que los datos son del tipo correcto
            if isinstance(wavenumber_data, str):
                wavenumber_data = json.loads(wavenumber_data)

            # Validar que sea un diccionario con 'wavenumbers' e 'intensities'
            if isinstance(wavenumber_data, dict):
                wn = wavenumber_data.get('wavenumbers', [])
                intensity = wavenumber_data.get('intensities', [])

                # Si no tiene 'intensities', intentar 'absorbance'
                if not intensity:
                    intensity = wavenumber_data.get('absorbance', [])
            else:
                logger.warning(f"⚠️ wavenumber_data no es dict: {type(wavenumber_data)}")
                return [], []

            # Convertir a float y eliminar valores None
            wn = [float(x) for x in wn if x is not None]
            intensity = [float(x) for x in intensity if x is not None]

            # Validar longitudes iguales
            if len(wn) != len(intensity):
                logger.error(f"❌ Longitudes diferentes: {len(wn)} wavenumbers vs {len(intensity)} intensities")
                return [], []

            # Validar que no estén vacíos
            if len(wn) == 0:
                logger.warning("⚠️ Datos parseados están vacíos")
                return [], []

            logger.debug(f"   ✅ Parseados {len(wn)} puntos correctamente")
            return wn, intensity

        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decodificando JSON: {e}")
            return [], []
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Error convirtiendo valores: {e}")
            return [], []
        except Exception as e:
            logger.error(f"❌ Error inesperado en parse_wavenumber_data: {e}")
            return [], []

    @staticmethod
    def filter_by_range(wavenumbers: List[float], absorbance: List[float],
                       range_min: int, range_max: int) -> tuple:
        """
        ✅ MEJORADO: Filtrar datos por rango de wavenumber
        Retorna: (filtered_wavenumbers, filtered_absorbance)
        """
        if not wavenumbers or not absorbance:
            logger.warning("⚠️ filter_by_range: Datos vacíos")
            return [], []

        try:
            indices = [i for i, w in enumerate(wavenumbers) if range_min <= w <= range_max]

            if not indices:
                logger.warning(f"⚠️ Sin datos en rango {range_min}-{range_max}")
                logger.debug(f"   Rango de datos: {min(wavenumbers):.2f}-{max(wavenumbers):.2f}")
                return [], []

            filtered_wn = [wavenumbers[i] for i in indices]
            filtered_abs = [absorbance[i] for i in indices]

            logger.debug(f"   Filtrados {len(filtered_wn)} puntos del rango {range_min}-{range_max}")
            return filtered_wn, filtered_abs
        except Exception as e:
            logger.error(f"❌ Error en filter_by_range: {e}")
            return [], []

    @staticmethod
    def align_spectra(wn1: List[float], abs1: List[float],
                     wn2: List[float], abs2: List[float],
                     tolerance: float) -> tuple:
        """
        ✅ MEJORADO: Alineación más robusta usando interpolación
        Retorna: (aligned_abs1, aligned_abs2)
        """
        if not wn1 or not abs1 or not wn2 or not abs2:
            logger.error("❌ align_spectra: Datos vacíos")
            return [], []

        try:
            wn1_arr = np.array(wn1, dtype=float)
            abs1_arr = np.array(abs1, dtype=float)
            wn2_arr = np.array(wn2, dtype=float)
            abs2_arr = np.array(abs2, dtype=float)

            # Encontrar rango común
            min_wn = max(np.min(wn1_arr), np.min(wn2_arr))
            max_wn = min(np.max(wn1_arr), np.max(wn2_arr))

            if min_wn >= max_wn:
                logger.error(f"❌ No hay solapamiento: [{np.min(wn1_arr):.2f}, {np.max(wn1_arr):.2f}] vs [{np.min(wn2_arr):.2f}, {np.max(wn2_arr):.2f}]")
                return [], []

            logger.debug(f"   Rango común: {min_wn:.2f} - {max_wn:.2f}")

            # Filtrar al rango común
            mask1 = (wn1_arr >= min_wn) & (wn1_arr <= max_wn)
            mask2 = (wn2_arr >= min_wn) & (wn2_arr <= max_wn)

            wn1_filtered = wn1_arr[mask1]
            abs1_filtered = abs1_arr[mask1]
            wn2_filtered = wn2_arr[mask2]
            abs2_filtered = abs2_arr[mask2]

            if len(wn1_filtered) < 2 or len(wn2_filtered) < 2:
                logger.error("❌ Insuficientes puntos después de filtrar al rango común")
                return [], []

            logger.debug(f"   Puntos en rango común: {len(wn1_filtered)} vs {len(wn2_filtered)}")

            # Crear rango común para interpolación
            num_points = max(len(wn1_filtered), len(wn2_filtered))
            common_wn = np.linspace(min_wn, max_wn, num_points)

            # Interpolación lineal
            try:
                f1 = interp1d(wn1_filtered, abs1_filtered, kind='linear',
                            bounds_error=False, fill_value='extrapolate')
                f2 = interp1d(wn2_filtered, abs2_filtered, kind='linear',
                            bounds_error=False, fill_value='extrapolate')

                aligned1 = f1(common_wn)
                aligned2 = f2(common_wn)

                # Convertir a listas de floats
                aligned1 = [float(x) for x in aligned1]
                aligned2 = [float(x) for x in aligned2]

                logger.debug(f"   ✅ Alineados {len(aligned1)} puntos por interpolación")
                return aligned1, aligned2

            except Exception as interp_error:
                logger.warning(f"⚠️ Fallo interpolación, usando nearest neighbor: {interp_error}")

                # Fallback: nearest neighbor
                aligned1 = []
                aligned2 = []

                for target_wn in wn1_filtered:
                    distances = np.abs(wn2_filtered - target_wn)
                    min_idx = np.argmin(distances)
                    min_dist = distances[min_idx]

                    if min_dist <= tolerance:
                        aligned1.append(float(abs1_filtered[np.where(wn1_filtered == target_wn)[0][0]]))
                        aligned2.append(float(abs2_filtered[min_idx]))

                logger.debug(f"   ✅ Alineados {len(aligned1)} puntos por nearest neighbor")
                return aligned1, aligned2

        except Exception as e:
            logger.error(f"❌ Error en alineación: {e}", exc_info=True)
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
        ✅ MEJORADO: Emparejar picos entre dos espectros con tolerancia
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

        logger.debug(f"   Matched peaks: {len(matched)}/{len(peaks1)}")

        return {
            "matched": matched,
            "unmatched": unmatched,
            "total": len(peaks1),
            "matched_count": len(matched)
        }

    # ====================================================
    # MÉTODO PRINCIPAL: CALCULAR SIMILITUD
    # ====================================================

    def calculate_similarity(self, spectrum1, spectrum2, method: str = "pearson",
                            tolerance: float = 4, range_min: int = 400,
                            range_max: int = 4000, peak_threshold: float = None) -> Optional[Dict]:
        """
        ✅ VERSIÓN MEJORADA CON LOGGING DETALLADO EN 6 FASES
        Calcula similitud entre dos espectros FTIR

        Args:
            spectrum1: Primer espectro (objeto con wavenumber_data)
            spectrum2: Segundo espectro (objeto con wavenumber_data)
            method: 'cosine', 'pearson' (recomendado), o 'euclidean'
            tolerance: Tolerancia en cm⁻¹ (default 4)
            range_min: Rango mínimo de wavenumber (default 400)
            range_max: Rango máximo de wavenumber (default 4000)
            peak_threshold: Umbral para detección de picos

        Returns:
            Dict con resultados o None si falla
        """
        if peak_threshold is None:
            peak_threshold = self.peak_threshold

        try:
            logger.info("="*70)
            logger.info(f"📊 INICIANDO CÁLCULO DE SIMILITUD")
            logger.info(f"   Spectrum1 ID: {getattr(spectrum1, 'id', 'N/A')}")
            logger.info(f"   Spectrum2 ID: {getattr(spectrum2, 'id', 'N/A')}")
            logger.info(f"   Método: {method}, Tolerancia: {tolerance} cm⁻¹")
            logger.info(f"   Rango: {range_min}-{range_max} cm⁻¹")
            logger.info("="*70)

            # 1️⃣ PARSEAR DATOS
            logger.info(f"1️⃣ FASE: PARSEO DE DATOS")
            wn1, abs1 = self.parse_wavenumber_data(spectrum1.wavenumber_data)
            wn2, abs2 = self.parse_wavenumber_data(spectrum2.wavenumber_data)

            logger.info(f"   Spectrum1: {len(wn1)} wavenumbers, {len(abs1)} intensidades")
            logger.info(f"   Spectrum2: {len(wn2)} wavenumbers, {len(abs2)} intensidades")

            if not wn1 or not abs1 or not wn2 or not abs2:
                logger.error(f"❌ FALLÓ: Datos incompletos en parseo")
                return None

            # 2️⃣ FILTRAR POR RANGO
            logger.info(f"2️⃣ FASE: FILTRADO POR RANGO")
            wn1, abs1 = self.filter_by_range(wn1, abs1, range_min, range_max)
            wn2, abs2 = self.filter_by_range(wn2, abs2, range_min, range_max)

            logger.info(f"   Spectrum1: {len(wn1)} puntos en rango")
            logger.info(f"   Spectrum2: {len(wn2)} puntos en rango")

            if not wn1 or not wn2:
                logger.error(f"❌ FALLÓ: Datos vacíos después de filtrar")
                return None

            # 3️⃣ ALINEAR ESPECTROS
            logger.info(f"3️⃣ FASE: ALINEAMIENTO DE ESPECTROS")
            aligned1, aligned2 = self.align_spectra(wn1, abs1, wn2, abs2, tolerance)

            logger.info(f"   Puntos alineados: {len(aligned1)}")

            if not aligned1 or not aligned2:
                logger.error(f"❌ FALLÓ: No se alinearon espectros")
                return None

            # 4️⃣ CALCULAR SIMILITUD
            logger.info(f"4️⃣ FASE: CÁLCULO DE SIMILITUD")
            if method == "cosine":
                score = self.cosine_similarity(aligned1, aligned2)
            elif method == "pearson":
                score = self.pearson_correlation(aligned1, aligned2)
            elif method == "euclidean":
                score = self.euclidean_similarity(aligned1, aligned2)
            else:
                logger.warning(f"⚠️ Método desconocido '{method}', usando pearson")
                score = self.pearson_correlation(aligned1, aligned2)

            logger.info(f"   Método: {method}")
            logger.info(f"   Score: {score:.4f} ({score*100:.2f}%)")

            if score < 0 or score > 1:
                logger.warning(f"⚠️ Score fuera de rango [0-1]: {score}")
                score = max(0, min(1, score))

            # 5️⃣ DETECTAR PICOS
            logger.info(f"5️⃣ FASE: DETECCIÓN DE PICOS")
            peaks1 = self.detect_peaks(wn1, abs1, threshold=peak_threshold)
            peaks2 = self.detect_peaks(wn2, abs2, threshold=peak_threshold)

            logger.info(f"   Spectrum1: {len(peaks1)} picos detectados")
            logger.info(f"   Spectrum2: {len(peaks2)} picos detectados")

            # 6️⃣ EMPAREJAR PICOS
            logger.info(f"6️⃣ FASE: EMPAREJAMIENTO DE PICOS")
            peak_match = self.match_peaks(peaks1, peaks2, tolerance)

            logger.info(f"   Coincidencias: {peak_match['matched_count']}/{peak_match['total']}")
            logger.info("="*70)
            logger.info(f"✅ CÁLCULO COMPLETADO EXITOSAMENTE")
            logger.info("="*70)

            return {
                "global_score": max(0, min(1, float(score))),
                "window_scores": [],
                "matching_peaks": len(peak_match["matched"]),
                "total_peaks": peak_match["total"],
                "matched_peaks": peak_match["matched"],
                "unmatched_peaks": peak_match["unmatched"],
                "aligned_points": len(aligned1),
                "method": method,
                "tolerance": tolerance
            }

        except AttributeError as e:
            logger.error(f"❌ ERROR DE ATRIBUTO: {str(e)}", exc_info=True)
            logger.error(f"   spectrum1 type: {type(spectrum1)}")
            logger.error(f"   spectrum2 type: {type(spectrum2)}")
            return None
        except Exception as e:
            logger.error(f"❌ EXCEPCIÓN: {str(e)}", exc_info=True)
            return None