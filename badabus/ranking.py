import json
import math
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VELOCIDAD_COMERCIAL_KMH = 20   # velocidad comercial real, medida de tiempos
FACTOR_SINUOSIDAD = 1.3        # la ruta real serpentea ~30% más que la recta
FACTOR_INFUMABLE = 1.5         # se descarta lo que pase de 1.5x la mejor
LIMITE_RUTAS = 4               # máximo de alternativas devueltas

VELOCIDAD_ANDANDO_KMH = 4.5    # paso normal
FACTOR_CALLEJEO = 1.3          # andando tampoco se va en línea recta
RADIO_PARADAS_KM = 1.0         # tope de cordura al buscar paradas cercanas

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


def minutos_andando(km: float) -> float:
    """Minutos a pie de una distancia recta, corregida porque no se
    atraviesan edificios.
    """
    return km * FACTOR_CALLEJEO / VELOCIDAD_ANDANDO_KMH * 60


def paradas_cercanas(
    lat: float, lon: float, paradas: dict
) -> list[tuple[str, float]]:
    """Las paradas a menos de RADIO_PARADAS_KM de un punto, como [(id, km)], de
    más cerca a más lejos.

    No se recorta la lista: quedarse con las más próximas escondía líneas enteras,
    porque varias paradas pegadas suelen ser de las mismas líneas. El planificador
    ya no paga por mirarlas todas, y el ranking decide si compensa andar.
    """
    cerca = []
    for parada, coords in paradas.items():
        km = distancia_km((lat, lon), coords)
        if km <= RADIO_PARADAS_KM:
            cerca.append((parada, km))
    cerca.sort(key=lambda p: p[1])
    return cerca


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
    rutas: list[list[dict]],
    red: dict,
    paradas: dict,
    esperas: dict,
    andando_origen: dict | None = None,
    andando_destino: dict | None = None,
) -> list[dict]:
    """Ordena las rutas por tiempo total estimado y filtra las mucho peores.

    El total es andar + esperar + bus. `esperas` va por parada de subida
    ({id_parada: {linea: minutos}}), porque cada origen candidato tiene la suya.
    `andando_origen` y `andando_destino` son {id_parada: km}; vacíos cuando el
    usuario eligió paradas a mano y no hay caminata que contar.

    Cada ruta se devuelve como {"tramos", "total_min", "viaje_min", "espera_min",
    "andando_min"}. `total_min` es la suma y la única fuente de verdad: el frontend
    la pinta, no la recalcula. Con los minutos redondeados y None donde el dato no
    se conoce. Sin coordenadas no se puede estimar nada: se devuelven en el orden
    del planificador.
    """
    andando_origen = andando_origen or {}
    andando_destino = andando_destino or {}
    hay_caminata = bool(andando_origen or andando_destino)

    if not paradas:
        return [
            {"tramos": ruta, "total_min": None, "viaje_min": None,
             "espera_min": None, "andando_min": None}
            for ruta in rutas[:LIMITE_RUTAS]
        ]

    puntuadas = []
    for ruta in rutas:
        subir = ruta[0]["subir"]
        bajar = ruta[-1]["bajar"]
        viaje = minutos_viaje(ruta, red, paradas)
        espera = esperas.get(subir, {}).get(ruta[0]["linea"], math.inf)
        km = andando_origen.get(subir, 0.0) + andando_destino.get(bajar, 0.0)
        andando = minutos_andando(km)
        total = viaje + andando + (espera if espera != math.inf else 0)
        puntuadas.append((total, viaje, espera, andando, ruta))

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
            "total_min": round(total),
            "viaje_min": round(viaje),
            "espera_min": round(espera) if espera != math.inf else None,
            "andando_min": round(andando) if hay_caminata else None,
        }
        for total, viaje, espera, andando, ruta in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """De paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
