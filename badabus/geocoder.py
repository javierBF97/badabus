"""Traducir entre direcciones y coordenadas, con dos proveedores en cascada.

**Photon** (Komoot, sobre OpenStreetMap) va primero: encuentra con la palabra a
medias —"Condes de Barc" ya devuelve el paseo—, y el autocompletado figura entre sus
funciones declaradas, al contrario que Nominatim, que lo prohíbe expresamente. Además
degrada bien: si pides un número que no existe, te da la calle.

**Cartociudad** (Instituto Geográfico Nacional) entra solo cuando Photon no encuentra
nada. Es el callejero oficial español y trae portales del catastro que OpenStreetMap
puede no tener. No sirve como principal porque devuelve **cero resultados** cuando el
número no está en su base, en vez de ofrecer la calle.

Aunque Photon permita buscar mientras se escribe, una petición por tecla sería abusar
de un servicio gratuito: el buscador mantiene su espera corta y su caché.
"""

import json
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

PHOTON = "https://photon.komoot.io/"
CARTOCIUDAD = "https://www.cartociudad.es/geocoder/api/geocoder/"
# Badajoz y alrededores: lon_min,lat_min,lon_max,lat_max
BBOX = "-7.05,38.83,-6.88,38.93"
CENTRO_LAT, CENTRO_LON = 38.879, -6.970
# Cartociudad busca en toda España si no se le dice dónde.
MUNICIPIO = "Badajoz"
USER_AGENT = "badabus/1.0 (proyecto personal; github.com/javierBF97/badabus)"
FETCH_MAX_BYTES = 1_000_000
LIMITE = 5

_FALLOS = (OSError, ValueError, KeyError, TypeError, IndexError)


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
    """Una entrada por nombre: el geocodificador devuelve varios tramos de un vial y
    en la lista salen tres veces la misma calle, que no ayuda a elegir."""
    vistos: dict[str, dict] = {}
    for sitio in sitios:
        vistos.setdefault(sitio["nombre"], sitio)
    return list(vistos.values())


def direccion(lat: float, lon: float, fetcher: Callable[..., bytes] = fetch) -> str:
    """Nombre del sitio que hay en esas coordenadas; cadena vacía si no se sabe."""
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
        # Sin recuadro, "Avenida de Elvas" se va a Elvas, que está en Portugal.
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
    """Un nombre legible a partir de las piezas sueltas que devuelve Photon."""
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
    # Sin el municipio busca por toda España y devuelve calles de otras provincias.
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
