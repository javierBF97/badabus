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
MARGEN_LLEGADA_MIN = 2         # margen para dar un bus por cogido (andar es estimado)

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


def _fusionar_por_paradas(puntuadas: list) -> list:
    """Une las rutas que suben y bajan en las mismas paradas y solo cambian de línea.

    No son alternativas distintas: son el mismo viaje con varios buses que sirven, y
    eso conviene saberlo porque se coge el primero que pase. Solo se fusionan las que
    difieren en un único tramo; si cambian dos, no consta que esa combinación exista.
    """
    grupos: dict[tuple, list] = {}
    for p in puntuadas:
        grupos.setdefault(tuple((t["subir"], t["bajar"]) for t in p[-1]), []).append(p)

    salida = []
    for miembros in grupos.values():
        base = miembros[0]
        lineas_base = [t["linea"] for t in base[-1]]
        otras: dict[int, set] = {}
        for otro in miembros[1:]:
            lineas = [t["linea"] for t in otro[-1]]
            distintas = [i for i, (a, b) in enumerate(zip(lineas_base, lineas, strict=True)) if a != b]
            if len(distintas) == 1:
                otras.setdefault(distintas[0], set()).add(lineas[distintas[0]])
            else:
                salida.append(otro)
        if otras:
            tramos = [dict(t) for t in base[-1]]
            for i, lineas in otras.items():
                tramos[i]["alternativas"] = sorted(lineas)
            base = (*base[:-1], tramos)
        salida.append(base)
    salida.sort(key=lambda p: p[0])
    return salida


def _una_por_combinacion(puntuadas: list) -> list:
    """Una sola ruta por combinación de líneas: la más rápida.

    La misma combinación cogida en otra parada es el mismo viaje andando de más, no
    una alternativa. Llegan ordenadas por tiempo, así que la primera es la buena.
    """
    vistas: dict[tuple, tuple] = {}
    for p in puntuadas:
        vistas.setdefault(tuple(t["linea"] for t in p[-1]), p)
    return list(vistas.values())


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
             "espera_min": None, "andando_min": None, "aviso_espera": None}
            for ruta in rutas[:LIMITE_RUTAS]
        ]

    puntuadas = []
    for ruta in rutas:
        subir = ruta[0]["subir"]
        bajar = ruta[-1]["bajar"]
        viaje = minutos_viaje(ruta, red, paradas)
        km = andando_origen.get(subir, 0.0) + andando_destino.get(bajar, 0.0)
        andando = minutos_andando(km)
        proximo = esperas.get(subir, {}).get(ruta[0]["linea"])
        hasta_la_parada = minutos_andando(andando_origen.get(subir, 0.0))
        if proximo is None or proximo == math.inf:
            # Sin dato no se sabe la espera. Contarla como cero premiaría a la ruta
            # justo por no tener información, que es lo contrario de lo que toca.
            aviso, espera = "sin_datos", None
        elif subir in andando_origen and proximo < hasta_la_parada + MARGEN_LLEGADA_MIN:
            # Ese bus se va antes de que llegues andando. El servicio solo da una
            # llegada por línea, así que cuándo pasa el siguiente es desconocido: la
            # espera no es cero, es que no se sabe.
            aviso, espera = "no_llegas", None
        else:
            aviso, espera = None, proximo
        total = viaje + andando + (espera or 0)
        puntuadas.append((total, viaje, espera, andando, aviso, ruta))

    if not puntuadas:
        return []
    puntuadas.sort(key=lambda p: p[0])
    # Se quitan las repetidas antes de filtrar y recortar: si no, las cuatro plazas
    # se las llevan variantes del mismo viaje y las opciones buenas no se ven.
    puntuadas = _una_por_combinacion(_fusionar_por_paradas(puntuadas))
    mejor = puntuadas[0][0]
    # Primero se descartan las mucho peores, y solo después se recorta: si no,
    # una ruta buena podría quedar fuera del límite por culpa de otra que luego
    # se descarta.
    aceptables = [p for p in puntuadas if p[0] <= mejor * FACTOR_INFUMABLE]
    return [
        {
            "tramos": ruta,
            # Con la espera desconocida el total es un suelo, no una promesa: el
            # frontend lo dice ("desde X"), y `aviso_espera` explica por qué.
            "total_min": round(total),
            "viaje_min": round(viaje),
            "espera_min": round(espera) if espera is not None else None,
            "andando_min": round(andando) if hay_caminata else None,
            "aviso_espera": aviso,
        }
        for total, viaje, espera, andando, aviso, ruta in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """De paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
