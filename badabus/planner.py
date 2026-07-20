import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def cargar_datos(data_dir: Path = DATA_DIR) -> tuple[dict, dict]:
    red = json.loads((data_dir / "red.json").read_text(encoding="utf-8"))
    transbordos = json.loads((data_dir / "transbordos.json").read_text(encoding="utf-8"))
    return red, transbordos


def planificar(origen: str, destino: str, red: dict, transbordos: dict, max_transbordos: int = 2) -> list[list[dict]]:
    """Rutas de la parada origen a la parada destino con <= max_transbordos.

    Cada ruta es una lista de tramos {linea, subir, bajar}. Se devuelven las mejores
    (primero menos transbordos, luego menos paradas). Solo usa las líneas que circulan hoy.
    """
    if origen == destino:
        return []
    activas = set(transbordos.get("lineas", {}))
    seq = {lin: red[lin] for lin in activas if lin in red}
    por_parada: dict[str, set] = {}
    for lin, paradas in seq.items():
        for stop in paradas:
            por_parada.setdefault(stop, set()).add(lin)

    def alcanzables(lin, desde):
        s = seq[lin]
        try:
            i = s.index(desde)
        except ValueError:
            return []
        return s[i + 1:]

    def alcanza(lin, desde, hasta):
        return hasta in alcanzables(lin, desde)

    rutas: list[list[dict]] = []

    for l1 in por_parada.get(origen, ()):
        if alcanza(l1, origen, destino):
            rutas.append([_tramo(l1, origen, destino)])

    if not rutas and max_transbordos >= 1:
        for l1 in por_parada.get(origen, ()):
            for t1 in alcanzables(l1, origen):
                for l2 in por_parada.get(t1, ()):
                    if l2 != l1 and alcanza(l2, t1, destino):
                        rutas.append([_tramo(l1, origen, t1), _tramo(l2, t1, destino)])

    if not rutas and max_transbordos >= 2:
        for l1 in por_parada.get(origen, ()):
            for t1 in alcanzables(l1, origen):
                for l2 in por_parada.get(t1, ()):
                    if l2 == l1:
                        continue
                    for t2 in alcanzables(l2, t1):
                        for l3 in por_parada.get(t2, ()):
                            if l3 not in (l1, l2) and alcanza(l3, t2, destino):
                                rutas.append([
                                    _tramo(l1, origen, t1),
                                    _tramo(l2, t1, t2),
                                    _tramo(l3, t2, destino),
                                ])

    return _mejores(rutas, seq)


def _tramo(linea: str, subir: str, bajar: str) -> dict:
    return {"linea": linea, "subir": subir, "bajar": bajar}


def _paradas_tramo(tramo: dict, seq: dict) -> int:
    s = seq[tramo["linea"]]
    i = s.index(tramo["subir"])
    return 1 + s[i + 1:].index(tramo["bajar"])


def _mejores(rutas: list, seq: dict, limite: int = 6) -> list:
    mejor: dict[tuple, tuple] = {}
    for ruta in rutas:
        clave = tuple(t["linea"] for t in ruta)
        coste = sum(_paradas_tramo(t, seq) for t in ruta)
        if clave not in mejor or coste < mejor[clave][0]:
            mejor[clave] = (coste, ruta)
    ordenadas = sorted(mejor.values(), key=lambda cr: (len(cr[1]), cr[0]))
    return [ruta for _, ruta in ordenadas[:limite]]
