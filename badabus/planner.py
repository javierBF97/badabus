import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Cuántas formas de llegar se recuerdan por parada mientras se busca. Enumerarlas
# todas es exponencial y, medido, además empeora el resultado: llena las mejores
# posiciones con variantes del mismo viaje. Recordar unas pocas es más rápido y
# deja ver alternativas de verdad.
CAMINOS_POR_PARADA = 4


def cargar_datos(data_dir: Path = DATA_DIR) -> tuple[dict, dict]:
    red = json.loads((data_dir / "red.json").read_text(encoding="utf-8"))
    dias = json.loads((data_dir / "dias.json").read_text(encoding="utf-8"))
    return red, dias


def _indexar(red: dict, activas) -> tuple[dict, dict, dict]:
    """Índice de la red activa: recorridos, líneas por parada y posición en cada línea.

    `pos` guarda la primera aparición de una parada en una línea, que es lo que
    miraba `list.index()`, para no recorrer la lista en cada consulta.
    """
    seq = {lin: red[lin] for lin in set(activas) if lin in red}
    por_parada: dict[str, set] = {}
    pos: dict[tuple, int] = {}
    for lin, paradas in seq.items():
        for i, parada in enumerate(paradas):
            por_parada.setdefault(parada, set()).add(lin)
            pos.setdefault((lin, parada), i)
    return seq, por_parada, pos


def planificar_muchos(
    origenes, destinos, red: dict, activas, max_transbordos: int = 2
) -> list[list[dict]]:
    """Rutas desde cualquiera de `origenes` hasta cualquiera de `destinos`.

    Busca por rondas, y cada ronda es un bus más. Una ronda recorre la red una
    sola vez, salgan de una parada o de setenta, así que el coste no crece con el
    número de pares origen-destino. Cada ruta es una lista de tramos
    {linea, subir, bajar}.
    """
    seq, por_parada, pos = _indexar(red, activas)
    destinos = set(destinos)
    hallado: dict[tuple, list] = {}
    etiquetas = {origen: [(origen, ())] for origen in origenes}

    for _ronda in range(max_transbordos + 1):
        siguiente: dict[str, list] = {}
        for parada, llegadas in etiquetas.items():
            for lin in por_parada.get(parada, ()):
                i = pos.get((lin, parada))
                if i is None:
                    continue
                # Nadie coge dos veces la misma línea en un viaje.
                utiles = [(o, c) for o, c in llegadas if all(t["linea"] != lin for t in c)]
                if not utiles:
                    continue
                for bajada in seq[lin][i + 1:]:
                    for origen, camino in utiles:
                        # Volver al punto de partida no es un viaje (líneas circulares).
                        if origen == bajada:
                            continue
                        ruta = (*camino, _tramo(lin, parada, bajada))
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
    """Rutas de la parada origen a la parada destino con <= max_transbordos.

    Cada ruta es una lista de tramos {linea, subir, bajar}. Se devuelven las mejores
    (primero menos transbordos, luego menos paradas). `activas` son los códigos de las
    líneas que circulan el día consultado.
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
    """Las mejores rutas entre un origen y un destino concretos.

    Si se llega con menos transbordos, las opciones más largas sobran: nadie coge
    dos buses donde uno le deja. Entre las que quedan, se prefiere la que pasa por
    menos paradas y no se repite una misma combinación de líneas.
    """
    if not rutas:
        return []
    minimo = min(len(ruta) for ruta in rutas)
    mejor: dict[tuple, tuple] = {}
    for ruta in rutas:
        if len(ruta) > minimo:
            continue
        clave = tuple(t["linea"] for t in ruta)
        coste = sum(_paradas_tramo(t, seq) for t in ruta)
        if clave not in mejor or coste < mejor[clave][0]:
            mejor[clave] = (coste, ruta)
    ordenadas = sorted(mejor.values(), key=lambda cr: (len(cr[1]), cr[0]))
    return [ruta for _, ruta in ordenadas[:limite]]
