import json
import os
import tempfile
import unittest

from badabus import collector

LINEAS = (
    b'{"ok":true,"data":['
    b'{"id":"002_A","lin":"2","nombre":"LINEA 2","descripcion":"Ruta 2",'
    b'"color_fondo":"696969","color_texto":"000000","orden":"1"},'
    b'{"id":"TRIP_100007","lin":"M2","nombre":"LINEA M2","descripcion":"Campomanes",'
    b'"color_fondo":"f58322","color_texto":"000000","orden":"14"}]}'
)
PARADAS_2 = (
    b'{"ok":true,"data":['
    b'{"stop_code":"202","stop_name":"Plaza","lat":"38.87","lon":"-6.97","sentido":"1","secuencia":"1"}]}'
)
PARADAS_M2 = (
    b'{"ok":true,"data":['
    b'{"stop_code":"1844","stop_name":"Campomane","lat":"38.82","lon":"-6.92","sentido":"1","secuencia":"2"},'
    b'{"stop_code":"202","stop_name":"Plaza","lat":"38.87","lon":"-6.97","sentido":"1","secuencia":"5"}]}'
)


def fake(url, timeout=10):
    if "action=lineas" in url:
        return LINEAS
    if "action=paradas" in url and "linea=002_A" in url:
        return PARADAS_2
    if "action=paradas" in url and "linea=TRIP_100007" in url:
        return PARADAS_M2
    raise AssertionError("url inesperada: " + url)


class TestCollect(unittest.TestCase):
    def test_builds_stops_meta_and_red(self):
        stops, meta, red = collector.collect(fetch=fake)
        by_id = {s["id"]: s for s in stops}
        self.assertEqual(sorted(by_id), ["1844", "202"])
        self.assertEqual(by_id["202"]["lineas"], ["2", "M2"])
        self.assertEqual(by_id["1844"]["lineas"], ["M2"])
        self.assertEqual(meta["M2"], {"color": "#f58322", "nombre": "Campomanes"})
        self.assertEqual(red["M2"], ["1844", "202"])
        self.assertEqual(red["2"], ["202"])

    def test_natural_key_orders_lines(self):
        names = ["M2", "2", "11", "C1", "9F", "9"]
        self.assertEqual(sorted(names, key=collector.natural_key), ["2", "9", "9F", "11", "C1", "M2"])

    def test_save_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "data", "x.json")
            collector.save_json({"a": 1}, p)
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.loads(f.read()), {"a": 1})


if __name__ == "__main__":
    unittest.main()
