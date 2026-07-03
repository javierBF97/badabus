import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from badabus import bus_data_api as api

HOST = "127.0.0.1"
PORT = 8000
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILES = {"paradas.json", "lineas.json", "red.json"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/parada/"):
            self.handle_tiempos(path.removeprefix("/api/parada/"))
        elif path.startswith("/data/"):
            self.handle_data(path.removeprefix("/data/"))
        else:
            self.fail(404, "no encontrado")

    def handle_data(self, name: str) -> None:
        if name not in DATA_FILES:
            self.fail(404, "no encontrado")
            return
        try:
            body = (DATA_DIR / name).read_bytes()
        except OSError:
            self.fail(404, "no encontrado")
            return
        self.send_json(200, body)

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
        self.send_json(200, body)

    def send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_json(status, body)

    def reject(self) -> None:
        self.fail(405, "metodo no permitido")

    do_POST = do_PUT = do_DELETE = do_PATCH = reject

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sirviendo en http://{HOST}:{PORT} (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
