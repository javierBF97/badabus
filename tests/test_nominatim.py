import json
import unittest

from badabus import nominatim

BUSQUEDA = json.dumps([
    {"lat": "38.8777796", "lon": "-6.9735163",
     "display_name": "12, Calle Menacho, Santo Domingo, Badajoz, Extremadura, 06001, España"},
    {"lat": "38.8783607", "lon": "-6.9702144",
     "display_name": "Plaza de España, Casco Antiguo, Badajoz, Extremadura, España"},
]).encode("utf-8")

INVERSO = json.dumps({
    "display_name": "12, Calle Menacho, Santo Domingo, Badajoz, Extremadura, 06001, España"
}).encode("utf-8")


class TestBuscar(unittest.TestCase):
    def test_devuelve_nombre_y_coordenadas(self):
        def fake(url, timeout=10):
            return BUSQUEDA
        salida = nominatim.buscar("Calle Menacho 12", fetcher=fake)
        self.assertEqual(len(salida), 2)
        self.assertEqual(salida[0]["lat"], 38.8777796)
        self.assertEqual(salida[0]["lon"], -6.9735163)
        self.assertIn("Calle Menacho", salida[0]["nombre"])

    def test_acota_la_busqueda_a_badajoz(self):
        visto = {}
        def fake(url, timeout=10):
            visto["url"] = url
            return b"[]"
        nominatim.buscar("algo", fetcher=fake)
        self.assertIn("viewbox=", visto["url"])
        self.assertIn("bounded=1", visto["url"])
        self.assertIn("countrycodes=es", visto["url"])
        self.assertIn("q=algo", visto["url"])

    def test_sin_resultados(self):
        def fake(url, timeout=10):
            return b"[]"
        self.assertEqual(nominatim.buscar("nada de nada", fetcher=fake), [])

    def test_texto_vacio_no_consulta(self):
        def fake(url, timeout=10):
            raise AssertionError("no debería consultarse")
        self.assertEqual(nominatim.buscar("   ", fetcher=fake), [])

    def test_ignora_resultados_sin_coordenadas(self):
        def fake(url, timeout=10):
            return b'[{"display_name": "Sitio raro"}]'
        self.assertEqual(nominatim.buscar("x", fetcher=fake), [])


class TestDireccion(unittest.TestCase):
    def test_devuelve_el_nombre(self):
        def fake(url, timeout=10):
            return INVERSO
        self.assertIn("Calle Menacho", nominatim.direccion(38.87, -6.97, fetcher=fake))

    def test_pasa_las_coordenadas(self):
        visto = {}
        def fake(url, timeout=10):
            visto["url"] = url
            return INVERSO
        nominatim.direccion(38.87, -6.97, fetcher=fake)
        self.assertIn("lat=38.87", visto["url"])
        self.assertIn("lon=-6.97", visto["url"])

    def test_sin_nombre_devuelve_cadena_vacia(self):
        def fake(url, timeout=10):
            return b'{"error": "Unable to geocode"}'
        self.assertEqual(nominatim.direccion(0.0, 0.0, fetcher=fake), "")


if __name__ == "__main__":
    unittest.main()
