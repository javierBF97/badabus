"""Translate between addresses and coordinates, with two providers in cascade.

**Photon** (Komoot, on OpenStreetMap) goes first: it finds an address from half a word,
and autocomplete is one of its stated features, unlike Nominatim, which forbids it
expressly. It also degrades well: if you ask for a street number that does not exist,
it gives you the street.

**Cartociudad** (Instituto Geográfico Nacional) comes in only when Photon finds nothing.
It is the official Spanish street register and it holds land registry addresses that
OpenStreetMap may not have. It does not serve as the primary provider, because it
returns **zero results** when the number is not in its database, instead of offering
the street.

Photon allows search as you type, but one request per keystroke would abuse a free
service: the search box keeps its short delay and its cache.
"""

import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

PHOTON = "https://photon.komoot.io/"
CARTOCIUDAD = "https://www.cartociudad.es/geocoder/api/geocoder/"
# Badajoz and its surroundings: lon_min,lat_min,lon_max,lat_max
BBOX = "-7.05,38.83,-6.88,38.93"
CENTRO_LAT, CENTRO_LON = 38.879, -6.970
# Cartociudad searches all of Spain if it is not told where.
MUNICIPIO = "Badajoz"
USER_AGENT = "badabus/1.0 (proyecto personal; github.com/javierBF97/badabus)"
FETCH_MAX_BYTES = 1_000_000
LIMITE = 5

_FALLOS = (OSError, ValueError, KeyError, TypeError, IndexError)


def fetch(url: str, timeout: int = 10) -> bytes:
    """GET to the geocoder, identified as its usage policy requires."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(FETCH_MAX_BYTES)


def buscar(texto: str, fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Addresses that match the text, bounded to Badajoz.

    Returns [{"nombre", "lat", "lon"}]. Results without coordinates are left out.
    """
    consulta = texto.strip()
    if not consulta:
        return []
    try:
        sitios = _photon_buscar(consulta, fetcher)
    except _FALLOS:
        sitios = []
    if sitios:
        return _sin_repetidos(sitios)
    try:
        return _sin_repetidos(_cartociudad_buscar(consulta, fetcher))
    except _FALLOS:
        return []


def _sin_repetidos(sitios: list[dict]) -> list[dict]:
    """One entry per name: the geocoder returns several segments of one road, and the
    same street then appears three times in the list, which does not help to choose."""
    vistos: dict[str, dict] = {}
    for sitio in sitios:
        vistos.setdefault(sitio["nombre"], sitio)
    return list(vistos.values())


def direccion(lat: float, lon: float, fetcher: Callable[..., bytes] = fetch) -> str:
    """Name of the place at those coordinates. An empty string if it is not known."""
    try:
        nombre = _photon_inversa(lat, lon, fetcher)
    except _FALLOS:
        nombre = ""
    if nombre:
        return nombre
    try:
        return _cartociudad_inversa(lat, lon, fetcher)
    except _FALLOS:
        return ""


def _photon_buscar(consulta: str, fetcher: Callable[..., bytes]) -> list[dict]:
    query = urlencode({
        "q": consulta,
        "limit": LIMITE,
        "lat": CENTRO_LAT,
        "lon": CENTRO_LON,
        # Without the box, "Avenida de Elvas" goes to Elvas, which is in Portugal.
        "bbox": BBOX,
    })
    datos = json.loads(fetcher(f"{PHOTON}api/?{query}"))
    salida = []
    for sitio in datos.get("features", []):
        punto = (sitio.get("geometry") or {}).get("coordinates") or []
        if len(punto) < 2:
            continue
        try:
            salida.append({
                "nombre": _nombre_photon(sitio.get("properties") or {}),
                "lat": float(punto[1]),
                "lon": float(punto[0]),
            })
        except (TypeError, ValueError):
            continue
    return [s for s in salida if s["nombre"]]


def _nombre_photon(props: dict) -> str:
    """A readable name from the loose pieces that Photon returns."""
    calle = props.get("street") or props.get("name") or ""
    numero = props.get("housenumber")
    cabeza = f"{calle} {numero}".strip() if numero else calle
    resto = [props.get("district"), props.get("city"), props.get("state")]
    return ", ".join(x for x in [cabeza, *resto] if x)


def _photon_inversa(lat: float, lon: float, fetcher: Callable[..., bytes]) -> str:
    query = urlencode({"lat": lat, "lon": lon, "limit": 1})
    datos = json.loads(fetcher(f"{PHOTON}reverse?{query}"))
    rasgos = datos.get("features") or []
    return _nombre_photon(rasgos[0].get("properties") or {}) if rasgos else ""


def _cartociudad_buscar(consulta: str, fetcher: Callable[..., bytes]) -> list[dict]:
    # Without the municipality it searches all of Spain and returns other provinces.
    query = urlencode({"q": f"{consulta}, {MUNICIPIO}", "limit": LIMITE})
    datos = json.loads(fetcher(f"{CARTOCIUDAD}candidates?{query}"))
    salida = []
    for sitio in datos if isinstance(datos, list) else []:
        try:
            salida.append({
                "nombre": _nombre_cartociudad(sitio),
                "lat": float(sitio["lat"]),
                "lon": float(sitio["lng"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return [s for s in salida if s["nombre"]]


def _nombre_cartociudad(sitio: dict) -> str:
    direccion_ = (sitio.get("address") or "").strip()
    muni = (sitio.get("muni") or "").strip()
    if muni and muni.lower() not in direccion_.lower():
        return f"{direccion_}, {muni}".strip(", ")
    return direccion_


def _cartociudad_inversa(lat: float, lon: float, fetcher: Callable[..., bytes]) -> str:
    query = urlencode({"lat": lat, "lon": lon})
    datos = json.loads(fetcher(f"{CARTOCIUDAD}reverseGeocode?{query}"))
    return _nombre_cartociudad(datos) if isinstance(datos, dict) else ""
