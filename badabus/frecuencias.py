"""Cada cuánto pasa cada línea, a partir de los horarios publicados.

El endpoint de tiempos solo informa del **próximo** bus de cada línea. Cuando ese se
escapa, o cuando no hay dato, la espera queda en el aire. Sabiendo cada cuánto pasa la
línea se puede cerrar: el siguiente va una frecuencia después del que se pierde.

El fichero se transcribe a mano y no se distribuye con el proyecto (ver README). Si no
está, todo esto devuelve None y el resto sigue funcionando igual que antes.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FICHERO = "frecuencias.json"


def cargar(data_dir: Path = DATA_DIR) -> dict:
    """Los horarios publicados, o {} si el fichero no está o no se puede leer."""
    try:
        datos = json.loads((data_dir / FICHERO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos.get("lineas", {}) if isinstance(datos, dict) else {}


def _minutos(hhmm: str) -> int | None:
    """'07:30' -> 450. None si no es una hora."""
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _horario(frecuencias: dict, linea: str, tipo_dia: str) -> dict | None:
    entrada = frecuencias.get(linea)
    return entrada.get(tipo_dia) if isinstance(entrada, dict) else None


def en_servicio(frecuencias: dict, linea: str, tipo_dia: str, ahora_min: int) -> bool | None:
    """¿Circula esa línea a esa hora? None si no consta su horario.

    Distinguir "ya no pasa" de "no se sabe" evita decir "sin datos de paso" a las once
    de la noche, cuando lo cierto es que el servicio ha terminado.
    """
    horario = _horario(frecuencias, linea, tipo_dia)
    if not horario:
        return None
    desde, hasta = _minutos(horario.get("desde")), _minutos(horario.get("hasta"))
    if desde is None or hasta is None:
        return None
    return desde <= ahora_min <= hasta


def intervalo_min(frecuencias: dict, linea: str, tipo_dia: str, ahora_min: int) -> float | None:
    """Cada cuántos minutos pasa esa línea a esa hora. None si no consta.

    Los horarios vienen en tres formas: una frecuencia fija, tramos con frecuencias
    distintas a lo largo del día, u horas de salida sueltas. En los dos últimos casos
    se mira el tramo o el hueco que corresponde a la hora consultada.
    """
    horario = _horario(frecuencias, linea, tipo_dia)
    if not horario:
        return None

    tramos = horario.get("tramos")
    if isinstance(tramos, dict):
        intervalos = [
            i for lista in tramos.values()
            for i in [_intervalo_de_tramo(lista, ahora_min)] if i is not None
        ]
        if intervalos:
            # Varias cabeceras cubren la misma línea; la que más tarda manda, para no
            # prometer una espera más corta de la que puede tocar.
            return max(intervalos)

    salidas = horario.get("salidas")
    if isinstance(salidas, dict):
        huecos = [h for lista in salidas.values()
                  if (h := _hueco_entre_salidas(lista, ahora_min)) is not None]
        if huecos:
            return max(huecos)

    frecuencia = horario.get("frecuencia_min")
    if isinstance(frecuencia, (int, float)):
        return float(frecuencia)
    if isinstance(frecuencia, list) and frecuencia:
        # Sin tramos que desambigüen, se toma la peor de las frecuencias posibles.
        return float(max(frecuencia))
    return None


def _intervalo_de_tramo(tramos: list, ahora_min: int) -> float | None:
    """El intervalo del tramo horario que contiene a `ahora_min`."""
    if not isinstance(tramos, list):
        return None
    for tramo in tramos:
        if not isinstance(tramo, dict):
            continue
        desde, hasta = _minutos(tramo.get("desde")), _minutos(tramo.get("hasta"))
        if desde is None or hasta is None or not (desde <= ahora_min <= hasta):
            continue
        minutos = tramo.get("minutos")
        if isinstance(minutos, list) and minutos:
            # Salidas repartidas en la hora: tres salidas son una cada veinte minutos.
            return 60.0 / len(minutos)
        salidas = tramo.get("salidas")
        if isinstance(salidas, list):
            return _hueco_entre_salidas(salidas, ahora_min)
    return None


def _hueco_entre_salidas(salidas: list, ahora_min: int) -> float | None:
    """Minutos entre las dos salidas que rodean a `ahora_min`."""
    if not isinstance(salidas, list):
        return None
    horas = sorted(m for s in salidas if (m := _minutos(s)) is not None)
    if len(horas) < 2:
        return None
    for anterior, siguiente in zip(horas, horas[1:], strict=False):
        if anterior <= ahora_min <= siguiente:
            return float(siguiente - anterior)
    # Fuera del rango de salidas: el hueco típico es lo más honesto que se puede decir.
    huecos = [b - a for a, b in zip(horas, horas[1:], strict=False)]
    return float(max(huecos)) if huecos else None
