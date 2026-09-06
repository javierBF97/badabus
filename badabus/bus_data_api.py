import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

BUS_API_BASE = "https://tubasa.autobus.cloud/tiemposdellegada/api/"
FETCH_MAX_BYTES = 5_000_000
SHAPES_BASE = "https://tubasa.eu/planos_de_lineas/datos/"


def fetch(url: str, timeout: int = 10) -> bytes:
    """A plain GET that returns bytes, with a defensive size limit."""
    req = urllib.request.Request(url, headers={"User-Agent": "badabus/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(FETCH_MAX_BYTES)


def fetch_json(action: str, fetcher: Callable[..., bytes] = fetch, **params) -> list[dict]:
    """Queries the JSON API of the service and returns the 'data' array. Raises if 'ok' or 'data' is missing."""
    query = urlencode({"action": action, **params})
    payload = json.loads(fetcher(f"{BUS_API_BASE}?{query}"))
    if not payload.get("ok"):
        raise ValueError(f"the API answered ok=false for action={action}")
    if "data" not in payload:
        raise ValueError(f"the API returned no 'data' for action={action}")
    return payload["data"]


def fetch_shape(shape_id: str, fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Downloads the geometry (shape) of a line and returns the raw array of points."""
    data = json.loads(fetcher(f"{SHAPES_BASE}shape{shape_id}.json"))
    if not isinstance(data, list):
        raise ValueError(f"shape{shape_id}.json: expected an array, not {type(data).__name__}")
    return data


def _correspondencias(linea_id: str, fetcher: Callable[..., bytes]) -> dict:
    """Raw response of the connections endpoint for one line."""
    query = urlencode({"action": "correspondencias", "linea": linea_id})
    payload = json.loads(fetcher(f"{BUS_API_BASE}?{query}"))
    if not payload.get("ok"):
        raise ValueError(f"the API answered ok=false for correspondencias linea={linea_id}")
    return payload


def fetch_correspondencias(
    linea_id: str, fetcher: Callable[..., bytes] = fetch
) -> tuple[str, dict]:
    """From the connections endpoint of one line: (current day type, data per day type).

    data = {"LV": {stop_code: "L11,L13,..."} | [], "SAB": ..., "DOM": ...}.
    A line that does not run on a day brings that day as an empty list, not a dict.
    """
    payload = _correspondencias(linea_id, fetcher)
    return payload.get("current_tipo_dia", ""), payload.get("data", {})


def fetch_dia(linea_id: str, fetcher: Callable[..., bytes] = fetch) -> tuple[str, str]:
    """The current day type and its label, for example ("LV", "Horario L - V")."""
    payload = _correspondencias(linea_id, fetcher)
    return payload.get("current_tipo_dia", ""), payload.get("etiqueta_dia", "")


def parse_tiempos(data: list[dict]) -> list[dict]:
    """From the action=tiempos response to arrivals with the metres as an integer, or None."""
    return [
        {"linea": row["linea"], "metros": metros_de(row["distancia"]), "tiempo": row["tiempo"]}
        for row in data
    ]


def parse_shape(puntos: list[dict]) -> dict[str, list[list[float]]]:
    """Groups the shape points by direction: {'1': [[lat,lon],...], '2': [...]}, in order."""
    por_sentido: dict[str, list[list[float]]] = {}
    for p in puntos:
        por_sentido.setdefault(p["sentido"], []).append(
            [float(p["shape_pt_lat"]), float(p["shape_pt_lon"])]
        )
    return por_sentido


def metros_de(distancia: str | None) -> int | None:
    """'21795m' -> 21795; '0m' -> 0; None or not numeric -> None."""
    try:
        return int(str(distancia).rstrip("m").strip())
    except (ValueError, TypeError):
        return None
