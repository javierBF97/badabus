import contextlib
import io
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
    if "shape002_A.json" in url:
        return b'[{"shape_pt_lat":"38.87","shape_pt_lon":"-6.97","sentido":"1"}]'
    if "shapeTRIP_100007.json" in url:
        return (
            b'[{"shape_pt_lat":"38.82","shape_pt_lon":"-6.92","sentido":"1"},'
            b'{"shape_pt_lat":"38.80","shape_pt_lon":"-6.90","sentido":"2"}]'
        )
    raise AssertionError("url inesperada: " + url)


class TestCollect(unittest.TestCase):
    def test_builds_stops_meta_and_red(self):
        stops, meta, red, shapes = collector.collect(fetcher=fake)
        by_id = {s["id"]: s for s in stops}
        self.assertEqual(sorted(by_id), ["1844", "202"])
        self.assertEqual(by_id["202"]["lineas"], ["2", "M2"])
        self.assertEqual(by_id["1844"]["lineas"], ["M2"])
        self.assertEqual(meta["M2"], {"color": "#f58322", "nombre": "Campomanes"})
        self.assertEqual(red["M2"], ["1844", "202"])
        self.assertEqual(red["2"], ["202"])
        self.assertEqual(shapes["M2"], {"1": [[38.82, -6.92]], "2": [[38.8, -6.9]]})
        self.assertEqual(shapes["2"], {"1": [[38.87, -6.97]]})

    def test_natural_key_orders_lines(self):
        names = ["M2", "2", "11", "C1", "9F", "9"]
        self.assertEqual(sorted(names, key=collector.natural_key), ["2", "9", "9F", "11", "C1", "M2"])

    def test_natural_key_empty_sorts_last(self):
        self.assertEqual(sorted(["M2", "", "2"], key=collector.natural_key), ["2", "M2", ""])

    def test_parada_valida(self):
        ok = {"stop_code": "1", "stop_name": "X", "lat": "38.8", "lon": "-6.9", "secuencia": "2"}
        self.assertTrue(collector.parada_valida(ok))
        self.assertFalse(collector.parada_valida({**ok, "lat": "abc"}))
        self.assertFalse(collector.parada_valida({"stop_code": "1"}))

    def test_skips_invalid_stops(self):
        paradas_mixtas = (
            b'{"ok":true,"data":['
            b'{"stop_code":"1","stop_name":"Buena","lat":"38.8","lon":"-6.9","sentido":"1","secuencia":"1"},'
            b'{"stop_code":"2","stop_name":"Mala","lat":"nan?","lon":"-6.9","sentido":"1","secuencia":"2"}]}'
        )

        def fake_mixto(url, timeout=10):
            if "action=lineas" in url:
                return LINEAS
            return paradas_mixtas

        with contextlib.redirect_stdout(io.StringIO()):
            stops, _, red, _ = collector.collect(fetcher=fake_mixto)
        ids = {s["id"] for s in stops}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)
        self.assertEqual(red["2"], ["1"])

    def test_shape_malformado_no_aborta(self):
        def fake_shape_malo(url, timeout=10):
            if "action=lineas" in url:
                return LINEAS
            if "action=paradas" in url and "linea=002_A" in url:
                return PARADAS_2
            if "action=paradas" in url and "linea=TRIP_100007" in url:
                return PARADAS_M2
            if "shape002_A.json" in url:
                return b'[{"shape_pt_lat":"38.87","shape_pt_lon":"-6.97","sentido":"1"}]'
            if "shapeTRIP_100007.json" in url:
                return b'[{"falta":"claves"}]'
            raise AssertionError("url inesperada: " + url)

        with contextlib.redirect_stdout(io.StringIO()):
            stops, meta, red, shapes = collector.collect(fetcher=fake_shape_malo)
        self.assertEqual(sorted({s["id"] for s in stops}), ["1844", "202"])
        self.assertEqual(sorted(red), ["2", "M2"])
        self.assertIn("2", shapes)
        self.assertNotIn("M2", shapes)

    def test_recolectar_dias(self):
        # M2 circula LV pero no SAB; la línea 2 solo circula SAB.
        def fake_corr(url, timeout=10):
            if "action=lineas" in url:
                return LINEAS
            if "action=correspondencias" in url and "linea=TRIP_100007" in url:
                return (
                    b'{"ok":true,"current_tipo_dia":"LV","data":'
                    b'{"LV":{"202":"L11"},"SAB":[],"DOM":[]}}'
                )
            if "action=correspondencias" in url and "linea=002_A" in url:
                return (
                    b'{"ok":true,"current_tipo_dia":"LV","data":'
                    b'{"LV":[],"SAB":{"202":""},"DOM":[]}}'
                )
            raise AssertionError("url inesperada: " + url)

        out = collector.recolectar_dias(fetcher=fake_corr)
        self.assertEqual(out, {"LV": ["M2"], "SAB": ["2"], "DOM": []})

    def test_recolectar_dias_error_no_aborta(self):
        def fake_corr(url, timeout=10):
            if "action=lineas" in url:
                return LINEAS
            if "linea=TRIP_100007" in url:
                return b'{"ok":true,"current_tipo_dia":"LV","data":{"LV":{"202":"L4"}}}'
            raise OSError("caido")

        with contextlib.redirect_stdout(io.StringIO()):
            out = collector.recolectar_dias(fetcher=fake_corr)
        self.assertEqual(out, {"LV": ["M2"]})

    def test_save_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "data", "x.json")
            collector.save_json({"a": 1}, p)
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.loads(f.read()), {"a": 1})


if __name__ == "__main__":
    unittest.main()
