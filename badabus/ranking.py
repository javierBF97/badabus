import json
import math
import re
from pathlib import Path
from typing import NamedTuple

from badabus import frecuencias as frec

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VELOCIDAD_COMERCIAL_KMH = 20   # real commercial speed, measured from the arrivals
FACTOR_SINUOSIDAD = 1.3        # the real course winds ~30% more than the line
FACTOR_INFUMABLE = 1.5         # anything over 1.5x the best one is dropped
LIMITE_RUTAS = 4               # most alternatives returned

VELOCIDAD_ANDANDO_KMH = 4.5    # a normal pace
FACTOR_CALLEJEO = 1.3          # on foot you do not go straight either
RADIO_PARADAS_KM = 1.0         # sanity limit when looking for nearby stops
RADIO_TRANSBORDO_KM = 0.3      # how far you walk between stops to transfer
MARGEN_LLEGADA_MIN = 2         # margin to call a bus caught (walking is an estimate)
ESPERA_TRANSBORDO_MIN = 5      # assumed at a transfer with no known frequency
# The assumed wait for a bus with no live data and no published frequency. It is half
# of the median published frequency (30 min), which is the expected wait if you reach
# the stop at a random time. It is not a measurement. It is the least bad alternative
# to counting zero, which is the only value that is certainly wrong.
ESPERA_SIN_DATO_MIN = 15

RADIO_TIERRA_KM = 6371.0


def distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line distance (haversine) between two (lat, lon) points, in kilometres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(h))


