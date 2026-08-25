import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from badabus import bus_data_api, server


class TestServer(unittest.TestCase):
    def setUp(self):
        self._orig_fetch_json = bus_data_api.fetch_json
        self._orig_data_dir = server.DATA_DIR
        self._orig_web_dir = server.WEB_DIR
        self._tmp = tempfile.TemporaryDirectory()
        Path(self._tmp.name, "lineas.json").write_text('{"M2": {"color": "#DF3A01"}}', encoding="utf-8")
        Path(self._tmp.name, "dias.json").write_text('{"LV": ["A"], "SAB": []}', encoding="utf-8")
        Path(self._tmp.name, "index.html").write_text(
            "<!doctype html><html><body>ok</body></html>", encoding="utf-8"
        )
        Path(self._tmp.name, "app.js").write_text("// app", encoding="utf-8")
        Path(self._tmp.name, "styles.css").write_text("/* css */", encoding="utf-8")
        server.DATA_DIR = Path(self._tmp.name)
        server.WEB_DIR = Path(self._tmp.name)
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        bus_data_api.fetch_json = self._orig_fetch_json
        server.DATA_DIR = self._orig_data_dir
        server.WEB_DIR = self._orig_web_dir
        self._tmp.cleanup()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_tiempos_ok(self):
        bus_data_api.fetch_json = lambda action, **kw: [
            {"linea": "LÍNEA M2", "distancia": "21795m", "tiempo": "72 Minutos."}
        ]
        status, body = self.get("/api/parada/202")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [
            {"linea": "LÍNEA M2", "metros": 21795, "tiempo": "72 Minutos."}
        ])

    def test_tiempos_invalid_id(self):
        status, _ = self.get("/api/parada/abc")
        self.assertEqual(status, 400)

    def test_tiempos_upstream_error(self):
        def boom(action, **kw):
            raise OSError("caido")
        bus_data_api.fetch_json = boom
        with contextlib.redirect_stdout(io.StringIO()):
            status, _ = self.get("/api/parada/202")
        self.assertEqual(status, 502)

    def test_data_allowed(self):
        status, body = self.get("/data/lineas.json")
        self.assertEqual(status, 200)
        self.assertIn("M2", json.loads(body))

    def test_data_not_allowlisted(self):
        status, _ = self.get("/data/secret.json")
        self.assertEqual(status, 404)

    def test_unknown_path(self):
        status, _ = self.get("/nope")
        self.assertEqual(status, 404)

    def test_serves_index_at_root(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("html", body.decode("utf-8"))

    def test_serves_asset(self):
        status, _ = self.get("/app.js")
        self.assertEqual(status, 200)

    def test_unknown_asset_404(self):
        status, _ = self.get("/evil.js")
        self.assertEqual(status, 404)

    def test_data_traversal_blocked(self):
        status, _ = self.get("/data/..%2f..%2fserver.py")
        self.assertEqual(status, 404)

    def test_data_existing_but_not_allowlisted(self):
        status, _ = self.get("/data/app.js")
        self.assertEqual(status, 404)

    def test_plan_ok(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        try:
            status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"rutas": [[{"linea": "A", "subir": "1", "bajar": "3"}]]})

    def test_plan_invalid_ids(self):
        status, _ = self.get("/api/plan?origen=abc&destino=3")
        self.assertEqual(status, 400)

    def test_plan_missing_params(self):
        status, _ = self.get("/api/plan?origen=1")
        self.assertEqual(status, 400)

    def test_plan_upstream_error(self):
        def boom(*a, **kw):
            raise OSError("sin datos")
        original = server.planner.cargar_datos
        server.planner.cargar_datos = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = original
        self.assertEqual(status, 502)

    def test_plan_malformed_data(self):
        # dias que no es dict (fichero corrupto) -> 502 limpio, no 500 con traza.
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        server.planner.cargar_datos = lambda *a, **kw: ({"A": ["1", "2", "3"]}, [])
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
        self.assertEqual(status, 502)

    def test_plan_sin_dia_usa_el_calendario(self):
        # Si el servicio no responde, el planificador sigue dando rutas.
        red = {"A": ["1", "2", "3"]}
        dias = {tipo: ["A"] for tipo in ("LV", "SAB", "DOM")}
        def boom(*a, **kw):
            raise OSError("caido")
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"rutas": [[{"linea": "A", "subir": "1", "bajar": "3"}]]})

    def test_dia_ok(self):
        original = server.dia.tipo_dia_actual
        server.dia.tipo_dia_actual = lambda *a, **kw: ("SAB", "Horario Sábado")
        try:
            status, body = self.get("/api/dia")
        finally:
            server.dia.tipo_dia_actual = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"tipo_dia": "SAB", "etiqueta": "Horario Sábado"})

    def test_dia_upstream_error(self):
        def boom(*a, **kw):
            raise OSError("caido")
        original = server.dia.tipo_dia_actual
        server.dia.tipo_dia_actual = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = self.get("/api/dia")
        finally:
            server.dia.tipo_dia_actual = original
        self.assertEqual(status, 502)

    def test_data_dias_allowed(self):
        status, body = self.get("/data/dias.json")
        self.assertEqual(status, 200)
        self.assertIn("LV", json.loads(body))


if __name__ == "__main__":
    unittest.main()
