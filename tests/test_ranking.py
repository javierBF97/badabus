import json
import math
import tempfile
import unittest
from pathlib import Path

from badabus import ranking


class TestDistanciaKm(unittest.TestCase):
    def test_misma_parada_es_cero(self):
        self.assertEqual(ranking.distancia_km((38.88, -6.97), (38.88, -6.97)), 0.0)

    def test_distancia_conocida(self):
        # ~0.01° de longitud a lat 38.88 ≈ 0.87 km
        d = ranking.distancia_km((38.88, -6.97), (38.88, -6.96))
        self.assertAlmostEqual(d, 0.87, delta=0.03)


class TestMinutosViaje(unittest.TestCase):
    RED = {"A": ["1", "2", "3", "4"]}
    PARADAS = {
        "1": (38.880, -6.970),
        "2": (38.880, -6.960),
        "3": (38.880, -6.950),
        "4": (38.880, -6.940),
    }

    def test_suma_distancias_y_aplica_factores(self):
        ruta = [{"linea": "A", "subir": "1", "bajar": "4"}]
        km = (
            ranking.distancia_km(self.PARADAS["1"], self.PARADAS["2"])
            + ranking.distancia_km(self.PARADAS["2"], self.PARADAS["3"])
            + ranking.distancia_km(self.PARADAS["3"], self.PARADAS["4"])
        )
        esperado = km * ranking.FACTOR_SINUOSIDAD / ranking.VELOCIDAD_COMERCIAL_KMH * 60
        self.assertAlmostEqual(ranking.minutos_viaje(ruta, self.RED, self.PARADAS), esperado, places=6)

    def test_ignora_paradas_sin_coordenadas(self):
        paradas = {k: v for k, v in self.PARADAS.items() if k != "2"}
        ruta = [{"linea": "A", "subir": "1", "bajar": "4"}]
        km = (
            ranking.distancia_km(paradas["1"], paradas["3"])
            + ranking.distancia_km(paradas["3"], paradas["4"])
        )
        esperado = km * ranking.FACTOR_SINUOSIDAD / ranking.VELOCIDAD_COMERCIAL_KMH * 60
        self.assertAlmostEqual(ranking.minutos_viaje(ruta, self.RED, paradas), esperado, places=6)

    def test_paradas_repetidas_ida_y_vuelta(self):
        # Regresión: línea con paradas repetidas (ida y vuelta).
        # Fija el comportamiento conocido: los índices se resuelven por
        # PRIMERA aparición, así que un tramo del retorno se mide con más
        # saltos que lo ideal. Esto es consistente con cómo el planificador
        # construye sus tramos, pero no es lo idealmente deseado en términos
        # de precisión de medida.
        red = {"L1": ["A", "B", "C", "D", "C", "B", "A"]}
        paradas = {
            "A": (38.880, -6.970),
            "B": (38.880, -6.960),
            "C": (38.880, -6.950),
            "D": (38.880, -6.940),
        }
        # Tramo de retorno: desde B (en la vuelta, índice 5) a A (índice 6).
        # Pero seq.index("B") = 1 (primera aparición), así que se calcula
        # de B(1) a A(6), recorriendo B->C->D->C->B->A (5 saltos).
        ruta = [{"linea": "L1", "subir": "B", "bajar": "A"}]
        km = (
            ranking.distancia_km(paradas["B"], paradas["C"])
            + ranking.distancia_km(paradas["C"], paradas["D"])
            + ranking.distancia_km(paradas["D"], paradas["C"])
            + ranking.distancia_km(paradas["C"], paradas["B"])
            + ranking.distancia_km(paradas["B"], paradas["A"])
        )
        esperado = km * ranking.FACTOR_SINUOSIDAD / ranking.VELOCIDAD_COMERCIAL_KMH * 60
        self.assertAlmostEqual(ranking.minutos_viaje(ruta, red, paradas), esperado, places=6)

    def test_ruta_multi_tramo_suma_correctamente(self):
        # Regresión: ruta de dos tramos (transbordo) suma correctamente.
        red = {
            "A": ["1", "2", "3"],
            "B": ["3", "4", "5"],
        }
        paradas = {
            "1": (38.880, -6.970),
            "2": (38.880, -6.960),
            "3": (38.880, -6.950),
            "4": (38.880, -6.940),
            "5": (38.880, -6.930),
        }
        # Tramo 1: línea A, de 1 a 3.
        # Tramo 2: línea B, de 3 a 5.
        ruta = [
            {"linea": "A", "subir": "1", "bajar": "3"},
            {"linea": "B", "subir": "3", "bajar": "5"},
        ]
        km1 = (
            ranking.distancia_km(paradas["1"], paradas["2"])
            + ranking.distancia_km(paradas["2"], paradas["3"])
        )
        km2 = (
            ranking.distancia_km(paradas["3"], paradas["4"])
            + ranking.distancia_km(paradas["4"], paradas["5"])
        )
        km_total = km1 + km2
        esperado = km_total * ranking.FACTOR_SINUOSIDAD / ranking.VELOCIDAD_COMERCIAL_KMH * 60
        self.assertAlmostEqual(ranking.minutos_viaje(ruta, red, paradas), esperado, places=6)


