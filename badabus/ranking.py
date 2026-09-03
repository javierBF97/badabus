import json
import math
import re
from pathlib import Path

from badabus import frecuencias as frec

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VELOCIDAD_COMERCIAL_KMH = 20   # velocidad comercial real, medida de tiempos
FACTOR_SINUOSIDAD = 1.3        # la ruta real serpentea ~30% más que la recta
FACTOR_INFUMABLE = 1.5         # se descarta lo que pase de 1.5x la mejor
LIMITE_RUTAS = 4               # máximo de alternativas devueltas

VELOCIDAD_ANDANDO_KMH = 4.5    # paso normal
FACTOR_CALLEJEO = 1.3          # andando tampoco se va en línea recta
RADIO_PARADAS_KM = 1.0         # tope de cordura al buscar paradas cercanas
RADIO_TRANSBORDO_KM = 0.3      # hasta donde se anda entre paradas para transbordar
MARGEN_LLEGADA_MIN = 2         # margen para dar un bus por cogido (andar es estimado)
ESPERA_TRANSBORDO_MIN = 5      # lo que se supone en un transbordo sin frecuencia conocida

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


def km_entre_tramos(ruta: list, paradas: dict) -> float:
    """Lo que se anda al transbordar, cuando no se sube donde se bajó.

    Con transbordos entre paradas cercanas el viaje deja de ser solo bus: hay metros a
    pie en medio, y no contarlos volvería a hacer parecer gratis lo que no lo es.
    """
    total = 0.0
    for anterior, siguiente in zip(ruta, ruta[1:], strict=False):
        if anterior["bajar"] == siguiente["subir"]:
            continue
        a, b = paradas.get(anterior["bajar"]), paradas.get(siguiente["subir"])
        if a and b:
            total += distancia_km(a, b)
    return total


