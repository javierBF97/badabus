import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

API_BASE = "https://tubasa.autobus.cloud/tiemposdellegada/api/"


def fetch(url: str, timeout: int = 10) -> bytes:
    """GET sencillo que devuelve bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": "badabus/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json(action: str, fetch: Callable[..., bytes] = fetch, **params) -> list[dict]:
    """Consulta la API JSON del servicio y devuelve el array 'data'. Lanza si falta 'ok'/'data'."""
    query = urlencode({"action": action, **params})
    payload = json.loads(fetch(f"{API_BASE}?{query}"))
    if not payload.get("ok"):
        raise ValueError(f"la API respondió ok=false para action={action}")
    if "data" not in payload:
        raise ValueError(f"la API no devolvió 'data' para action={action}")
    return payload["data"]
