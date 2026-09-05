import json
import math
import re
from pathlib import Path
from typing import NamedTuple

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
# Lo que se supone que se espera un bus del que no se sabe nada y cuya frecuencia
# tampoco se publica. Es la mitad de la frecuencia mediana publicada (30 min), que es
# lo esperable al llegar a la parada en un momento cualquiera. No es un dato: es la
# alternativa menos mala a contar cero, que es lo unico que seguro esta mal.
ESPERA_SIN_DATO_MIN = 15

RADIO_TIERRA_KM = 6371.0


def distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en línea recta (haversine) entre dos (lat, lon), en kilómetros."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(h))


def cargar_shapes(data_dir: Path = DATA_DIR) -> dict:
    """La geometría de cada línea, o {} si no está el fichero."""
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
    """Metros de carretera entre paradas consecutivas: {(línea, a, b): km}.

    La distancia recta corregida por un factor fijo falla en las dos direcciones: se
    midió sobre 491 tramos y la sinuosidad real va de 0,95 a 2,19, con mediana 1,10
    frente al 1,30 que se aplicaba a todos. En los tramos rectos sobraba tiempo y en
    los revirados faltaban minutos, que es lo grave porque hace perder transbordos.

    La geometría ya está descargada, así que la distancia se puede medir en lugar de
    suponerla. Se calcula una vez: recorrer los trazados en cada consulta sería caro.
    """
    reales: dict[tuple, float] = {}
    for linea, seq in red.items():
        for sentido in (shapes.get(linea) or {}).values():
            pts = _puntos(sentido)
            if len(pts) < 2:
                continue
            # El punto del trazado más cercano a cada parada, una vez por parada.
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
                # Un trazado mal alineado puede dar disparates: se descarta lo imposible.
                if recta > 0 and recta <= km <= recta * 3:
                    reales[(linea, a, b)] = km
    return reales


def minutos_viaje(
    ruta: list[dict], red: dict, paradas: dict, reales: dict | None = None
) -> float:
    """Minutos de trayecto estimados, a velocidad comercial media.

    Con `reales` se usa la distancia de carretera medida del trazado de la línea. Sin
    ella se cae a la recta entre paradas corregida por un factor fijo, que es peor pero
    no necesita la geometría descargada.

    Se ignoran las paradas sin coordenadas y se suma entre las que quedan,
    en orden.

    Nota: los índices se resuelven por la PRIMERA aparición de cada parada
    en la secuencia de la línea, siguiendo la misma convención que usa el
    planificador al construir tramos. Por eso, en líneas de ida y vuelta
    (que repiten paradas), un tramo del retorno puede medirse con más
    paradas intermedias de las ideales.
    """
    reales = reales or {}
    km = 0.0
    for tramo in ruta:
        linea = tramo["linea"]
        seq = red[linea]
        i = seq.index(tramo["subir"])
        j = i + 1 + seq[i + 1:].index(tramo["bajar"])
        # Las paradas sin coordenadas se puentean: se mide de la anterior a la
        # siguiente, que es mejor aproximación que descontar ese trozo del viaje.
        entre = [s for s in seq[i:j + 1] if s in paradas]
        for a, b in zip(entre, entre[1:], strict=False):
            medida = reales.get((linea, a, b))
            if medida is not None:
                km += medida
            else:
                # Sin geometría de ese tramo, la recta corregida es lo que hay.
                km += distancia_km(paradas[a], paradas[b]) * FACTOR_SINUOSIDAD
    return km / VELOCIDAD_COMERCIAL_KMH * 60


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


