import json
import tempfile
import unittest
from pathlib import Path

from badabus import frecuencias

# Una linea de cada forma: frecuencia fija, tramos que cambian durante el dia, y
# salidas sueltas sin patron.
HORARIOS = {
    "lineas": {
        "FIJA": {
            "LV": {"desde": "07:00", "hasta": "23:20", "frecuencia_min": 20,
                   "cabeceras": {"Norte": [0, 20, 40]}},
        },
        "TRAMOS": {
            "LV": {"desde": "07:00", "hasta": "23:00", "frecuencia_min": [15, 20],
                   "tramos": {"Norte": [
                       {"desde": "07:00", "hasta": "13:00", "minutos": [0, 15, 30, 45]},
                       {"desde": "13:00", "hasta": "23:00", "minutos": [0, 20, 40]},
                   ]}},
        },
        "SALIDAS": {
            "LV": {"desde": "06:30", "hasta": "22:45",
                   "salidas": {"Norte": ["06:30", "08:00", "09:30"]}},
        },
    }
}


class TestCargar(unittest.TestCase):
    def test_lee_las_lineas(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "frecuencias.json").write_text(json.dumps(HORARIOS), encoding="utf-8")
            self.assertEqual(set(frecuencias.cargar(Path(d))), {"FIJA", "TRAMOS", "SALIDAS"})

    def test_sin_fichero_devuelve_vacio(self):
        # Es el caso de quien clona el repo: no debe romper nada.
        self.assertEqual(frecuencias.cargar(Path("no-existe")), {})

    def test_fichero_ilegible_devuelve_vacio(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "frecuencias.json").write_text("{esto no es json", encoding="utf-8")
            self.assertEqual(frecuencias.cargar(Path(d)), {})


class TestIntervalo(unittest.TestCase):
    H = HORARIOS["lineas"]

    def test_frecuencia_fija(self):
        self.assertEqual(frecuencias.intervalo_min(self.H, "FIJA", "LV", 9 * 60), 20.0)

    def test_los_tramos_cambian_con_la_hora(self):
        # Cuatro salidas por hora por la mañana, tres por la tarde.
        self.assertEqual(frecuencias.intervalo_min(self.H, "TRAMOS", "LV", 10 * 60), 15.0)
        self.assertEqual(frecuencias.intervalo_min(self.H, "TRAMOS", "LV", 18 * 60), 20.0)

    def test_salidas_sueltas_dan_el_hueco(self):
        # Entre las 08:00 y las 09:30 hay hora y media.
        self.assertEqual(frecuencias.intervalo_min(self.H, "SALIDAS", "LV", 8 * 60 + 30), 90.0)

    def test_linea_desconocida(self):
        self.assertIsNone(frecuencias.intervalo_min(self.H, "NO_EXISTE", "LV", 9 * 60))

    def test_tipo_de_dia_sin_horario(self):
        self.assertIsNone(frecuencias.intervalo_min(self.H, "FIJA", "DOM", 9 * 60))

    def test_sin_horarios_no_inventa(self):
        self.assertIsNone(frecuencias.intervalo_min({}, "FIJA", "LV", 9 * 60))


class TestEnServicio(unittest.TestCase):
    H = HORARIOS["lineas"]

    def test_dentro_del_horario(self):
        self.assertTrue(frecuencias.en_servicio(self.H, "FIJA", "LV", 9 * 60))

    def test_despues_del_ultimo_bus(self):
        # A las 23:40 la linea ya ha terminado: no es que falte el dato.
        self.assertFalse(frecuencias.en_servicio(self.H, "FIJA", "LV", 23 * 60 + 40))

    def test_antes_del_primero(self):
        self.assertFalse(frecuencias.en_servicio(self.H, "FIJA", "LV", 6 * 60))

    def test_sin_horario_no_se_sabe(self):
        # None no es False: una cosa es que no pase y otra que no conste.
        self.assertIsNone(frecuencias.en_servicio(self.H, "NO_EXISTE", "LV", 9 * 60))
        self.assertIsNone(frecuencias.en_servicio({}, "FIJA", "LV", 9 * 60))


if __name__ == "__main__":
    unittest.main()