def cargar_shapes(data_dir: Path = DATA_DIR) -> dict:
    """The geometry of each line, or {} if the file is not there."""
    try:
        return json.loads((data_dir / "shapes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _puntos(sentido: list) -> list:
    salida = []
    for p in sentido:
        if isinstance(p, dict):
            lat, lon = p.get("lat"), p.get("lon")
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            lat, lon = p[0], p[1]
        else:
            continue
        try:
            salida.append((float(lat), float(lon)))
        except (TypeError, ValueError):
            continue
    return salida


def distancias_por_tramo(red: dict, paradas: dict, shapes: dict) -> dict:
    """Road distance between consecutive stops: {(line, a, b): km}.

    A straight line times a fixed factor is wrong in both directions. Measured over 491
    legs, the real detour factor runs from 0.95 to 2.19, with a median of 1.10 against
    the 1.30 that a single fixed factor gives every leg. Straight legs get too much
    time. Winding legs get too little, and that is the direction that hurts, because it
    makes you miss transfers.

    The geometry is already downloaded, so the distance can be measured instead of
    assumed. It is computed once: to scan the shapes on every query would be expensive.
    """
    reales: dict[tuple, float] = {}
    for linea, seq in red.items():
        for sentido in (shapes.get(linea) or {}).values():
            pts = _puntos(sentido)
            if len(pts) < 2:
                continue
            # The shape point nearest to each stop, computed once per stop.
            cerca = {}
            for parada in set(seq):
                if parada in paradas:
                    cerca[parada] = min(
                        range(len(pts)), key=lambda i: distancia_km(paradas[parada], pts[i])
                    )
            for a, b in zip(seq, seq[1:], strict=False):
                if a not in cerca or b not in cerca or cerca[b] <= cerca[a]:
                    continue
                if (linea, a, b) in reales:
                    continue
                tramo = pts[cerca[a]:cerca[b] + 1]
                km = sum(distancia_km(tramo[i], tramo[i + 1]) for i in range(len(tramo) - 1))
                recta = distancia_km(paradas[a], paradas[b])
                # A badly aligned shape can give nonsense, so impossible values are dropped.
                if recta > 0 and recta <= km <= recta * 3:
                    reales[(linea, a, b)] = km
    return reales


def minutos_viaje(
    ruta: list[dict], red: dict, paradas: dict, reales: dict | None = None
) -> float:
    """Estimated ride time in minutes, at the mean commercial speed.

    With `reales`, the road distance measured from the line shape is used. Without it,
    the distance falls back to the straight line between stops times a fixed factor.
    That is worse, but it does not need the downloaded geometry.

    Stops without coordinates are ignored. The distance is summed between the stops
    that remain, in order.

    Note: the boarding stop resolves to its FIRST occurrence in the line sequence, and
    the alighting stop to its first occurrence after that one.
    This follows the same convention the planner uses to build legs. On out-and-back
    lines, which repeat stops, a return leg can therefore be measured through more
    intermediate stops than it should.
    """
    reales = reales or {}
    km = 0.0
    for tramo in ruta:
        linea = tramo["linea"]
        seq = red[linea]
        i = seq.index(tramo["subir"])
        j = i + 1 + seq[i + 1:].index(tramo["bajar"])
        # Stops without coordinates are bridged: the distance is measured from the
        # previous stop to the next one, which approximates better than dropping that
        # part of the trip.
        entre = [s for s in seq[i:j + 1] if s in paradas]
        for a, b in zip(entre, entre[1:], strict=False):
            medida = reales.get((linea, a, b))
            if medida is not None:
                km += medida
            else:
                # Without geometry for that leg, the corrected straight line is all there is.
                km += distancia_km(paradas[a], paradas[b]) * FACTOR_SINUOSIDAD
    return km / VELOCIDAD_COMERCIAL_KMH * 60


def minutos_andando(km: float) -> float:
    """Walking minutes for a straight-line distance, corrected because a person does
    not walk through buildings.
    """
    return km * FACTOR_CALLEJEO / VELOCIDAD_ANDANDO_KMH * 60


def km_entre_tramos(ruta: list, paradas: dict) -> float:
    """The distance walked at a transfer, when you do not board where you alighted.

    With transfers between nearby stops, a trip is no longer only bus. There are metres
    on foot in the middle. If they are not counted, they look free, and they are not.
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
    """Which stops are within walking distance of each other: {stop: [(other, km)]}.

    This is the opposite of `paradas_cercanas`, which measures from a single arbitrary
    point and scans all the stops on every call. Here the whole network is needed at once, so
    that a transfer does not require both lines to call at the same place.
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
    """The stops within RADIO_PARADAS_KM of a point, as [(id, km)], nearest first.

    The list is not trimmed. Keeping only the nearest stops hides whole lines, because
    stops close together tend to serve the same lines. The planner does not pay to look
    at all of them, and the ranking decides whether the walk is worth it.
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
    """Line name from the arrivals feed to a line code: it removes the 'LÍNEA ' prefix,
    in any case, and applies the BGM1 and BGM2 aliases.
    """
    codigo = _PREFIJO_LINEA.sub("", str(texto)).strip()
    return _ALIAS_LINEA.get(codigo, codigo)


def minutos_espera(texto: str) -> float:
    """Minutes to the next bus: '4 Minutos.' -> 4, 'Próximo.' -> 0, no number -> inf.
    """
    encontrado = re.search(r"\d+", str(texto))
    if encontrado:
        return float(encontrado.group())
    if re.search(r"pr[óo]ximo", str(texto), re.IGNORECASE):
        return 0.0
    return math.inf


def esperas_por_linea(tiempos: list[dict]) -> dict[str, float]:
    """From the arrivals response of one stop: {line code: shortest wait in minutes}.
    """
    esperas: dict[str, float] = {}
    for fila in tiempos:
        codigo = codigo_linea(fila.get("linea", ""))
        espera = minutos_espera(fila.get("tiempo", ""))
        if codigo not in esperas or espera < esperas[codigo]:
            esperas[codigo] = espera
    return esperas


class Puntuada(NamedTuple):
    """A route that is already measured, with **two** totals that are not the same number.

    `total` is what the user sees. With an unknown wait it is a floor, and the card says
    so ("from X min"): the application does not assert what it does not know.

    `comparable` decides the order, which route dominates which, and what is dropped for
    being much worse. A floor is wrong there. To count zero for an unknown wait makes
    the least known route win every time, because zero is the best possible number. A
    route with "up to 20 min of wait" can erase from the screen another route whose 15
    minutes are certain. The estimate follows the rule that transfers already use: half the frequency
    where it is published, and a fixed figure where it is not.
    """

    total: float
    comparable: float
    viaje: float
    espera: float | None
    tope: float | None
    andando: float
    transbordo: float
    aviso: str | None
    ruta: list


def _espera_estimada(espera: float | None, tope: float | None) -> float:
    """The wait that can be expected, for comparison. Never zero just because it is unknown."""
    if espera is not None:
        return espera
    return tope / 2 if tope else ESPERA_SIN_DATO_MIN


def _orden(p: Puntuada) -> tuple:
    """By estimated time, and with fewer legs when the time is equal.

    The tie-break is not cosmetic. Without it, "take a line and then another bus" can
    slip ahead of that same line on its own, and the rule that drops detours never sees
    it.
    """
    return (p.comparable, len(p.ruta))


def _circula(p: Puntuada) -> bool:
    return p.aviso != "fuera_de_servicio"


def _fusionar_por_paradas(puntuadas: list) -> list:
    """Merges the routes that board and alight at the same stops and only change line.

    They are not different alternatives. They are the same trip with several buses that
    serve it, and that is worth knowing, because you take the first one that comes. Only
    routes that differ in a single leg are merged. If two legs differ, there is no
    evidence that the combination exists.
    """
    grupos: dict[tuple, list] = {}
    for p in puntuadas:
        # A line that does not run is not interchangeable with one that does: to
        # present them together ("take the first one that comes") would be a lie. They
        # are grouped separately.
        clave = (tuple((t["subir"], t["bajar"]) for t in p.ruta),
                 p.aviso == "fuera_de_servicio")
        grupos.setdefault(clave, []).append(p)

    salida = []
    for miembros in grupos.values():
        base = miembros[0]
        lineas_base = [t["linea"] for t in base.ruta]
        otras: dict[int, set] = {}
        for otro in miembros[1:]:
            lineas = [t["linea"] for t in otro.ruta]
            distintas = [i for i, (a, b) in enumerate(zip(lineas_base, lineas, strict=True)) if a != b]
            if len(distintas) == 1:
                otras.setdefault(distintas[0], set()).add(lineas[distintas[0]])
            else:
                salida.append(otro)
        if otras:
            tramos = [dict(t) for t in base.ruta]
            for i, lineas in otras.items():
                tramos[i]["alternativas"] = sorted(lineas)
            base = base._replace(ruta=tramos)
        salida.append(base)
    salida.sort(key=_orden)
    return salida


def _sin_dominadas(puntuadas: list) -> list:
    """Removes the routes that another route equals or beats on everything that matters.

    If another route arrives no later, makes you walk no further and has no more
    transfers, this one is not an alternative: it suits nobody. The rule needs no view on what a minute walking
    is worth against a minute waiting, which would be a matter of opinion. It is enough
    that another route wins on all three.

    The comparison uses `comparable`, not what the user sees. And a route whose wait is
    unknown **cannot discard one whose wait is known**, however good its estimate looks:
    that would erase a certainty on the strength of an assumption. It can sort ahead,
    which is what the expected value says, but the other one is still offered.
    """
    aceptadas: list[Puntuada] = []
    for p in puntuadas:
        total, andando, saltos = p.comparable, p.andando, len(p.ruta)
        if any(
            q.comparable <= total and q.andando <= andando and len(q.ruta) <= saltos
            and not (q.espera is None and p.espera is not None)
            for q in aceptadas
        ):
            continue
        aceptadas.append(p)
    return aceptadas


def _sin_rodeos(puntuadas: list) -> list:
    """Removes the routes that are a shorter route with extra buses added on.

    If one line alone takes you there, "that line and then another bus" is not an
    alternative: you reach the same place later. The routes arrive ordered by time, so
    any route that starts with an already accepted one is worse by definition.
    """
    aceptadas: list[Puntuada] = []
    lineas_ok: list[tuple] = []
    for p in puntuadas:
        lineas = tuple(t["linea"] for t in p.ruta)
        if any(lineas[:len(corta)] == corta for corta in lineas_ok):
            continue
        aceptadas.append(p)
        lineas_ok.append(lineas)
    return aceptadas


def _una_por_combinacion(puntuadas: list) -> list:
    """One route per combination of lines: the fastest one.

    The same combination boarded at another stop is the same trip with more walking, not
    an alternative. The routes arrive ordered by time, so the first one is the one to
    keep.
    """
    vistas: dict[tuple, Puntuada] = {}
    for p in puntuadas:
        # By the SET of lines of each leg: after alternatives are merged, "A or B"
        # and "B or A" are the same trip, even if the one listed first changes.
        clave = tuple(
            frozenset([t["linea"], *t.get("alternativas", [])]) for t in p.ruta
        )
        vistas.setdefault(clave, p)
    return list(vistas.values())


def _espera_en_transbordos(
    ruta: list, red: dict, paradas: dict, esperas: dict, horarios: dict,
    tipo_dia: str | None, ahora_min: int | None, desde_min: float,
    reales: dict | None = None,
) -> float:
    """The wait at each transfer, read from live data instead of assumed.

    The service gives arrivals for **any** stop, not only the origin one, so at the
    transfer the arrival of the other line is known too. With that and the estimated
    arrival time, the real wait is calculated instead of assumed.

    If that bus is missed — the arrival is an estimate, so it requires the same margin
    as the departure — the next one is taken by adding the frequency. Without live data,
    half the frequency applies, which is the expected wait at a random point of the
    timetable. Without a frequency, a fixed figure applies: a transfer is never free.
    """
    total = 0.0
    reloj = desde_min          # minutes from now when the current leg starts
    for anterior, tramo in zip(ruta, ruta[1:], strict=False):
        reloj += minutos_viaje([anterior], red, paradas, reales)
        if anterior["bajar"] != tramo["subir"]:
            # The transfer is on foot: you must arrive before you can board.
            reloj += minutos_andando(km_entre_tramos([anterior, tramo], paradas))
        linea = tramo["linea"]
        intervalo = None
        if horarios and tipo_dia and ahora_min is not None:
            intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)
        # The same as at the start: it looks at when each bus calls at this stop, not
        # only the announced one, and takes the first one that can be reached in time.
        pasos = pasadas_en_parada(
            linea, tramo["subir"], esperas, red, paradas, reales, intervalo)
        alcanzables = [t for t in pasos if t >= reloj + MARGEN_LLEGADA_MIN]
        if alcanzables:
            espera = min(alcanzables) - reloj
        else:
            espera = intervalo / 2 if intervalo else ESPERA_TRANSBORDO_MIN
        total += espera
        reloj += espera
    return total


def pasadas_en_parada(
    linea: str, parada: str, esperas: dict, red: dict, paradas: dict,
    reales: dict | None = None, intervalo: float | None = None,
) -> list[float]:
    """Minutes from now at which each bus of that line calls at that stop.

    The service reports **one single arrival per line and stop**, but that bus runs the
    whole line: if it calls at one stop in ten minutes, it reaches the next one in ten
    plus the ride. So one observation at any stop is good for every other stop on its
    line.

    This is what shows that two different stops put you on **the same vehicle**. Compared
    as separate waits, a far stop would appear to "wait less", and twice the walk would be
    proposed to end up on the same bus and arrive at the same time.

    Negative values are buses that have already gone past here. They are kept because
    adding the frequency to them gives the following ones.
    """
    seq = red.get(linea) or []
    if parada not in seq:
        return []
    aqui = seq.index(parada)
    vistas = []
    for otra, lineas in esperas.items():
        observada = lineas.get(linea)
        if observada is None or observada == math.inf or otra not in seq:
            continue
        alli = seq.index(otra)
        if alli == aqui:
            vistas.append(float(observada))
        elif alli < aqui:
            # The bus comes from there, so it reaches here later.
            vistas.append(observada + minutos_viaje(
                [_tramo_simple(linea, otra, parada)], red, paradas, reales))
        else:
            # It has already gone past here on its way there.
            vistas.append(observada - minutos_viaje(
                [_tramo_simple(linea, parada, otra)], red, paradas, reales))
    if not vistas:
        return []
    # Each observation also gives the following buses, one frequency apart.
    salida = set()
    for t in vistas:
        salida.add(round(t, 2))
        if intervalo:
            for n in range(1, 4):
                salida.add(round(t + intervalo * n, 2))
    return sorted(salida)


def _tramo_simple(linea: str, subir: str, bajar: str) -> dict:
    return {"linea": linea, "subir": subir, "bajar": bajar}


def _resolver_espera(
    linea: str, pasadas: list, hasta_la_parada: float, camina: bool,
    horarios: dict, tipo_dia: str | None, ahora_min: int | None,
) -> tuple:
    """How long the wait for the bus is, and what can be asserted about it.

    Returns (espera, tope, aviso). `espera` is minutes when a number can be supported.
    `tope` is the most it can take when the wait is unknown but the frequency is not.
    `aviso` explains why there is no closed number.

    It receives **when each bus calls** at this stop, not only the next one, so the choice
    is to keep the first bus that can be reached in time. If one goes past before you can
    be there, the notice says so: you take the following one, not the announced one.
    """
    intervalo = None
    if horarios and tipo_dia and ahora_min is not None:
        if frec.en_servicio(horarios, linea, tipo_dia, ahora_min) is False:
            return None, None, "fuera_de_servicio"
        intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)

    if not pasadas:
        # Without live data the last bus is unknown, but the frequency bounds the
        # wait: never more than one full interval.
        return None, intervalo, "sin_datos"

    # The walking estimate is approximate, so the timing must not be cut so fine.
    listo = hasta_la_parada + (MARGEN_LLEGADA_MIN if camina else 0)
    alcanzables = [t for t in pasadas if t >= listo]
    if not alcanzables:
        return None, intervalo, "no_llegas"

    primera = min(alcanzables)
    if ahora_min is not None and horarios:
        if frec.en_servicio(horarios, linea, tipo_dia, int(ahora_min + primera)) is False:
            return None, None, "fuera_de_servicio"
    # If one goes past before you can be ready, that bus is missed, and it is worth saying so.
    perdido = any(0 <= t < listo for t in pasadas)
    return primera - hasta_la_parada, None, ("no_llegas" if perdido else None)


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
    reales: dict | None = None,
) -> list[dict]:
    """Orders the routes by estimated total time and filters out the much worse ones.

    The total is walk + wait + ride, with the transfer waits inside. `esperas` is keyed
    ({stop_id: {line: minutes}}), because each candidate origin has its own.
    `andando_origen` and `andando_destino` are {stop_id: km}. They are empty when the
    user picks the stops by hand and there is no walk to count.

    Each route is returned as {"tramos", "total_min", "viaje_min", "espera_min",
    "espera_max_min", "espera_transbordo_min", "andando_min", "aviso_espera"}.
    `total_min` is the sum and the single source of truth: the frontend
    draws it and does not recalculate it. Minutes are rounded, and None marks a value
    that is not known. Without coordinates nothing can be estimated, and the routes come
    back in planner order.
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

    # When each bus calls at each stop, computed once per line and stop, because it
    # repeats across very many routes.
    memoria: dict[tuple, list] = {}

    def pasadas(linea: str, parada: str) -> list:
        clave = (linea, parada)
        if clave not in memoria:
            intervalo = None
            if horarios and tipo_dia and ahora_min is not None:
                intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)
            memoria[clave] = pasadas_en_parada(
                linea, parada, esperas, red, paradas, reales, intervalo)
        return memoria[clave]

    puntuadas = []
    for ruta in rutas:
        subir = ruta[0]["subir"]
        bajar = ruta[-1]["bajar"]
        viaje = minutos_viaje(ruta, red, paradas, reales)
        km = (andando_origen.get(subir, 0.0) + andando_destino.get(bajar, 0.0)
              + km_entre_tramos(ruta, paradas))
        andando = minutos_andando(km)
        hasta_la_parada = minutos_andando(andando_origen.get(subir, 0.0))
        espera, tope, aviso = _resolver_espera(
            ruta[0]["linea"],
            pasadas(ruta[0]["linea"], subir),
            hasta_la_parada,
            subir in andando_origen,
            horarios or {}, tipo_dia, ahora_min,
        )
        # The transfer is reached after the walk TO THE FIRST STOP and the ride. The
        # walk at the destination happens after leaving the last bus, not before
        # boarding the second one. To count it here would advance the clock and pick
        # the wrong connecting bus.
        transbordo = _espera_en_transbordos(
            ruta, red, paradas, esperas, horarios or {}, tipo_dia, ahora_min,
            hasta_la_parada + (espera or 0), reales,
        )
        # Two totals on purpose: the floor that is shown and the estimate that
        # decides. See `Puntuada`.
        total = viaje + andando + (espera or 0) + transbordo
        comparable = viaje + andando + _espera_estimada(espera, tope) + transbordo
        puntuadas.append(Puntuada(
            total, comparable, viaje, espera, tope, andando, transbordo, aviso, ruta))

    if not puntuadas:
        return []
    # A line that does not run at this hour is not an alternative, so it is dropped. If
    # remain, they come back anyway, so the application can explain why instead of
    # saying there is no route, which would be false: there is one, but not now.
    circulan = [p for p in puntuadas if _circula(p)]
    puntuadas = circulan or puntuadas
    puntuadas.sort(key=_orden)
    # Duplicates are removed before the filter and the trim. Otherwise variants of the
    # same trip take the four slots and the good options are not seen.
    puntuadas = _sin_dominadas(
        _sin_rodeos(_una_por_combinacion(_fusionar_por_paradas(puntuadas)))
    )
    mejor = puntuadas[0].comparable
    # The much worse routes are dropped first, and only then the list is trimmed.
    # Otherwise a good route can fall outside the limit because of another one that
    # is dropped later.
    aceptables = [p for p in puntuadas if p.comparable <= mejor * FACTOR_INFUMABLE]
    return [
        {
            "tramos": p.ruta,
            # With an unknown wait the total is a floor, not a promise: the frontend
            # says so ("from X"), and `aviso_espera` explains why.
            "total_min": round(p.total),
            "viaje_min": round(p.viaje),
            "espera_min": round(p.espera) if p.espera is not None else None,
            # The most it can take when the wait is unknown but the frequency is not.
            "espera_max_min": round(p.tope) if p.tope is not None else None,
            # The wait at the transfers, already inside the total.
            "espera_transbordo_min": round(p.transbordo) if p.transbordo else None,
            "andando_min": round(p.andando) if hay_caminata else None,
            "aviso_espera": p.aviso,
        }
        for p in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """From paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
