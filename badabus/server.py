import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from badabus import bus_data_api as api
from badabus import dia, nominatim, planner, ranking

HOST = "127.0.0.1"
PORT = 8000
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
DATA_FILES = {"paradas.json", "lineas.json", "red.json", "shapes.json", "dias.json"}
ENV_FILE = BASE_DIR / ".env"
WEB_FILES = {"index.html", "app.js", "styles.css"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/parada/"):
            self.handle_tiempos(path.removeprefix("/api/parada/"))
        elif path == "/api/plan":
            self.handle_plan()
        elif path == "/api/dia":
            self.handle_dia()
        elif path == "/api/config":
            self.handle_config()
        elif path == "/api/buscar":
            self.handle_buscar()
        elif path == "/api/direccion":
            self.handle_direccion()
        elif path.startswith("/data/"):
            self.handle_static(path.removeprefix("/data/"), DATA_DIR, DATA_FILES)
        elif path == "/":
            self.handle_static("index.html", WEB_DIR, WEB_FILES)
        elif path.lstrip("/") in WEB_FILES:
            self.handle_static(path.lstrip("/"), WEB_DIR, WEB_FILES)
        else:
            self.fail(404, "no encontrado")

    def handle_static(self, name: str, directory: Path, allowed: set[str]) -> None:
        if name not in allowed:
            self.fail(404, "no encontrado")
            return
        try:
            body = (directory / name).read_bytes()
        except OSError:
            self.fail(404, "no encontrado")
            return
        content_type = CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")
        self.send_bytes(200, body, content_type)

    def handle_tiempos(self, stop_id: str) -> None:
        if not stop_id.isdigit():
            self.fail(400, "id de parada invalido")
            return
        try:
            data = api.fetch_json("tiempos", parada=stop_id)
            body = json.dumps(api.parse_tiempos(data), ensure_ascii=False).encode("utf-8")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"  ! error consultando tiempos de {stop_id}: {exc}")
            self.fail(502, "no se pudo consultar el servicio")
            return
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def handle_plan(self) -> None:
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(query)
        origen = (params.get("origen") or [""])[0]
        destino = (params.get("destino") or [""])[0]
        if not origen.isdigit() or not destino.isdigit():
            self.fail(400, "origen y destino deben ser ids de parada")
            return
        try:
            red, dias = planner.cargar_datos()
            try:
                tipo, _ = dia.tipo_dia_actual()
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                print(f"  ! no se pudo consultar el tipo de día, uso el calendario: {exc}")
                tipo = dia.tipo_dia_local()
            activas = dias.get(tipo) or {lin for lins in dias.values() for lin in lins}
            rutas = planner.planificar(origen, destino, red, activas)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            print(f"  ! error planificando {origen}->{destino}: {exc}")
            self.fail(502, "no se pudo calcular la ruta")
            return
        # Enriquecido best-effort: si falla el dato en vivo o las coordenadas, se devuelve igual.
        try:
            tiempos = api.parse_tiempos(api.fetch_json("tiempos", parada=origen))
            esperas = ranking.esperas_por_linea(tiempos)
        except (OSError, ValueError, KeyError, TypeError):
            esperas = {}
        try:
            paradas = ranking.cargar_paradas()
        except (OSError, ValueError):
            paradas = {}
        try:
            rutas = ranking.puntuar(rutas, red, paradas, esperas)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            # Un fallo puntuando no debe esconder rutas: se devuelven sin estimar.
            print(f"  ! error puntuando las rutas: {exc}")
            rutas = [
                {"tramos": ruta, "viaje_min": None, "espera_min": None}
                for ruta in rutas[:ranking.LIMITE_RUTAS]
            ]
        body = json.dumps({"rutas": rutas}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def handle_dia(self) -> None:
        try:
            tipo, etiqueta = dia.tipo_dia_actual()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            print(f"  ! error consultando el tipo de día: {exc}")
            self.fail(502, "no se pudo consultar el tipo de día")
            return
        body = json.dumps({"tipo_dia": tipo, "etiqueta": etiqueta}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def handle_config(self) -> None:
        """Ajustes que el navegador necesita y no viven en el código, como la clave del mapa."""
        # Se pasa el fichero explícitamente: por defecto quedaría fijado al importar.
        clave = leer_env(ENV_FILE).get("CARTO_API_KEY", "")
        body = json.dumps({"carto_key": clave}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def handle_buscar(self) -> None:
        """Direcciones que coinciden con el texto, para el buscador de origen y destino."""
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        texto = (parse_qs(query).get("q") or [""])[0]
        if not texto.strip():
            self.send_bytes(200, b"[]", "application/json; charset=utf-8")
            return
        try:
            sitios = nominatim.buscar(texto)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"  ! error buscando la dirección {texto!r}: {exc}")
            self.fail(502, "no se pudo buscar la dirección")
            return
        body = json.dumps(sitios, ensure_ascii=False).encode("utf-8")
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def handle_direccion(self) -> None:
        """Nombre del sitio que hay en unas coordenadas, para los clics en el mapa."""
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(query)
        try:
            lat = float((params.get("lat") or [""])[0])
            lon = float((params.get("lon") or [""])[0])
        except ValueError:
            self.fail(400, "lat y lon deben ser números")
            return
        try:
            nombre = nominatim.direccion(lat, lon)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Sin nombre la ruta se calcula igual: no merece un error.
            print(f"  ! no se pudo nombrar el punto {lat},{lon}: {exc}")
            nombre = ""
        body = json.dumps({"nombre": nombre}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(200, body, "application/json; charset=utf-8")

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def reject(self) -> None:
        self.fail(405, "metodo no permitido")

    do_POST = do_PUT = do_DELETE = do_PATCH = reject

    def log_message(self, format: str, *args) -> None:
        pass


def leer_env(ruta: Path = ENV_FILE) -> dict[str, str]:
    """Lee un .env sencillo (CLAVE=valor por línea). Si no existe, devuelve {}."""
    valores: dict[str, str] = {}
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return valores
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sirviendo en http://{HOST}:{PORT} (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
