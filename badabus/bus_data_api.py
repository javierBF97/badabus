import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

BUS_API_BASE = "https://tubasa.autobus.cloud/tiemposdellegada/api/"
FETCH_MAX_BYTES = 5_000_000
SHAPES_BASE = "https://tubasa.eu/planos_de_lineas/datos/"


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


def fetch_shape(shape_id: str, fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Baja la geometría (shape) de una línea; devuelve el array crudo de puntos."""
    data = json.loads(fetcher(f"{SHAPES_BASE}shape{shape_id}.json"))
    if not isinstance(data, list):
        raise ValueError(f"shape{shape_id}.json: se esperaba un array, no {type(data).__name__}")
    return data


def _correspondencias(linea_id: str, fetcher: Callable[..., bytes]) -> dict:
    """Respuesta cruda del endpoint de correspondencias de una línea."""
    query = urlencode({"action": "correspondencias", "linea": linea_id})
    payload = json.loads(fetcher(f"{BUS_API_BASE}?{query}"))
    if not payload.get("ok"):
        raise ValueError(f"la API respondió ok=false para correspondencias linea={linea_id}")
    return payload


def fetch_correspondencias(
    linea_id: str, fetcher: Callable[..., bytes] = fetch
) -> tuple[str, dict]:
    """Del endpoint correspondencias de una línea: devuelve (tipo_dia_actual, data por tipo de día).

    data = {"LV": {stop_code: "L11,L13,..."} | [], "SAB": ..., "DOM": ...}.
    Una línea que no circula un día trae ese día como lista vacía en vez de dict.
    """
    payload = _correspondencias(linea_id, fetcher)
    return payload.get("current_tipo_dia", ""), payload.get("data", {})


def fetch_dia(linea_id: str, fetcher: Callable[..., bytes] = fetch) -> tuple[str, str]:
    """Tipo de día vigente y su etiqueta, p. ej. ("LV", "Horario L - V")."""
    payload = _correspondencias(linea_id, fetcher)
    return payload.get("current_tipo_dia", ""), payload.get("etiqueta_dia", "")


def parse_tiempos(data: list[dict]) -> list[dict]:
    """De la respuesta de action=tiempos a llegadas con los metros como entero (o None)."""
    return [
        {"linea": row["linea"], "metros": metros_de(row["distancia"]), "tiempo": row["tiempo"]}
        for row in data
    ]


def parse_shape(puntos: list[dict]) -> dict[str, list[list[float]]]:
    """Agrupa los puntos del shape por sentido: {'1': [[lat,lon],...], '2': [...]}, en orden."""
    por_sentido: dict[str, list[list[float]]] = {}
    for p in puntos:
        por_sentido.setdefault(p["sentido"], []).append(
            [float(p["shape_pt_lat"]), float(p["shape_pt_lon"])]
        )
    return por_sentido


def metros_de(distancia: str | None) -> int | None:
    """'21795m' -> 21795; '0m' -> 0; None o no numérico -> None."""
    try:
        return int(str(distancia).rstrip("m").strip())
    except (ValueError, TypeError):
        return None