def vecindad(paradas: dict, radio_km: float = RADIO_TRANSBORDO_KM) -> dict[str, list]:
    """Qué paradas se tocan andando: {parada: [(otra, km)]}.

    Es lo contrario de `paradas_cercanas`, que mide desde un punto suelto y recorre
    todas las paradas en cada llamada. Aquí interesa la red entera de una vez, para
    poder transbordar sin exigir que las dos líneas paren en el mismo sitio.
    """
    ids = list(paradas)
    vecinas: dict[str, list] = {p: [] for p in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            km = distancia_km(paradas[a], paradas[b])
            if km <= radio_km:
                vecinas[a].append((b, km))
                vecinas[b].append((a, km))
    return vecinas


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


def _orden(p: tuple) -> tuple:
    """Por tiempo, y a igualdad de tiempo menos transbordos.

    El desempate no es cosmetico: sin el, "coge la M4 y luego otro bus" puede colarse
    por delante de la M4 a secas y la regla que descarta rodeos no llega a verla.
    """
    return (p[0], len(p[-1]))


def _circula(p: tuple) -> bool:
    return p[6] != "fuera_de_servicio"


def _fusionar_por_paradas(puntuadas: list) -> list:
    """Une las rutas que suben y bajan en las mismas paradas y solo cambian de línea.

    No son alternativas distintas: son el mismo viaje con varios buses que sirven, y
    eso conviene saberlo porque se coge el primero que pase. Solo se fusionan las que
    difieren en un único tramo; si cambian dos, no consta que esa combinación exista.
    """
    grupos: dict[tuple, list] = {}
    for p in puntuadas:
        # Una linea que no circula no es intercambiable con una que si: presentarlas
        # juntas ("coge la primera que pase") seria mentir. Se agrupan por separado.
        clave = (tuple((t["subir"], t["bajar"]) for t in p[-1]), p[6] == "fuera_de_servicio")
        grupos.setdefault(clave, []).append(p)

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
    salida.sort(key=_orden)
    return salida


def _sin_dominadas(puntuadas: list) -> list:
    """Quita las rutas a las que otra gana en todo lo que importa.

    Si otra llega antes, te hace andar menos y con menos transbordos, esta no es una
    alternativa: no hay a quien le convenga. Descartarlas no exige decidir cuanto vale
    andar frente a esperar, que seria opinable; basta con que otra le gane en las tres.
    """
    aceptadas: list[tuple] = []
    for p in puntuadas:
        total, andando, saltos = p[0], p[4], len(p[-1])
        if any(
            q[0] <= total and q[4] <= andando and len(q[-1]) <= saltos
            for q in aceptadas
        ):
            continue
        aceptadas.append(p)
    return aceptadas


def _sin_rodeos(puntuadas: list) -> list:
    """Quita las rutas que son otra mas corta con buses de propina.

    Si la M2 sola te deja, "M2 y luego otro bus" no es una alternativa: llegas mas
    tarde al mismo sitio. Llegan ordenadas por tiempo, asi que cualquier ruta que
    empiece por una ya aceptada es peor por definicion.
    """
    aceptadas: list[tuple] = []
    lineas_ok: list[tuple] = []
    for p in puntuadas:
        lineas = tuple(t["linea"] for t in p[-1])
        if any(lineas[:len(corta)] == corta for corta in lineas_ok):
            continue
        aceptadas.append(p)
        lineas_ok.append(lineas)
    return aceptadas


def _una_por_combinacion(puntuadas: list) -> list:
    """Una sola ruta por combinación de líneas: la más rápida.

    La misma combinación cogida en otra parada es el mismo viaje andando de más, no
    una alternativa. Llegan ordenadas por tiempo, así que la primera es la buena.
    """
    vistas: dict[tuple, tuple] = {}
    for p in puntuadas:
        # Por el CONJUNTO de lineas de cada tramo: tras fusionar alternativas, "C2 o 5"
        # y "5 o C2" son el mismo viaje aunque cambie cual figura primero.
        clave = tuple(
            frozenset([t["linea"], *t.get("alternativas", [])]) for t in p[-1]
        )
        vistas.setdefault(clave, p)
    return list(vistas.values())


def _espera_en_transbordos(
    ruta: list, red: dict, paradas: dict, esperas: dict, horarios: dict,
    tipo_dia: str | None, ahora_min: int | None, desde_min: float,
) -> float:
    """Lo que se espera en los transbordos, que antes no se contaba en absoluto.

    El servicio da los tiempos de **cualquier** parada, no solo la de origen, así que
    en el transbordo también se sabe cuándo pasa la otra línea. Con eso y la hora
    estimada de llegada se calcula la espera de verdad, en lugar de suponerla.

    Si ese bus se escapa —la llegada es una estimación, así que se exige el mismo
    margen que al salir— se salta al siguiente sumando la frecuencia. Sin dato en vivo
    queda media frecuencia, que es lo esperable al caer en un punto cualquiera del
    horario; y sin frecuencia, una cifra fija: un transbordo nunca es gratis.
    """
    total = 0.0
    reloj = desde_min          # minutos desde ahora en que arranca el tramo en curso
    for anterior, tramo in zip(ruta, ruta[1:], strict=False):
        reloj += minutos_viaje([anterior], red, paradas)
        if anterior["bajar"] != tramo["subir"]:
            # El transbordo es andando: hay que llegar antes de poder subir.
            reloj += minutos_andando(km_entre_tramos([anterior, tramo], paradas))
        linea = tramo["linea"]
        intervalo = None
        if horarios and tipo_dia and ahora_min is not None:
            intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)
        pasa = esperas.get(tramo["subir"], {}).get(linea)
        espera = None
        if pasa is not None and pasa != math.inf:
            # Ese dato fija la fase de la línea en esa parada: si el bus que viene se
            # escapa, los siguientes van de frecuencia en frecuencia.
            while pasa < reloj + MARGEN_LLEGADA_MIN and intervalo:
                pasa += intervalo
            if pasa >= reloj + MARGEN_LLEGADA_MIN:
                espera = pasa - reloj
        if espera is None:
            espera = intervalo / 2 if intervalo else ESPERA_TRANSBORDO_MIN
        total += espera
        reloj += espera
    return total


