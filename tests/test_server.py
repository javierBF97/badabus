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
        self._orig_cargar_paradas = server.ranking.cargar_paradas
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
        # Stubea por defecto para que ningún test toque la red ni el disco
        bus_data_api.fetch_json = lambda action, **kw: []
        server.ranking.cargar_paradas = lambda *a, **kw: {}
        self._orig_buscar = server.nominatim.buscar
        self._orig_direccion = server.nominatim.direccion
        server.nominatim.buscar = lambda *a, **kw: []
        server.nominatim.direccion = lambda *a, **kw: ""
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        server.ranking.cargar_paradas = self._orig_cargar_paradas
        server.nominatim.buscar = self._orig_buscar
        server.nominatim.direccion = self._orig_direccion
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

    def test_config_sin_env_devuelve_clave_vacia(self):
        original = server.ENV_FILE
        server.ENV_FILE = Path(self._tmp.name, "no-existe.env")
        try:
            status, body = self.get("/api/config")
        finally:
            server.ENV_FILE = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"carto_key": ""})

    def test_config_lee_la_clave_del_env(self):
        env = Path(self._tmp.name, ".env")
        env.write_text("# comentario\nCARTO_API_KEY=abc123\n", encoding="utf-8")
        original = server.ENV_FILE
        server.ENV_FILE = env
        try:
            status, body = self.get("/api/config")
        finally:
            server.ENV_FILE = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"carto_key": "abc123"})

    def test_leer_env_ignora_comentarios_lineas_sueltas_y_comillas(self):
        env = Path(self._tmp.name, "otro.env")
        env.write_text('# nota\n\nCARTO_API_KEY="con comillas"\nSUELTA\n', encoding="utf-8")
        self.assertEqual(server.leer_env(env), {"CARTO_API_KEY": "con comillas"})

    def test_buscar_devuelve_direcciones(self):
        original = server.nominatim.buscar
        server.nominatim.buscar = lambda texto, **kw: [
            {"nombre": "12, Calle Menacho, Badajoz", "lat": 38.87, "lon": -6.97}
        ]
        try:
            status, body = self.get("/api/buscar?q=menacho")
        finally:
            server.nominatim.buscar = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]["nombre"], "12, Calle Menacho, Badajoz")

    def test_buscar_sin_texto_devuelve_lista_vacia(self):
        status, body = self.get("/api/buscar")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])

    def test_buscar_con_el_servicio_caido(self):
        def boom(*a, **kw):
            raise OSError("caido")
        original = server.nominatim.buscar
        server.nominatim.buscar = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = self.get("/api/buscar?q=menacho")
        finally:
            server.nominatim.buscar = original
        self.assertEqual(status, 502)

    def test_direccion_devuelve_el_nombre(self):
        original = server.nominatim.direccion
        server.nominatim.direccion = lambda lat, lon, **kw: "12, Calle Menacho, Badajoz"
        try:
            status, body = self.get("/api/direccion?lat=38.87&lon=-6.97")
        finally:
            server.nominatim.direccion = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"nombre": "12, Calle Menacho, Badajoz"})

    def test_direccion_con_coordenadas_invalidas(self):
        status, _ = self.get("/api/direccion?lat=abc&lon=-6.97")
        self.assertEqual(status, 400)

    def test_direccion_con_el_servicio_caido(self):
        def boom(*a, **kw):
            raise OSError("caido")
        original = server.nominatim.direccion
        server.nominatim.direccion = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, body = self.get("/api/direccion?lat=38.87&lon=-6.97")
        finally:
            server.nominatim.direccion = original
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"nombre": ""})

    def test_plan_ok(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        paradas = {"1": (38.88, -6.97), "2": (38.88, -6.96), "3": (38.88, -6.95)}
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_fetch = bus_data_api.fetch_json
        orig_paradas = server.ranking.cargar_paradas
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        server.ranking.cargar_paradas = lambda *a, **kw: paradas
        bus_data_api.fetch_json = lambda action, **kw: [
            {"linea": "LÍNEA A", "distancia": "1000m", "tiempo": "5 Minutos."}
        ]
        try:
            status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            bus_data_api.fetch_json = orig_fetch
            server.ranking.cargar_paradas = orig_paradas
        self.assertEqual(status, 200)
        rutas = json.loads(body)["rutas"]
        self.assertEqual(rutas[0]["tramos"], [{"linea": "A", "subir": "1", "bajar": "3"}])
        self.assertEqual(rutas[0]["espera_min"], 5)
        self.assertIsNone(rutas[0]["andando_min"])

    def test_plan_con_coordenadas_de_origen(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        paradas = {"1": (38.88, -6.97), "2": (38.88, -6.96), "3": (38.88, -6.95)}
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_paradas = server.ranking.cargar_paradas
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        server.ranking.cargar_paradas = lambda *a, **kw: paradas
        try:
            status, body = self.get("/api/plan?origen_lat=38.8801&origen_lon=-6.9701&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            server.ranking.cargar_paradas = orig_paradas
        self.assertEqual(status, 200)
        rutas = json.loads(body)["rutas"]
        self.assertTrue(rutas, "debería encontrar ruta desde una parada cercana")
        self.assertIsInstance(rutas[0]["andando_min"], int)

    def test_plan_con_direccion_fuera_de_la_red(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        paradas = {"1": (38.88, -6.97), "2": (38.88, -6.96), "3": (38.88, -6.95)}
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_paradas = server.ranking.cargar_paradas
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        server.ranking.cargar_paradas = lambda *a, **kw: paradas
        try:
            status, body = self.get("/api/plan?origen_lat=40.0&origen_lon=-3.0&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            server.ranking.cargar_paradas = orig_paradas
        self.assertEqual(status, 200)
        datos = json.loads(body)
        self.assertEqual(datos["rutas"], [])
        self.assertEqual(datos["aviso"], "fuera de la red")

    def test_plan_con_coordenadas_invalidas(self):
        status, _ = self.get("/api/plan?origen_lat=abc&origen_lon=-6.97&destino=3")
        self.assertEqual(status, 400)

    def test_plan_sin_tiempos_espera_es_none(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        paradas = {"1": (38.88, -6.97), "2": (38.88, -6.96), "3": (38.88, -6.95)}
        def boom(*a, **kw):
            raise OSError("sin tiempos")
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_fetch = bus_data_api.fetch_json
        orig_paradas = server.ranking.cargar_paradas
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        server.ranking.cargar_paradas = lambda *a, **kw: paradas
        bus_data_api.fetch_json = boom
        try:
            status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            bus_data_api.fetch_json = orig_fetch
            server.ranking.cargar_paradas = orig_paradas
        self.assertEqual(status, 200)
        rutas = json.loads(body)["rutas"]
        self.assertIsNone(rutas[0]["espera_min"])
        self.assertIsInstance(rutas[0]["viaje_min"], int)

    def test_plan_sin_paradas_viaje_es_none(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_fetch = bus_data_api.fetch_json
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        bus_data_api.fetch_json = lambda action, **kw: []
        # cargar_paradas ya devuelve {} por el setUp
        try:
            status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            bus_data_api.fetch_json = orig_fetch
        self.assertEqual(status, 200)
        rutas = json.loads(body)["rutas"]
        self.assertEqual(rutas[0]["tramos"], [{"linea": "A", "subir": "1", "bajar": "3"}])
        self.assertIsNone(rutas[0]["viaje_min"])
        self.assertIsNone(rutas[0]["espera_min"])

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
        rutas = json.loads(body)["rutas"]
        self.assertEqual(len(rutas), 1)
        self.assertEqual(rutas[0]["tramos"], [{"linea": "A", "subir": "1", "bajar": "3"}])
        self.assertIsNone(rutas[0]["viaje_min"])
        self.assertIsNone(rutas[0]["espera_min"])
        self.assertIsNone(rutas[0].get("total_min"))
        self.assertIsNone(rutas[0].get("andando_min"))

    def test_plan_error_puntuando_devuelve_rutas_sin_estimar(self):
        red = {"A": ["1", "2", "3"]}
        dias = {"LV": ["A"]}
        def boom(*a, **kw):
            raise ValueError("ranking roto")
        orig_datos = server.planner.cargar_datos
        orig_dia = server.dia.tipo_dia_actual
        orig_puntuar = server.ranking.puntuar
        server.planner.cargar_datos = lambda *a, **kw: (red, dias)
        server.dia.tipo_dia_actual = lambda *a, **kw: ("LV", "Horario L - V")
        server.ranking.puntuar = boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status, body = self.get("/api/plan?origen=1&destino=3")
        finally:
            server.planner.cargar_datos = orig_datos
            server.dia.tipo_dia_actual = orig_dia
            server.ranking.puntuar = orig_puntuar
        self.assertEqual(status, 200)
        rutas = json.loads(body)["rutas"]
        self.assertEqual(rutas[0]["tramos"], [{"linea": "A", "subir": "1", "bajar": "3"}])
        self.assertIsNone(rutas[0]["viaje_min"])
        self.assertIsNone(rutas[0]["espera_min"])

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
