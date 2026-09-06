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
        # ~0.01° of longitude at lat 38.88 is about 0.87 km
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
        # Regression: a line with repeated stops, outward and back.
        # It fixes the known behaviour: indexes resolve to the FIRST
        # occurrence, so a return leg is measured with more hops than it
        # should be. This is consistent with how the planner builds its legs,
        # but it is not what is ideally wanted in terms of measurement
        # accuracy.
        red = {"L1": ["A", "B", "C", "D", "C", "B", "A"]}
        paradas = {
            "A": (38.880, -6.970),
            "B": (38.880, -6.960),
            "C": (38.880, -6.950),
            "D": (38.880, -6.940),
        }
        # Return leg: from B, on the way back at index 5, to A at index 6.
        # But seq.index("B") = 1, the first occurrence, so it is calculated
        # from B(1) to A(6), through B->C->D->C->B->A, five hops.
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
        # Regression: a two-leg route, with a transfer, adds up correctly.
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
        # Leg 1: line A, from 1 to 3.
        # Leg 2: line B, from 3 to 5.
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
    # A: 1->2 short. B: 1->...->2 with a long detour.
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
        self.assertEqual([r["tramos"][0]["linea"] for r in salida], ["A"])

    def test_la_espera_de_su_parada_desempata(self):
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        esperas = {"1": {"A": 8.0, "C": 1.0}}
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, esperas)
        self.assertEqual(salida[0]["tramos"][0]["linea"], "C")

    def test_forma_de_cada_ruta(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"1": {"A": 4.0}})
        self.assertEqual(
            set(salida[0]),
            {"tramos", "total_min", "viaje_min", "espera_min", "espera_max_min",
             "espera_transbordo_min", "andando_min", "aviso_espera"},
        )
        # The total is rounded whole, not as a sum of roundings: it can move by a minute.
        suma = salida[0]["viaje_min"] + salida[0]["espera_min"]
        self.assertLessEqual(abs(salida[0]["total_min"] - suma), 1)
        self.assertEqual(salida[0]["espera_min"], 4)

    HORARIOS = {"A": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}}

    def test_llegando_andando_la_espera_sigue_saliendo_del_tiempo_real(self):
        # You alight at 2, walk to 3, another stop, and board B there. The wait must
        # come from the live time of stop 3, with the walk already counted.
        red = {"A": ["1", "2"], "B": ["3", "4"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967),
                   "3": (38.881, -6.967), "4": (38.881, -6.964)}
        horarios = {"B": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}}
        ruta = [{"linea": "A", "subir": "1", "bajar": "2"},
                {"linea": "B", "subir": "3", "bajar": "4"}]
        salida = ranking.puntuar(
            [ruta], red, paradas, {"1": {"A": 0.0}, "3": {"B": 30.0}},
            horarios=horarios, tipo_dia="LV", ahora_min=10 * 60,
        )
        # With the bus 30 min away there is time to spare: the wait is what is left
        # after the walk, so less than 30 and more than half the frequency (10).
        espera = salida[0]["espera_transbordo_min"]
        self.assertLess(espera, 30)
        self.assertGreater(espera, 10)

    def test_la_caminata_del_transbordo_entra_en_el_total(self):
        # Alight at 2 and walk to 3 to board B: those metres are time.
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967),
                   "3": (38.881, -6.967), "4": (38.881, -6.964)}
        anda = [{"linea": "A", "subir": "1", "bajar": "2"},
                {"linea": "B", "subir": "3", "bajar": "4"}]
        km = ranking.km_entre_tramos(anda, paradas)
        self.assertGreater(km, 0)
        self.assertAlmostEqual(km, ranking.distancia_km(paradas["2"], paradas["3"]))

    def test_sin_caminata_entre_tramos_no_suma(self):
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.965)}
        mismo = [{"linea": "A", "subir": "1", "bajar": "2"},
                 {"linea": "C", "subir": "2", "bajar": "3"}]
        self.assertEqual(ranking.km_entre_tramos(mismo, paradas), 0.0)

    def test_vecindad_es_simetrica_y_respeta_el_radio(self):
        paradas = {"a": (38.880, -6.970), "b": (38.8802, -6.970), "lejos": (38.900, -6.970)}
        vec = ranking.vecindad(paradas, radio_km=0.1)
        self.assertEqual([p for p, _ in vec["a"]], ["b"])
        self.assertEqual([p for p, _ in vec["b"]], ["a"])
        self.assertEqual(vec["lejos"], [])

    def test_una_parada_no_es_vecina_de_si_misma(self):
        paradas = {"a": (38.880, -6.970), "b": (38.8802, -6.970)}
        self.assertNotIn("a", [p for p, _ in ranking.vecindad(paradas)["a"]])

    def test_el_transbordo_usa_el_tiempo_real_de_esa_parada(self):
        # The service gives arrivals for any stop, the transfer one included. If it
        # says there that C calls in 15 and we arrive around minute 1, the wait is
        # about 14, not half the frequency (10), which is the assumption without it.
        red = {"A": ["1", "2"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.965)}
        horarios = {"C": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"},
                  {"linea": "C", "subir": "2", "bajar": "3"}]]
        salida = ranking.puntuar(
            rutas, red, paradas, {"1": {"A": 0.0}, "2": {"C": 15.0}},
            horarios=horarios, tipo_dia="LV", ahora_min=10 * 60,
        )
        self.assertEqual(salida[0]["espera_transbordo_min"], 14)

    def test_si_el_bus_del_transbordo_se_escapa_se_coge_el_siguiente(self):
        # We arrive around minute 1 and C has just gone past, at 0: the one at 20 is taken.
        red = {"A": ["1", "2"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.965)}
        horarios = {"C": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"},
                  {"linea": "C", "subir": "2", "bajar": "3"}]]
        salida = ranking.puntuar(
            rutas, red, paradas, {"1": {"A": 0.0}, "2": {"C": 0.0}},
            horarios=horarios, tipo_dia="LV", ahora_min=10 * 60,
        )
        self.assertEqual(salida[0]["espera_transbordo_min"], 19)

    def test_un_transbordo_cuesta_media_frecuencia(self):
        # When you alight you do not know where in the timetable of the other line you
        # land: a line every 20 minutes means 10 of expected wait, and that goes in the
        # total.
        red = {"A": ["1", "2"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.965)}
        horarios = {
            "A": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}},
            "C": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}},
        }
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"},
                  {"linea": "C", "subir": "2", "bajar": "3"}]]
        salida = ranking.puntuar(
            rutas, red, paradas, {}, horarios=horarios, tipo_dia="LV", ahora_min=10 * 60,
        )
        self.assertEqual(salida[0]["espera_transbordo_min"], 10)

    def test_sin_frecuencia_el_transbordo_tampoco_es_gratis(self):
        red = {"A": ["1", "2"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.965)}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"},
                  {"linea": "C", "subir": "2", "bajar": "3"}]]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(salida[0]["espera_transbordo_min"], ranking.ESPERA_TRANSBORDO_MIN)

    def test_sin_transbordos_no_se_penaliza(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertIsNone(salida[0]["espera_transbordo_min"])

    def test_a_igualdad_de_tiempo_gana_la_de_menos_transbordos(self):
        red = {"A": ["1", "2", "3"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.9655), "3": (38.880, -6.965)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"},
             {"linea": "C", "subir": "2", "bajar": "3"}],
            [{"linea": "A", "subir": "1", "bajar": "3"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual([t["linea"] for t in salida[0]["tramos"]], ["A"])

    def test_no_ofrece_una_ruta_mas_larga_que_empieza_igual(self):
        # If A alone drops you at the destination, "A and then C" reaches the same
        # place later: it is not an alternative, it is that route with a spare bus.
        red = {"A": ["1", "2", "3"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.966), "3": (38.880, -6.965)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "3"}],
            [{"linea": "A", "subir": "1", "bajar": "2"},
             {"linea": "C", "subir": "2", "bajar": "3"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(len(salida), 1)
        self.assertEqual([t["linea"] for t in salida[0]["tramos"]], ["A"])

    def test_una_espera_desconocida_no_borra_una_conocida(self):
        # The bias of counting zero for an unknown wait: the least known route comes
        # out with the lowest possible total and discards the others by dominating them.
        # B, with no data, can erase A from the screen, and A is certain at 15 minutes.
        # B may sort ahead, which is what the expected value says, but A is still shown.
        red = {"A": ["1", "2"], "B": ["3", "2"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.960), "3": (38.8801, -6.9701)}
        horarios = {lin: {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}
                    for lin in ("A", "B")}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}],
                 [{"linea": "B", "subir": "3", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, red, paradas, {"1": {"A": 12.0}},
            horarios=horarios, tipo_dia="LV", ahora_min=10 * 60,
        )
        lineas = [r["tramos"][0]["linea"] for r in salida]
        self.assertIn("A", lineas)
        # And what is shown for A is still its closed total, not an estimate.
        cerrada = next(r for r in salida if r["tramos"][0]["linea"] == "A")
        self.assertEqual(cerrada["espera_min"], 12)

    def test_la_desconocida_no_se_ordena_como_si_pasara_ya(self):
        # With no published frequency there is no bound, so ESPERA_SIN_DATO_MIN
        # applies. With that, a route with no data no longer beats a known one that is
        # faster than the assumption. To count zero made it win every time.
        red = {"A": ["1", "2"], "B": ["3", "2"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.960), "3": (38.8801, -6.9701)}
        rutas = [[{"linea": "B", "subir": "3", "bajar": "2"}],
                 [{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, red, paradas, {"1": {"A": 1.0}})
        self.assertEqual(salida[0]["tramos"][0]["linea"], "A")

    def test_una_linea_parada_no_desplaza_a_una_que_circula(self):
        # A does not run at that hour and C does. Even if A came out better on time,
        # it is not an alternative: the one you can take goes first.
        horarios = {
            "A": {"LV": {"desde": "07:00", "hasta": "15:00", "frecuencia_min": 20}},
            "C": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}},
        }
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 5.0, "C": 5.0}},
            horarios=horarios, tipo_dia="LV", ahora_min=19 * 60,
        )
        self.assertEqual([r["tramos"][0]["linea"] for r in salida], ["C"])

    def test_si_no_circula_ninguna_se_muestran_igual(self):
        # An empty list would say "no route", and that is false: there is one, but not now.
        horarios = {"A": {"LV": {"desde": "07:00", "hasta": "15:00", "frecuencia_min": 20}}}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {}, horarios=horarios,
            tipo_dia="LV", ahora_min=19 * 60,
        )
        self.assertEqual(salida[0]["aviso_espera"], "fuera_de_servicio")

    def test_con_frecuencia_se_sabe_cuando_pasa_el_siguiente(self):
        # 0.9 km is about 15.6 min on foot, and the announced bus calls in 3: it is
        # missed. But the line runs every 20, so the next one calls at 23 and you have
        # been there since 15.6: the wait is the ~7 minutes between the two.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 3.0}}, andando_origen={"1": 0.9},
            horarios=self.HORARIOS, tipo_dia="LV", ahora_min=10 * 60,
        )
        self.assertEqual(salida[0]["aviso_espera"], "no_llegas")
        self.assertEqual(salida[0]["espera_min"], 7)

    def test_sin_dato_la_frecuencia_acota_la_espera(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {},
            horarios=self.HORARIOS, tipo_dia="LV", ahora_min=10 * 60,
        )
        self.assertEqual(salida[0]["aviso_espera"], "sin_datos")
        self.assertIsNone(salida[0]["espera_min"])
        self.assertEqual(salida[0]["espera_max_min"], 20)

    def test_fuera_de_horario_no_es_falta_de_datos(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {},
            horarios=self.HORARIOS, tipo_dia="LV", ahora_min=23 * 60 + 40,
        )
        self.assertEqual(salida[0]["aviso_espera"], "fuera_de_servicio")

    def test_sin_horarios_se_comporta_como_antes(self):
        # Anyone who clones the repo has no such file: the wait stays unknown.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 3.0}}, andando_origen={"1": 0.9},
        )
        self.assertEqual(salida[0]["aviso_espera"], "no_llegas")
        self.assertIsNone(salida[0]["espera_min"])
        self.assertIsNone(salida[0]["espera_max_min"])

    def test_un_bus_que_pasa_antes_de_llegar_no_cuenta_como_espera(self):
        # 0.9 km on foot is about 15 min: a bus in 3 cannot be caught. And the
        # service does not say when the next one calls, so the wait is unknown.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 3.0}}, andando_origen={"1": 0.9},
        )
        self.assertEqual(salida[0]["aviso_espera"], "no_llegas")
        self.assertIsNone(salida[0]["espera_min"])

    def test_un_bus_que_da_tiempo_a_coger_si_cuenta(self):
        # 0.9 km is about 16 min on foot and the bus calls at 30 FROM NOW: you arrive
        # at minute 16 and wait until 30, that is 14. To add the whole 30 would count
        # the walk twice, once inside the wait and once again on its own.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 30.0}}, andando_origen={"1": 0.9},
        )
        self.assertIsNone(salida[0]["aviso_espera"])
        self.assertEqual(salida[0]["espera_min"], 14)
        r = salida[0]
        self.assertEqual(r["total_min"], r["andando_min"] + r["espera_min"] + r["viaje_min"])

    def test_la_espera_es_la_de_la_parada_no_la_de_ahora(self):
        # With no walk, the wait starts now: the wait is the announced arrival.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"1": {"A": 8.0}})
        self.assertEqual(salida[0]["espera_min"], 8)

    def test_sin_dato_de_paso_se_avisa(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertEqual(salida[0]["aviso_espera"], "sin_datos")
        self.assertIsNone(salida[0]["espera_min"])

    def test_eligiendo_la_parada_a_mano_no_se_supone_caminata(self):
        # Without coordinates the position of the user is unknown, so it cannot be
        # asserted that they do not make it.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {"1": {"A": 0.0}})
        self.assertIsNone(salida[0]["aviso_espera"])

    def test_sin_caminata_andando_es_none(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertIsNone(salida[0]["andando_min"])

    def test_la_caminata_entra_en_el_total(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {},
            andando_origen={"1": 0.5}, andando_destino={"2": 0.25},
        )
        esperado = round(ranking.minutos_andando(0.75))
        self.assertEqual(salida[0]["andando_min"], esperado)

    def test_una_parada_lejana_pierde_contra_una_cercana(self):
        # Both routes are equally long by bus: the walk decides.
        red = {"A": ["1", "2"], "C": ["6", "2"]}
        rutas = [
            [{"linea": "C", "subir": "6", "bajar": "2"}],
            [{"linea": "A", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(
            rutas, red, self.PARADAS, {},
            andando_origen={"1": 0.05, "6": 0.9}, andando_destino={},
        )
        self.assertEqual(salida[0]["tramos"][0]["linea"], "A")

    def test_sin_paradas_devuelve_sin_puntuar(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, {}, {"1": {"A": 4.0}})
        self.assertEqual(
            salida,
            [{"tramos": rutas[0], "total_min": None, "viaje_min": None,
              "espera_min": None, "espera_max_min": None,
              "espera_transbordo_min": None,
              "andando_min": None, "aviso_espera": None}],
        )

    def test_respeta_el_limite(self):
        # Real alternatives: the further the stop is from the destination the longer
        # the ride, but the less you walk to reach it. Neither wins on everything, so
        # none is discarded as dominated and only the trim applies.
        cuantas = ranking.LIMITE_RUTAS + 3
        km_por_grado = 86.7                      # a esta latitud
        destino = (38.880, -6.960)
        paradas = {"2": destino}
        andando = {}
        for i in range(cuantas):
            viaje_km = (5 + 3 * i) / 3.9         # the ride grows with i
            paradas[f"s{i}"] = (38.880, destino[1] - viaje_km / km_por_grado)
            andando[f"s{i}"] = ((7 - i) / 17.3)  # y la caminata mengua
        red = {f"L{i}": [f"s{i}", "2"] for i in range(cuantas)}
        rutas = [[{"linea": f"L{i}", "subir": f"s{i}", "bajar": "2"}] for i in range(cuantas)]
        salida = ranking.puntuar(rutas, red, paradas, {}, andando_origen=andando)
        self.assertEqual(len(salida), ranking.LIMITE_RUTAS)

    def test_descarta_la_que_pierde_en_todo(self):
        # Slower, more walking and one transfer more: it suits nobody.
        red = {"A": ["1", "3"], "B": ["1", "2"], "C": ["2", "3"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.967), "3": (38.880, -6.960)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "3"}],
            [{"linea": "B", "subir": "1", "bajar": "2"},
             {"linea": "C", "subir": "2", "bajar": "3"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(len(salida), 1)
        self.assertEqual([t["linea"] for t in salida[0]["tramos"]], ["A"])

    def test_no_repite_el_mismo_viaje_con_las_lineas_al_reves(self):
        # "C2 or 5" and "5 or C2" are the same trip: after alternatives are merged,
        # the set of lines of each leg is identical.
        red = {"A": ["1", "2"], "C": ["1", "2"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.965)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(len(salida), 1)

    def test_no_repite_la_misma_combinacion_de_lineas(self):
        # The same line boarded at another stop is the same trip with more walking,
        # not an alternative. The shortest one is kept.
        red = {"A": ["1", "3", "2"]}
        paradas = {"1": (38.880, -6.970), "3": (38.880, -6.968), "2": (38.880, -6.965)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "A", "subir": "3", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["tramos"][0]["subir"], "3")

    def test_agrupa_las_lineas_que_hacen_el_mismo_tramo(self):
        # A and C run from 1 to 2 alike: it is one trip with two buses that serve it.
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["tramos"][0]["alternativas"], ["C"])


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

    def test_devuelve_todas_las_del_radio(self):
        # To trim to the nearest stops hides whole lines: several stops close
        # together tend to serve the same lines.
        muchas = {str(n): (38.8800 + n / 10000, -6.9700) for n in range(20)}
        salida = ranking.paradas_cercanas(38.8800, -6.9700, muchas)
        self.assertEqual(len(salida), 20)

    def test_sin_paradas_cerca_devuelve_vacio(self):
        salida = ranking.paradas_cercanas(0.0, 0.0, self.PARADAS)
        self.assertEqual(salida, [])


if __name__ == "__main__":
    unittest.main()
