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
        # El total se redondea entero, no como suma de redondeos: puede bailar un minuto.
        suma = salida[0]["viaje_min"] + salida[0]["espera_min"]
        self.assertLessEqual(abs(salida[0]["total_min"] - suma), 1)
        self.assertEqual(salida[0]["espera_min"], 4)

    HORARIOS = {"A": {"LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": 20}}}

    def test_la_caminata_del_transbordo_entra_en_el_total(self):
        # Bajar en 2 y andar hasta 3 para coger la B: esos metros son tiempo.
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
        # El servicio da tiempos de cualquier parada, tambien la del transbordo. Si
        # ahi consta que la C pasa en 15 y llegamos sobre el minuto 1, la espera son
        # ~14: no la media frecuencia (10), que es lo que se supondria sin ese dato.
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
        # Llegamos sobre el minuto 1 y la C acaba de pasar (en 0): se coge la de 20.
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
        # Al bajarte no sabes en que punto del horario de la otra linea caes: una linea
        # cada 20 minutos son 10 de espera esperable, y eso entra en el total.
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
        # Si la A sola te deja en el destino, "A y luego C" llega mas tarde al mismo
        # sitio: no es una alternativa, es la misma ruta con un bus de propina.
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

    def test_una_linea_parada_no_desplaza_a_una_que_circula(self):
        # La A no pasa a esa hora y la C si. Aunque la A saliera mejor por tiempo, no
        # es una alternativa: la que se puede coger va primero.
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
        # Devolver lista vacia diria "no hay ruta", y es falso: la hay, pero no ahora.
        horarios = {"A": {"LV": {"desde": "07:00", "hasta": "15:00", "frecuencia_min": 20}}}
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {}, horarios=horarios,
            tipo_dia="LV", ahora_min=19 * 60,
        )
        self.assertEqual(salida[0]["aviso_espera"], "fuera_de_servicio")

    def test_con_frecuencia_se_sabe_cuando_pasa_el_siguiente(self):
        # 0.9 km son ~15.6 min andando, y el bus anunciado pasa en 3: se escapa. Pero
        # la linea va cada 20, asi que el siguiente pasa en 23 y ya estas alli desde el
        # 15.6: la espera son los ~7 minutos que van de uno a otro.
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
        # Quien clone el repo no tiene el fichero: la espera queda desconocida.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 3.0}}, andando_origen={"1": 0.9},
        )
        self.assertEqual(salida[0]["aviso_espera"], "no_llegas")
        self.assertIsNone(salida[0]["espera_min"])
        self.assertIsNone(salida[0]["espera_max_min"])

    def test_un_bus_que_pasa_antes_de_llegar_no_cuenta_como_espera(self):
        # 0.9 km andando son ~15 min: un bus en 3 no se coge. Y cuándo pasa el
        # siguiente no lo dice el servicio, así que la espera es desconocida.
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 3.0}}, andando_origen={"1": 0.9},
        )
        self.assertEqual(salida[0]["aviso_espera"], "no_llegas")
        self.assertIsNone(salida[0]["espera_min"])

    def test_un_bus_que_da_tiempo_a_coger_si_cuenta(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(
            rutas, self.RED, self.PARADAS, {"1": {"A": 30.0}}, andando_origen={"1": 0.9},
        )
        self.assertIsNone(salida[0]["aviso_espera"])
        self.assertEqual(salida[0]["espera_min"], 30)

    def test_sin_dato_de_paso_se_avisa(self):
        rutas = [[{"linea": "A", "subir": "1", "bajar": "2"}]]
        salida = ranking.puntuar(rutas, self.RED, self.PARADAS, {})
        self.assertEqual(salida[0]["aviso_espera"], "sin_datos")
        self.assertIsNone(salida[0]["espera_min"])

    def test_eligiendo_la_parada_a_mano_no_se_supone_caminata(self):
        # Sin coordenadas no se sabe dónde está el usuario, así que no se puede
        # afirmar que no llegue.
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
        # Las dos rutas son iguales de largas en bus; decide la caminata.
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
        # Alternativas de verdad: cuanto mas lejos queda la parada del destino mas dura
        # el viaje, pero menos hay que andar para llegar a ella. Ninguna gana a otra en
        # todo, asi que ninguna se descarta por dominada y solo actua el recorte.
        cuantas = ranking.LIMITE_RUTAS + 3
        km_por_grado = 86.7                      # a esta latitud
        destino = (38.880, -6.960)
        paradas = {"2": destino}
        andando = {}
        for i in range(cuantas):
            viaje_km = (5 + 3 * i) / 3.9         # el viaje crece con i
            paradas[f"s{i}"] = (38.880, destino[1] - viaje_km / km_por_grado)
            andando[f"s{i}"] = ((7 - i) / 17.3)  # y la caminata mengua
        red = {f"L{i}": [f"s{i}", "2"] for i in range(cuantas)}
        rutas = [[{"linea": f"L{i}", "subir": f"s{i}", "bajar": "2"}] for i in range(cuantas)]
        salida = ranking.puntuar(rutas, red, paradas, {}, andando_origen=andando)
        self.assertEqual(len(salida), ranking.LIMITE_RUTAS)

    def test_descarta_la_que_pierde_en_todo(self):
        # Mas lenta, mas caminata y un transbordo de mas: no hay a quien le convenga.
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
        # "C2 o 5" y "5 o C2" son el mismo viaje: tras fusionar alternativas, el
        # conjunto de lineas de cada tramo es identico.
        red = {"A": ["1", "2"], "C": ["1", "2"]}
        paradas = {"1": (38.880, -6.970), "2": (38.880, -6.965)}
        rutas = [
            [{"linea": "A", "subir": "1", "bajar": "2"}],
            [{"linea": "C", "subir": "1", "bajar": "2"}],
        ]
        salida = ranking.puntuar(rutas, red, paradas, {})
        self.assertEqual(len(salida), 1)

    def test_no_repite_la_misma_combinacion_de_lineas(self):
        # La misma línea cogida en otra parada es el mismo viaje andando de más,
        # no una alternativa. Se queda la más corta.
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
        # A y C van de la 1 a la 2 igual: es un viaje con dos buses que sirven.
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
        # Antes se recortaba a las más próximas, y eso escondía líneas enteras:
        # varias paradas pegadas suelen ser de las mismas líneas.
        muchas = {str(n): (38.8800 + n / 10000, -6.9700) for n in range(20)}
        salida = ranking.paradas_cercanas(38.8800, -6.9700, muchas)
        self.assertEqual(len(salida), 20)

    def test_sin_paradas_cerca_devuelve_vacio(self):
        salida = ranking.paradas_cercanas(0.0, 0.0, self.PARADAS)
        self.assertEqual(salida, [])


if __name__ == "__main__":
    unittest.main()