class TestCodigoLinea(unittest.TestCase):
    def test_quita_prefijo_linea(self):
        self.assertEqual(ranking.codigo_linea("LÍNEA M2"), "M2")
        self.assertEqual(ranking.codigo_linea("LINEA 18"), "18")

    def test_alias_bgm(self):
        self.assertEqual(ranking.codigo_linea("LÍNEA BGM1"), "BG1")

    def test_sin_prefijo_se_queda_igual(self):
        self.assertEqual(ranking.codigo_linea("M2"), "M2")


class TestMinutosEspera(unittest.TestCase):
    def test_minutos(self):
        self.assertEqual(ranking.minutos_espera("4 Minutos."), 4.0)

    def test_proximo_es_cero(self):
        self.assertEqual(ranking.minutos_espera("Próximo."), 0.0)

    def test_sin_numero_es_infinito(self):
        self.assertEqual(ranking.minutos_espera("Sin datos"), math.inf)


class TestEsperasPorLinea(unittest.TestCase):
    def test_toma_el_minimo_por_linea(self):
        tiempos = [
            {"linea": "LÍNEA M2", "metros": 3000, "tiempo": "9 Minutos."},
            {"linea": "LÍNEA M2", "metros": 1000, "tiempo": "3 Minutos."},
            {"linea": "LÍNEA 18", "metros": 500, "tiempo": "Próximo."},
        ]
        self.assertEqual(ranking.esperas_por_linea(tiempos), {"M2": 3.0, "18": 0.0})


class TestPuntuar(unittest.TestCase):
    # A: 1->2 corto; B: 1->...->2 dando un rodeo largo.
    RED = {
        "A": ["1", "2"],
        "B": ["1", "9", "8", "7", "6", "2"],
        "C": ["1", "2"],
    }
    PARADAS = {
        "1": (38.880, -6.970),
        "2": (38.880, -6.965),
        "9": (38.900, -6.930),
        "8": (38.905, -6.925),
        "7": (38.905, -6.960),
        "6": (38.890, -6.968),
    }

    def test_ordena_por_total_y_filtra_infumables(self):
        rutas = [
            [{"linea": "B", "subir": "1", "bajar": "2"}],
            [{"linea": "A", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertEqual([r["tramos"][0]["linea"] for r in salida], ["A"])  # B se descarta

    def test_la_espera_desempata_entre_iguales(self):
        # A y C recorren lo mismo (1->2); la espera decide.
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"A": 8.0, "C": 1.0})
        self.assertEqual(salida[0]["tramos"][0]["linea"], "C")

    def test_forma_de_cada_ruta(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"A": 4.0})
        self.assertEqual(set(salida[0]), {"tramos", "viaje_min", "espera_min"})
        self.assertIsInstance(salida[0]["viaje_min"], int)
        self.assertEqual(salida[0]["espera_min"], 4)

    def test_espera_desconocida_es_none(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertIsNone(salida[0]["espera_min"])

    def test_sin_paradas_devuelve_sin_puntuar(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, {}, {"A": 4.0})
        self.assertEqual(salida, [{"tramos": rutas[0], "viaje_min": None, "espera_min": None}])

    def test_respeta_el_limite(self):
        # Muchas rutas parecidas (misma línea directa) -> no se filtran, pero se recorta.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}] for _ in range(ranking.LIMITE_RUTAS + 3)]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"A": 4.0})
        self.assertEqual(len(salida), ranking.LIMITE_RUTAS)


class TestCargarParadas(unittest.TestCase):
    def test_lee_coordenadas(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            (data_dir / "paradas.json").write_text(
                json.dumps([{"id": "1", "nombre": "X", "lat": 38.88, "lon": -6.97}]),
                encoding="utf-8",
            )
            paradas = ranking.cargar_paradas(data_dir)
        self.assertEqual(paradas, {"1": (38.88, -6.97)})


class TestMinutosAndando(unittest.TestCase):
    def test_aplica_callejeo_y_velocidad(self):
        esperado = 1.0 * ranking.FACTOR_CALLEJEO / ranking.VELOCIDAD_ANDANDO_KMH * 60
        self.assertAlmostEqual(ranking.minutos_andando(1.0), esperado, places=6)

    def test_cero_es_cero(self):
        self.assertEqual(ranking.minutos_andando(0.0), 0.0)


class TestParadasCercanas(unittest.TestCase):
    PARADAS = {
        "cerca": (38.8800, -6.9700),
        "media": (38.8810, -6.9700),
        "lejos": (38.8850, -6.9700),
        "fuera": (38.9500, -6.9700),
    }

    def test_ordena_por_distancia_y_devuelve_km(self):
        salida = ranking.paradas_cercanas(38.8800, -6.9700, self.PARADAS)
        self.assertEqual([i for i, _ in salida][:3], ["cerca", "media", "lejos"])
        self.assertAlmostEqual(salida[0][1], 0.0, places=6)

    def test_descarta_las_de_fuera_del_radio(self):
        salida = ranking.paradas_cercanas(38.8800, -6.9700, self.PARADAS)
        self.assertNotIn("fuera", [i for i, _ in salida])

    def test_respeta_el_maximo(self):
        muchas = {str(n): (38.8800 + n / 10000, -6.9700) for n in range(20)}
        salida = ranking.paradas_cercanas(38.8800, -6.9700, muchas)
        self.assertEqual(len(salida), ranking.MAX_PARADAS_CERCANAS)

    def test_sin_paradas_cerca_devuelve_vacio(self):
        salida = ranking.paradas_cercanas(0.0, 0.0, self.PARADAS)
        self.assertEqual(salida, [])


if __name__ == "__main__":
    unittest.main()