class Puntuada(NamedTuple):
    """Una ruta ya medida, con **dos** totales, que no son el mismo numero.

    `total` es lo que se ensena. Con la espera desconocida es un suelo, y la tarjeta lo
    dice ("desde X min"): no se afirma lo que no se sabe.

    `comparable` es lo que decide el orden, quien domina a quien y que se descarta por
    ser mucho peor. Ahi el suelo no vale: contar cero cuando no se sabe la espera hace
    que la ruta peor conocida gane siempre, porque cero es el mejor numero posible. Una
    ruta con "hasta 20 min de espera" llegaba a borrar de la pantalla otra de 15
    minutos ciertos. La estimacion sigue la regla que ya se usaba en los transbordos:
    media frecuencia si se publica, y si no una cifra fija.
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
    """Lo que se espera de verdad, para comparar. Nunca cero por no saberlo."""
    if espera is not None:
        return espera
    return tope / 2 if tope else ESPERA_SIN_DATO_MIN


def _orden(p: Puntuada) -> tuple:
    """Por tiempo estimado, y a igualdad de tiempo menos transbordos.

    El desempate no es cosmetico: sin el, "coge la M4 y luego otro bus" puede colarse
    por delante de la M4 a secas y la regla que descarta rodeos no llega a verla.
    """
    return (p.comparable, len(p.ruta))


def _circula(p: Puntuada) -> bool:
    return p.aviso != "fuera_de_servicio"


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
    """Quita las rutas a las que otra gana en todo lo que importa.

    Si otra llega antes, te hace andar menos y con menos transbordos, esta no es una
    alternativa: no hay a quien le convenga. Descartarlas no exige decidir cuanto vale
    andar frente a esperar, que seria opinable; basta con que otra le gane en las tres.

    Se compara con `comparable`, no con lo que se ensena. Y una ruta cuya espera no se
    sabe **no puede descartar a una que si la sabe**, por buena que salga su estimacion:
    eso seria borrar una certeza apoyandose en una suposicion. Puede ir delante, que es
    lo que dice el valor esperado, pero la otra se sigue ofreciendo.
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
    """Quita las rutas que son otra mas corta con buses de propina.

    Si la M2 sola te deja, "M2 y luego otro bus" no es una alternativa: llegas mas
    tarde al mismo sitio. Llegan ordenadas por tiempo, asi que cualquier ruta que
    empiece por una ya aceptada es peor por definicion.
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
    """Una sola ruta por combinación de líneas: la más rápida.

    La misma combinación cogida en otra parada es el mismo viaje andando de más, no
    una alternativa. Llegan ordenadas por tiempo, así que la primera es la buena.
    """
    vistas: dict[tuple, Puntuada] = {}
    for p in puntuadas:
        # Por el CONJUNTO de lineas de cada tramo: tras fusionar alternativas, "C2 o 5"
        # y "5 o C2" son el mismo viaje aunque cambie cual figura primero.
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
        reloj += minutos_viaje([anterior], red, paradas, reales)
        if anterior["bajar"] != tramo["subir"]:
            # El transbordo es andando: hay que llegar antes de poder subir.
            reloj += minutos_andando(km_entre_tramos([anterior, tramo], paradas))
        linea = tramo["linea"]
        intervalo = None
        if horarios and tipo_dia and ahora_min is not None:
            intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)
        # Igual que al salir: se mira cuándo pasa cada autobús por esta parada, no solo
        # el anunciado, y se coge el primero al que se llega a tiempo.
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
    """Minutos desde ahora en que pasa cada autobús de esa línea por esa parada.

    El servicio informa de **una sola llegada por línea y parada**, pero ese autobús
    recorre la línea entera: si pasa por una parada dentro de diez minutos, llega a la
    siguiente diez más el trayecto. Así una observación en cualquier parada vale para
    todas las demás de su línea.

    Esto es lo que permite ver que dos paradas distintas te suben **al mismo vehículo**.
    Comparando esperas sueltas parecía que una parada lejana "esperaba menos", y se
    proponía andar el doble para acabar en el mismo autobús y llegar a la misma hora.

    Los valores negativos son buses que ya pasaron por aquí; se conservan porque sumando
    la frecuencia dan los siguientes.
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
            # El bus viene de allí: llega aquí más tarde.
            vistas.append(observada + minutos_viaje(
                [_tramo_simple(linea, otra, parada)], red, paradas, reales))
        else:
            # Ya pasó por aquí camino de allí.
            vistas.append(observada - minutos_viaje(
                [_tramo_simple(linea, parada, otra)], red, paradas, reales))
    if not vistas:
        return []
    # De cada observación salen también los buses siguientes, una frecuencia aparte.
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
    """Cuánto se espera al bus, y qué se puede afirmar de ello.

    Devuelve (espera, tope, aviso). `espera` son minutos cuando se sostienen; `tope` es
    lo más que puede tardar cuando no se sabe la espera pero sí cada cuánto pasa; y
    `aviso` explica por qué no hay un número cerrado.

    Recibe **cuándo pasa cada autobús** por esta parada, no solo el próximo, así que
    elegir es quedarse con el primero al que se llega a tiempo. Si alguno pasó antes de
    que pudieras estar allí, se dice: coges el siguiente, no el anunciado.
    """
    intervalo = None
    if horarios and tipo_dia and ahora_min is not None:
        if frec.en_servicio(horarios, linea, tipo_dia, ahora_min) is False:
            return None, None, "fuera_de_servicio"
        intervalo = frec.intervalo_min(horarios, linea, tipo_dia, ahora_min)

    if not pasadas:
        # Sin dato en vivo no se sabe cuándo pasó el último, pero la frecuencia acota
        # la espera: nunca más de una vuelta.
        return None, intervalo, "sin_datos"

    # La estimación a pie es aproximada, así que no vale apurar al minuto.
    listo = hasta_la_parada + (MARGEN_LLEGADA_MIN if camina else 0)
    alcanzables = [t for t in pasadas if t >= listo]
    if not alcanzables:
        return None, intervalo, "no_llegas"

    primera = min(alcanzables)
    if ahora_min is not None and horarios:
        if frec.en_servicio(horarios, linea, tipo_dia, int(ahora_min + primera)) is False:
            return None, None, "fuera_de_servicio"
    # Si había alguno antes de estar listo, ese se pierde y conviene decirlo.
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

    # Cuando pasa cada bus por cada parada, calculado una vez por linea y parada:
    # se repite en muchisimas rutas.
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
        # Al transbordo se llega tras andar HASTA LA PRIMERA PARADA y viajar; la
        # caminata del destino ocurre al bajarse del ultimo bus, no antes de subir al
        # segundo. Contarla aqui adelantaba el reloj y elegia mal el bus del enlace.
        transbordo = _espera_en_transbordos(
            ruta, red, paradas, esperas, horarios or {}, tipo_dia, ahora_min,
            hasta_la_parada + (espera or 0), reales,
        )
        # Dos totales a proposito: el suelo que se ensena y el estimado que decide.
        # Ver `Puntuada`.
        total = viaje + andando + (espera or 0) + transbordo
        comparable = viaje + andando + _espera_estimada(espera, tope) + transbordo
        puntuadas.append(Puntuada(
            total, comparable, viaje, espera, tope, andando, transbordo, aviso, ruta))

    if not puntuadas:
        return []
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
    mejor = puntuadas[0].comparable
    # Primero se descartan las mucho peores, y solo después se recorta: si no,
    # una ruta buena podría quedar fuera del límite por culpa de otra que luego
    # se descarta.
    aceptables = [p for p in puntuadas if p.comparable <= mejor * FACTOR_INFUMABLE]
    return [
        {
            "tramos": p.ruta,
            # Con la espera desconocida el total es un suelo, no una promesa: el
            # frontend lo dice ("desde X"), y `aviso_espera` explica por qué.
            "total_min": round(p.total),
            "viaje_min": round(p.viaje),
            "espera_min": round(p.espera) if p.espera is not None else None,
            # Lo más que puede tardar cuando no se sabe la espera pero sí la frecuencia.
            "espera_max_min": round(p.tope) if p.tope is not None else None,
            # Lo que se espera en los transbordos, ya dentro del total.
            "espera_transbordo_min": round(p.transbordo) if p.transbordo else None,
            "andando_min": round(p.andando) if hay_caminata else None,
            "aviso_espera": p.aviso,
        }
        for p in aceptables[:LIMITE_RUTAS]
    ]


def cargar_paradas(data_dir: Path = DATA_DIR) -> dict[str, tuple[float, float]]:
    """De paradas.json: {id: (lat, lon)}."""
    datos = json.loads((data_dir / "paradas.json").read_text(encoding="utf-8"))
    return {p["id"]: (p["lat"], p["lon"]) for p in datos}
