import json
import math
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VELOCIDAD_COMERCIAL_KMH = 20   # velocidad comercial real, medida de tiempos
FACTOR_SINUOSIDAD = 1.3        # la ruta real serpentea ~30% más que la recta
FACTOR_INFUMABLE = 1.5         # se descarta lo que pase de 1.5x la mejor
LIMITE_RUTAS = 4               # máximo de alternativas devueltas

RADIO_TIERRA_KM = 6371.0


def distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en línea recta (haversine) entre dos (lat, lon), en kilómetros."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(h))


def minutos_viaje(ruta: list[dict], red: dict, paradas: dict) -> float:
    """Minutos de trayecto estimados: distancia recta entre paradas,
    corregida y a velocidad media.

    Se ignoran las paradas sin coordenadas y se suma entre las que quedan,
    en orden.

    Nota: los índices se resuelven por la PRIMERA aparición de cada parada
    en la secuencia de la línea, siguiendo la misma convención que usa el
    planificador al construir tramos. Por eso, en líneas de ida y vuelta
    (que repiten paradas), un tramo del retorno puede medirse con más
    paradas intermedias de las ideales.
    """
    km = 0.0
    for tramo in ruta:
        seq = red[tramo["linea"]]
        i = seq.index(tramo["subir"])
        j = i + 1 + seq[i + 1:].index(tramo["bajar"])
        coords = [paradas[s] for s in seq[i:j + 1] if s in paradas]
        for a, b in zip(coords, coords[1:], strict=False):
            km += distancia_km(a, b)
    return km * FACTOR_SINUOSIDAD / VELOCIDAD_COMERCIAL_KMH * 60


_ALIAS_LINEA = {"BGM1": "BG1", "BGM2": "BG2"}
_PREFIJO_LINEA = re.compile(r"^L[ÍI]NEA\s+", re.IGNORECASE)


def codigo_linea(texto: str) -> str:
    """Nombre de línea de tiempos a código: quita el prefijo 'LÍNEA ' y
    aplica alias BGM→BG.
    """
    codigo = _PREFIJO_LINEA.sub("", str(texto)).strip()
    return _ALIAS_LINEA.get(codigo, codigo)


def minutos_espera(texto: str) -> float:
    """Minutos hasta el próximo bus: '4 Minutos.' -> 4, 'Próximo.' -> 0,
    sin número -> inf.
    """
    encontrado = re.search(r"\d+", str(texto))
    if encontrado:
        return float(encontrado.group())
    if re.search(r"pr[óo]ximo", str(texto), re.IGNORECASE):
        return 0.0
    return math.inf


def esperas_por_linea(tiempos: list[dict]) -> dict[str, float]:
    """De la respuesta de tiempos de una parada: {codigo de línea:
    menor espera en minutos}.
    """
    esperas: dict[str, float] = {}
    for fila in tiempos:
        codigo = codigo_linea(fila.get("linea", ""))
        espera = minutos_espera(fila.get("tiempo", ""))
        if codigo not in esperas or espera < esperas[codigo]:
            esperas[codigo] = espera
    return esperas


def puntuar(
    rutas: list[list[dict]], red: dict, paradas: dict, esperas: dict
) -> list[dict]:
    """Ordena las rutas por tiempo estimado (trayecto + espera del primer bus) y
    filtra las peores.

    Cada ruta se devuelve como {"tramos", "viaje_min", "espera_min"} (minutos
    redondeados; la espera es None si no se conoce). Sin coordenadas no se puede
    estimar: se devuelven en el orden del planificador, sin puntuar.
    """
    if not paradas:
        return [
            {"tramos": ruta, "viaje_min": None, "espera_min": None}
            for ruta in rutas[:LIMITE_RUTAS]
        ]

    puntuadas = []
    for ruta in rutas:
        viaje = minutos_viaje(ruta, red, paradas)
        espera = esperas.get(ruta[0]["linea"], math.inf)
        total = viaje + (espera if espera != math.inf else 0)
        puntuadas.append((total, viaje, espera, ruta))

    if not puntuadas:
        return []
    puntuadas.sort(key=lambda p: p[0])
    mejor = puntuadas[0][0]
    # Primero se descartan las mucho peores, y solo después se recorta: si no,
    # una ruta buena podría quedar fuera del límite por culpa de otra que luego
    # se descarta.
    aceptables = [p for p in puntuadas if p[0] <= mejor * FACTOR_INFUMABLE]
    return [
        {
            "tramos": ruta,
            "viaje_min": round(viaje),
            "espera_min": round(espera) if espera != math.inf else None,
        }
        for _, viaje, espera, ruta in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """De paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
