import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# How many ways to arrive are kept per stop during the search. To enumerate them all
# is exponential and, measured, it also gives a worse result: it fills the top places
# with variants of the same trip. To keep a few is faster and lets the real
# alternatives show.
CAMINOS_POR_PARADA = 8


def cargar_datos(data_dir: Path = DATA_DIR) -> tuple[dict, dict]:
    red = json.loads((data_dir / "red.json").read_text(encoding="utf-8"))
    dias = json.loads((data_dir / "dias.json").read_text(encoding="utf-8"))
    return red, dias


def _indexar(red: dict, activas) -> tuple[dict, dict, dict]:
    """Index of the active network: sequences, lines per stop and position in each line.

    `pos` holds the first occurrence of a stop in a line, which is what `list.index()`
    looks up, so the list is not walked on every query.
    """
    seq = {lin: red[lin] for lin in set(activas) if lin in red}
    por_parada: dict[str, set] = {}
    pos: dict[tuple, int] = {}
    for lin, paradas in seq.items():
        for i, parada in enumerate(paradas):
            por_parada.setdefault(parada, set()).add(lin)
            pos.setdefault((lin, parada), i)
    return seq, por_parada, pos


def _puntos_de_subida(parada: str, camino: tuple, vecinas: dict, pos: dict) -> list[str]:
    """Where you can board after you alight here: this stop, and the ones within a walk.

    **You do not walk to a stop that the bus you just left also calls at.** If it calls
    there earlier, walking to it undoes your own trip. If it calls there later, staying
    on board is enough. To walk two hundred metres to do what the bus does in two stops
    is not a route, and the planner prefers it, because it measures cost in stops
    ridden: to alight early looks cheaper.

    To cross the street is fine, because the two pavements are different stops and the
    direction you want can be the other one. What is dropped is the stop that is already
    on the route, not the one across from it.
    """
    puntos = [parada]
    if not vecinas or not camino:
        return puntos
    linea = camino[-1]["linea"]
    for otra, _km in vecinas.get(parada, ()):
        if pos.get((linea, otra)) is None:
            puntos.append(otra)
    return puntos


def planificar_muchos(
    origenes, destinos, red: dict, activas, max_transbordos: int = 2,
    vecinas: dict | None = None,
) -> list[list[dict]]:
    """Routes from any of `origenes` to any of `destinos`.

    The search runs in rounds, and each round is one more bus. A round walks the network
    once, whether you start from one stop or from seventy, so the cost does not grow
    with the number of origin-destination pairs. Each route is a list of legs
    {linea, subir, bajar}.
    """
    seq, por_parada, pos = _indexar(red, activas)
    destinos = set(destinos)
    hallado: dict[tuple, list] = {}
    etiquetas = {origen: [(origen, ())] for origen in origenes}

    for _ronda in range(max_transbordos + 1):
        siguiente: dict[str, list] = {}
        for parada, llegadas in etiquetas.items():
            for origen, camino in llegadas:
                for punto in _puntos_de_subida(parada, camino, vecinas, pos):
                    # Sorted: `por_parada` holds sets, and their order changes from
                    # one run to the next. With the cap per stop, that order decides
                    # which paths are kept, so the same query can give different
                    # results.
                    for lin in sorted(por_parada.get(punto, ())):
                        # Nobody takes the same line twice in one trip.
                        if any(t["linea"] == lin for t in camino):
                            continue
                        i = pos.get((lin, punto))
                        if i is None:
                            continue
                        for bajada in seq[lin][i + 1:]:
                            # To come back to the starting point is not a trip (circular lines).
                            if origen == bajada:
                                continue
                            ruta = (*camino, _tramo(lin, punto, bajada))
                            if bajada in destinos:
                                hallado.setdefault((origen, bajada), []).append(list(ruta))
                            cola = siguiente.setdefault(bajada, [])
                            if len(cola) < CAMINOS_POR_PARADA:
                                cola.append((origen, ruta))
        etiquetas = siguiente
        if not etiquetas:
            break

    return [ruta for rutas in hallado.values() for ruta in _mejores(rutas, seq)]


def planificar(
    origen: str, destino: str, red: dict, activas, max_transbordos: int = 2
) -> list[list[dict]]:
    """Routes from the origin stop to the destination stop with <= max_transbordos.

    Each route is a list of legs {linea, subir, bajar}. The best ones come back: fewer
    transfers first, then fewer stops. `activas` are the codes of the lines that run on
    the day queried.
    """
    if origen == destino:
        return []
    return planificar_muchos([origen], [destino], red, activas, max_transbordos)


def _tramo(linea: str, subir: str, bajar: str) -> dict:
    return {"linea": linea, "subir": subir, "bajar": bajar}


def _paradas_tramo(tramo: dict, seq: dict) -> int:
    s = seq[tramo["linea"]]
    i = s.index(tramo["subir"])
    return 1 + s[i + 1:].index(tramo["bajar"])


def _mejores(rutas: list, seq: dict, limite: int = 6) -> list:
    """The best routes between one specific origin and one specific destination.

    If you get there with fewer transfers, the longer options are surplus: nobody takes
    two buses where one takes them. Among the rest, the route through fewer stops is
    preferred, and the same combination of lines is not repeated.
    """
    if not rutas:
        return []
    minimo = min(len(ruta) for ruta in rutas)
    mejor: dict[tuple, tuple] = {}
    for ruta in rutas:
        if len(ruta) > minimo:
            continue
        # The cost is measured in stops ridden, and walking does not count: to
        # alight early and walk looks "cheaper" even for two hundred metres on foot.
        # So the same-stop transfer and the walking one do not compete here. The best
        # of each is kept, and the ranking decides, because it does know distances
        # and times.
        clave = (
            tuple(t["linea"] for t in ruta),
            tuple(a["bajar"] != b["subir"] for a, b in zip(ruta, ruta[1:], strict=False)),
        )
        coste = sum(_paradas_tramo(t, seq) for t in ruta)
        if clave not in mejor or coste < mejor[clave][0]:
            mejor[clave] = (coste, ruta)
    ordenadas = sorted(mejor.values(), key=lambda cr: (len(cr[1]), cr[0]))
    return [ruta for _, ruta in ordenadas[:limite]]
