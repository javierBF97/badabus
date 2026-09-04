import json
import unittest

from badabus import geocoder

PHOTON_CALLE = {
    "features": [{
        "geometry": {"coordinates": [-6.9737, 38.8777]},
        "properties": {"housenumber": "12", "street": "Calle Menacho", "city": "Badajoz"},
    }]
}
PHOTON_VACIO = {"features": []}
CARTO_PORTAL = [{"address": "CALLE MENACHO 12", "muni": "Badajoz",
                 "lat": 38.8777, "lng": -6.9737, "type": "portal"}]


def responde(*respuestas):
    """Un fetcher que devuelve cada respuesta en orden, y anota las urls pedidas."""
    pendientes = list(respuestas)
    pedidas = []

    def fake(url, **kw):
        pedidas.append(url)
        if not pendientes:
            raise AssertionError(f"peticion de mas: {url}")
        siguiente = pendientes.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return json.dumps(siguiente).encode("utf-8")

    fake.pedidas = pedidas
    return fake


class TestBuscar(unittest.TestCase):
    def test_usa_photon_y_no_pregunta_a_nadie_mas(self):
        fake = responde(PHOTON_CALLE)
        salida = geocoder.buscar("Menacho 12", fetcher=fake)
        self.assertEqual(salida, [{"nombre": "Calle Menacho 12, Badajoz",
                                   "lat": 38.8777, "lon": -6.9737}])
        self.assertEqual(len(fake.pedidas), 1)
        self.assertIn("photon", fake.pedidas[0])

    def test_acota_a_badajoz(self):
        # Sin recuadro, una avenida con nombre de ciudad portuguesa se va a Portugal.
        fake = responde(PHOTON_CALLE)
        geocoder.buscar("Avenida de Elvas", fetcher=fake)
        self.assertIn("bbox", fake.pedidas[0])

    def test_si_photon_no_encuentra_pregunta_a_cartociudad(self):
        fake = responde(PHOTON_VACIO, CARTO_PORTAL)
        salida = geocoder.buscar("Menacho 12", fetcher=fake)
        self.assertEqual(salida[0]["nombre"], "CALLE MENACHO 12, Badajoz")
        self.assertEqual(len(fake.pedidas), 2)
        self.assertIn("cartociudad", fake.pedidas[1])

    def test_si_photon_falla_tambien_se_cae_al_segundo(self):
        fake = responde(OSError("photon caido"), CARTO_PORTAL)
        self.assertEqual(len(geocoder.buscar("Menacho", fetcher=fake)), 1)

    def test_si_fallan_los_dos_no_revienta(self):
        fake = responde(OSError("uno"), OSError("dos"))
        self.assertEqual(geocoder.buscar("Menacho", fetcher=fake), [])

    def test_no_repite_la_misma_calle(self):
        # Photon devuelve varios tramos del mismo vial; en la lista sobran.
        tres = {"features": [{
            "geometry": {"coordinates": [-6.98 - i / 1000, 38.86]},
            "properties": {"street": "Paseo Condes de Barcelona", "city": "Badajoz"},
        } for i in range(3)]}
        fake = responde(tres)
        self.assertEqual(len(geocoder.buscar("Condes", fetcher=fake)), 1)

    def test_texto_vacio_no_pregunta(self):
        fake = responde()
        self.assertEqual(geocoder.buscar("   ", fetcher=fake), [])
        self.assertEqual(fake.pedidas, [])

    def test_ignora_resultados_sin_coordenadas(self):
        fake = responde({"features": [{"geometry": {}, "properties": {"name": "X"}}]},
                        [])
        self.assertEqual(geocoder.buscar("algo", fetcher=fake), [])

    def test_sin_numero_el_nombre_es_solo_la_calle(self):
        fake = responde({"features": [{
            "geometry": {"coordinates": [-6.98, 38.87]},
            "properties": {"street": "Avenida Sinforiano Madronero", "city": "Badajoz"},
        }]})
        self.assertEqual(geocoder.buscar("Sinforiano", fetcher=fake)[0]["nombre"],
                         "Avenida Sinforiano Madronero, Badajoz")


class TestDireccion(unittest.TestCase):
    def test_inversa_por_photon(self):
        fake = responde(PHOTON_CALLE)
        self.assertEqual(geocoder.direccion(38.8777, -6.9737, fetcher=fake),
                         "Calle Menacho 12, Badajoz")

    def test_inversa_cae_a_cartociudad(self):
        fake = responde(PHOTON_VACIO, {"address": "CALLE MENACHO", "muni": "Badajoz"})
        self.assertEqual(geocoder.direccion(38.8777, -6.9737, fetcher=fake),
                         "CALLE MENACHO, Badajoz")

    def test_sin_respuesta_devuelve_vacio(self):
        fake = responde(PHOTON_VACIO, {})
        self.assertEqual(geocoder.direccion(0.0, 0.0, fetcher=fake), "")


if __name__ == "__main__":
    unittest.main()