def _resolver_espera(
    linea: str, proximo, hasta_la_parada: float, camina: bool,
    horarios: dict, tipo_dia: str | None, ahora_min: int | None,
) -> tuple:
    """Cuánto se espera al bus, y qué se puede afirmar de ello.

    Devuelve (espera, tope, aviso). `espera` son minutos cuando se sostienen; `tope` es
    lo más que puede tardar cuando no se sabe la espera pero sí cada cuánto pasa; y
    `aviso` explica por qué no hay un número cerrado.

    Si el bus anunciado se escapa mientras andas, la frecuencia cierra el hueco: el
    siguiente va una frecuencia después de ese. Eso no es una suposición, es aritmética
    sobre dos datos conocidos.
    """
    intervalo = None
    if horarios and tipo_dia and ahora_min is not None:
        if frec.en_servicio(horarios, linea, tipo_dia, ahora_min) is False:
            return None, None, "fuera_de_servicio"
        intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)

    if proximo is None or proximo == math.inf:
        # Sin dato en vivo no se sabe cuándo pasó el último, pero la frecuencia acota
        # la espera: nunca más de una vuelta.
        return None, intervalo, "sin_datos"

    if camina and proximo < hasta_la_parada + MARGEN_LLEGADA_MIN:
        if intervalo is None:
            return None, None, "no_llegas"
        siguiente = proximo + intervalo
        if ahora_min is not None and horarios:
            fin = frec.en_servicio(horarios, linea, tipo_dia, int(ahora_min + siguiente))
            if fin is False:
                return None, None, "fuera_de_servicio"
        return siguiente - hasta_la_parada, None, "no_llegas"

    return proximo, None, None


def puntuar(
    rutas: list[list[dict]],
    red: dict,
    paradas: dict,
    esperas: dict,
    andando_origen: dict | None = None,
    andando_destino: dict | None = None,
    horarios: dict | None = None,
    tipo_dia: str | None = None,
    ahora_min: int | None = None,
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
             "espera_min": None, "espera_max_min": None,
             "espera_transbordo_min": None,
             "andando_min": None, "aviso_espera": None}
            for ruta in rutas[:LIMITE_RUTAS]
        ]

    puntuadas = []
    for ruta in rutas:
        subir = ruta[0]["subir"]
        bajar = ruta[-1]["bajar"]
        viaje = minutos_viaje(ruta, red, paradas)
        km = (andando_origen.get(subir, 0.0) + andando_destino.get(bajar, 0.0)
              + km_entre_tramos(ruta, paradas))
        andando = minutos_andando(km)
        espera, tope, aviso = _resolver_espera(
            ruta[0]["linea"],
            esperas.get(subir, {}).get(ruta[0]["linea"]),
            minutos_andando(andando_origen.get(subir, 0.0)),
            subir in andando_origen,
            horarios or {}, tipo_dia, ahora_min,
        )
        transbordo = _espera_en_transbordos(
            ruta, red, paradas, esperas, horarios or {}, tipo_dia, ahora_min,
            andando + (espera or 0),
        )
        total = viaje + andando + (espera or 0) + transbordo
        puntuadas.append((total, viaje, espera, tope, andando, transbordo, aviso, ruta))

    if not puntuadas:
        return []
    # Una linea que no circula a esta hora no es una alternativa: va detras de todo, por
    # buena que parezca. Se sigue mostrando para que se vea por que no sirve, pero nunca
    # desplaza a una ruta que si se puede coger.
    # Una linea que no circula a esta hora no es una alternativa: fuera. Si no queda
    # ninguna se devuelven igual, para poder explicar por que en vez de decir que no
    # hay ruta, que seria falso: la hay, pero no ahora.
    circulan = [p for p in puntuadas if _circula(p)]
    puntuadas = circulan or puntuadas
    puntuadas.sort(key=_orden)
    # Se quitan las repetidas antes de filtrar y recortar: si no, las cuatro plazas
    # se las llevan variantes del mismo viaje y las opciones buenas no se ven.
    puntuadas = _sin_dominadas(
        _sin_rodeos(_una_por_combinacion(_fusionar_por_paradas(puntuadas)))
    )
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
            # Lo más que puede tardar cuando no se sabe la espera pero sí la frecuencia.
            "espera_max_min": round(tope) if tope is not None else None,
            # Lo que se espera en los transbordos, ya dentro del total.
            "espera_transbordo_min": round(transbordo) if transbordo else None,
            "andando_min": round(andando) if hay_caminata else None,
            "aviso_espera": aviso,
        }
        for total, viaje, espera, tope, andando, transbordo, aviso, ruta
        in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """De paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
