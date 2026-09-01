import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

BASE = "https://nominatim.openstreetmap.org/"
# Badajoz y alrededores: lon_min,lat_min,lon_max,lat_max
VIEWBOX = "-7.05,38.83,-6.88,38.93"
# Nominatim exige identificarse; sin esto puede rechazar las peticiones.
USER_AGENT = "badabus/1.0 (proyecto personal; github.com/javierBF97/badabus)"
FETCH_MAX_BYTES = 1_000_000


def fetch(url: str, timeout: int = 10) -> bytes:
    """GET al geocodificador, identificándose como pide su política de uso."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(FETCH_MAX_BYTES)


def buscar(texto: str, fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Direcciones que coinciden con el texto, acotadas a Badajoz.

    Devuelve [{"nombre", "lat", "lon"}]. Los resultados sin coordenadas se omiten.
    """
    consulta = texto.strip()
    if not consulta:
        return []
    query = urlencode({
        "q": consulta,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "es",
        "viewbox": VIEWBOX,
        "bounded": 1,
    })
    datos = json.loads(fetcher(f"{BASE}search?{query}"))
    salida = []
    for sitio in datos:
        try:
            salida.append({
                "nombre": sitio["display_name"],
                "lat": float(sitio["lat"]),
                "lon": float(sitio["lon"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return salida


def direccion(lat: float, lon: float, fetcher: Callable[..., bytes] = fetch) -> str:
    """Nombre del sitio que hay en esas coordenadas; cadena vacía si no se sabe."""
    query = urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18})
    datos = json.loads(fetcher(f"{BASE}reverse?{query}"))
    if not isinstance(datos, dict):
        return ""
    return datos.get("display_name", "")
