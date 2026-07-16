import unittest

from badabus import bus_data_api as api


class TestFetchJson(unittest.TestCase):
    def test_returns_data_on_ok(self):
        def fake(url, timeout=10):
            assert "action=lineas" in url
            return b'{"ok":true,"data":[{"lin":"2"}]}'
        self.assertEqual(api.fetch_json("lineas", fetcher=fake), [{"lin": "2"}])

    def test_passes_params_in_url(self):
        seen = {}
        def fake(url, timeout=10):
            seen["url"] = url
            return b'{"ok":true,"data":[]}'
        api.fetch_json("paradas", fetcher=fake, linea="TRIP_100007")
        self.assertIn("action=paradas", seen["url"])
        self.assertIn("linea=TRIP_100007", seen["url"])

    def test_raises_when_not_ok(self):
        def fake(url, timeout=10):
            return b'{"ok":false}'
        with self.assertRaises(ValueError):
            api.fetch_json("lineas", fetcher=fake)

    def test_raises_when_ok_but_no_data(self):
        def fake(url, timeout=10):
            return b'{"ok":true}'
        with self.assertRaises(ValueError):
            api.fetch_json("lineas", fetcher=fake)


class TestParseTiempos(unittest.TestCase):
    def test_maps_and_parses_meters(self):
        data = [
            {"linea": "LÍNEA M2", "distancia": "21795m", "tiempo": "72 Minutos."},
            {"linea": "LÍNEA CA", "distancia": "0m", "tiempo": "Próximo."},
        ]
        self.assertEqual(api.parse_tiempos(data), [
            {"linea": "LÍNEA M2", "metros": 21795, "tiempo": "72 Minutos."},
            {"linea": "LÍNEA CA", "metros": 0, "tiempo": "Próximo."},
        ])

    def test_non_numeric_meters_is_none(self):
        self.assertIsNone(api.parse_tiempos([{"linea": "L5", "distancia": "-", "tiempo": "x"}])[0]["metros"])

    def test_none_meters_is_none(self):
        self.assertIsNone(api.parse_tiempos([{"linea": "L5", "distancia": None, "tiempo": "x"}])[0]["metros"])

    def test_empty(self):
        self.assertEqual(api.parse_tiempos([]), [])


class TestFetchShape(unittest.TestCase):
    def test_builds_url_and_returns_array(self):
        seen = {}
        def fake(url, timeout=10):
            seen["url"] = url
            return b'[{"shape_pt_lat":"38.8","shape_pt_lon":"-6.9","sentido":"1"}]'
        out = api.fetch_shape("TRIP_100007", fetcher=fake)
        self.assertIn("shapeTRIP_100007.json", seen["url"])
        self.assertEqual(out, [{"shape_pt_lat": "38.8", "shape_pt_lon": "-6.9", "sentido": "1"}])

    def test_raises_when_not_a_list(self):
        def fake(url, timeout=10):
            return b'{"error":"not found"}'
        with self.assertRaises(ValueError):
            api.fetch_shape("X", fetcher=fake)


class TestParseShape(unittest.TestCase):
    def test_groups_by_sentido_in_order(self):
        puntos = [
            {"shape_pt_lat": "38.1", "shape_pt_lon": "-6.1", "sentido": "1"},
            {"shape_pt_lat": "38.2", "shape_pt_lon": "-6.2", "sentido": "1"},
            {"shape_pt_lat": "38.9", "shape_pt_lon": "-6.9", "sentido": "2"},
        ]
        self.assertEqual(api.parse_shape(puntos), {
            "1": [[38.1, -6.1], [38.2, -6.2]],
            "2": [[38.9, -6.9]],
        })


if __name__ == "__main__":
    unittest.main()
