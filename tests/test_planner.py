import json
import tempfile
import unittest
from pathlib import Path

from badabus import planner

# Red mínima de prueba:
#   A: 1 -> 2 -> 3 -> 4
#   B: 3 -> 5 -> 6   (comparte la 3 con A: transbordo posible)
#   C: 2 -> 7        (comparte la 2 con A)
#   D: 1 -> 99       (existe en la red pero NO circula hoy)
RED = {
    "A": ["1", "2", "3", "4"],
    "B": ["3", "5", "6"],
    "C": ["2", "7"],
    "D": ["1", "99"],
}
# Solo A, B y C circulan hoy (D queda fuera).
ACTIVAS = ["A", "B", "C"]
DIAS = {"LV": ACTIVAS, "SAB": ["A"], "DOM": []}


class TestPlanificar(unittest.TestCase):
    def plan(self, origen, destino, **kw):
        return planner.planificar(origen, destino, RED, ACTIVAS, **kw)

    def test_ruta_directa(self):
        rutas = self.plan("1", "4")
        self.assertIn([{"linea": "A", "subir": "1", "bajar": "4"}], rutas)
        # Con ruta directa no debe proponer nada con transbordos.
        self.assertTrue(all(len(r) == 1 for r in rutas))

    def test_un_transbordo(self):
        rutas = self.plan("1", "6")
        self.assertEqual(rutas, [[
            {"linea": "A", "subir": "1", "bajar": "3"},
            {"linea": "B", "subir": "3", "bajar": "6"},
        ]])

    def test_sin_ruta(self):
        self.assertEqual(self.plan("1", "inexistente"), [])

    def test_origen_igual_destino(self):
        # Misma parada: no hay ruta (evita la "vuelta entera" en líneas circulares).
        self.assertEqual(self.plan("2", "2"), [])

    def test_prefiere_directa_a_transbordo(self):
        # 2 -> 4 es directo por A; no debe mezclar rutas con transbordo.
        rutas = self.plan("2", "4")
        self.assertEqual(rutas, [[{"linea": "A", "subir": "2", "bajar": "4"}]])

    def test_solo_usa_lineas_activas(self):
        # 1 -> 99 solo sería posible por la línea D, que hoy no circula.
        self.assertEqual(self.plan("1", "99"), [])

    def test_no_viaja_hacia_atras(self):
        # En A la 4 va después de la 1, así que 4 -> 1 no es alcanzable en ese sentido.
        self.assertEqual(self.plan("4", "1"), [])

    def test_respeta_max_transbordos(self):
        # 1 -> 6 necesita un transbordo; con max_transbordos=0 no hay ruta.
        self.assertEqual(self.plan("1", "6", max_transbordos=0), [])

    def test_conjunto_de_activas_distinto(self):
        # Con solo la A activa, la 1 -> 6 (que necesita la B) deja de existir.
        self.assertEqual(planner.planificar("1", "6", RED, ["A"]), [])
        self.assertEqual(
            planner.planificar("1", "4", RED, ["A"]),
            [[{"linea": "A", "subir": "1", "bajar": "4"}]],
        )


class TestTransbordoAndando(unittest.TestCase):
    # A: 1 -> 2      B: 3 -> 4      La 2 y la 3 son paradas distintas pero vecinas.
    RED_PIE = {"A": ["1", "2"], "B": ["3", "4"], "D": ["2", "9"]}
    VECINAS = {"2": [("3", 0.1)], "3": [("2", 0.1)]}

    def test_sin_vecinas_no_hay_ruta(self):
        # Sin el grafo, el transbordo exige la misma parada: 1 -> 4 no existe.
        self.assertEqual(
            planner.planificar_muchos(["1"], ["4"], self.RED_PIE, ["A", "B"]), []
        )

    def test_con_vecinas_se_baja_y_se_anda(self):
        rutas = planner.planificar_muchos(
            ["1"], ["4"], self.RED_PIE, ["A", "B"], vecinas=self.VECINAS
        )
        self.assertEqual(rutas, [[
            {"linea": "A", "subir": "1", "bajar": "2"},
            {"linea": "B", "subir": "3", "bajar": "4"},
        ]])

    def test_ofrece_las_dos_versiones_cuando_hay_transbordo_en_parada(self):
        # Con las mismas lineas hay dos formas: bajarse antes y andar, o seguir hasta
        # la parada comun. El planificador no debe elegir por su cuenta: medir en
        # paradas recorridas hace ganar a la de andar, que puede ser mucho peor.
        red = {"C": ["1", "2", "3"], "E": ["9", "3", "4"]}
        vecinas = {"2": [("9", 0.2)], "9": [("2", 0.2)]}
        rutas = planner.planificar_muchos(["1"], ["4"], red, ["C", "E"], vecinas=vecinas)
        formas = {tuple(a["bajar"] != b["subir"] for a, b in zip(r, r[1:], strict=False)) for r in rutas}
        self.assertIn((True,), formas, "falta la version andando")
        self.assertIn((False,), formas, "falta la version sin andar")

    def test_no_se_baja_antes_para_andar_a_donde_el_bus_llega(self):
        # La C pasa por 5, 6 y 7. Bajarse en 6 y andar hasta 7 es absurdo: el bus va.
        red = {"C": ["5", "6", "7"], "E": ["7", "8"]}
        vecinas = {"6": [("7", 0.2)], "7": [("6", 0.2)]}
        rutas = planner.planificar_muchos(["5"], ["8"], red, ["C", "E"], vecinas=vecinas)
        for ruta in rutas:
            for anterior, siguiente in zip(ruta, ruta[1:], strict=False):
                self.assertEqual(
                    anterior["bajar"], siguiente["subir"],
                    "se baja antes para andar a una parada de su propia linea",
                )

    def test_no_se_anda_hacia_atras(self):
        # La C pasa por 5 antes que por 6: al bajar en 6 no se vuelve andando a la 5.
        red = {"C": ["5", "6"], "E": ["5", "7"]}
        vecinas = {"6": [("5", 0.1)], "5": [("6", 0.1)]}
        self.assertEqual(
            planner.planificar_muchos(["5"], ["7"], red, ["C", "E"], vecinas=vecinas),
            [[{"linea": "E", "subir": "5", "bajar": "7"}]],
        )

    def test_los_transbordos_de_siempre_siguen_saliendo(self):
        rutas = planner.planificar_muchos(
            ["1"], ["9"], self.RED_PIE, ["A", "D"], vecinas=self.VECINAS
        )
        self.assertEqual(rutas, [[
            {"linea": "A", "subir": "1", "bajar": "2"},
            {"linea": "D", "subir": "2", "bajar": "9"},
        ]])


class TestCargarDatos(unittest.TestCase):
    def test_lee_red_y_dias(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            (data_dir / "red.json").write_text(json.dumps(RED), encoding="utf-8")
            (data_dir / "dias.json").write_text(json.dumps(DIAS), encoding="utf-8")
            red, dias = planner.cargar_datos(data_dir)
        self.assertEqual(red, RED)
        self.assertEqual(dias, DIAS)


if __name__ == "__main__":
    unittest.main()
