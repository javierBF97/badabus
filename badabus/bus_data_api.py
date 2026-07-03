import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

BUS_API_BASE = "https://tubasa.autobus.cloud/tiemposdellegada/api/"
FETCH_MAX_BYTES = 5_000_000


def fetch(url: str, timeout: int = 10) -> bytes:
    """GET sencillo que devuelve bytes (con un tope defensivo de tamaño)."""
    req = urllib.request.Request(url, headers={"User-Agent": "badabus/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(FETCH_MAX_BYTES)


def fetch_json(action: str, fetcher: Callable[..., bytes] = fetch, **params) -> list[dict]:
    """Consulta la API JSON del servicio y devuelve el array 'data'. Lanza si falta 'ok'/'data'."""
    query = urlencode({"action": action, **params})
    payload = json.loads(fetcher(f"{BUS_API_BASE}?{query}"))
    if not payload.get("ok"):
        raise ValueError(f"la API respondió ok=false para action={action}")
    if "data" not in payload:
        raise ValueError(f"la API no devolvió 'data' para action={action}")
    return payload["data"]


def parse_tiempos(data: list[dict]) -> list[dict]:
    """De la respuesta de action=tiempos a llegadas con los metros como entero (o None)."""
    return [
        {"linea": row["linea"], "metros": metros_de(row["distancia"]), "tiempo": row["tiempo"]}
        for row in data
    ]


def metros_de(distancia: str | None) -> int | None:
    """'21795m' -> 21795; '0m' -> 0; None o no numérico -> None."""
    try:
        return int(str(distancia).rstrip("m").strip())
    except (ValueError, TypeError):
        return None
