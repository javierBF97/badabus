"""How often each line runs, from the published timetables.

The arrivals endpoint reports only the **next** bus of each line. When that one is
missed, or when there is no data, the wait is left open. With the frequency of the line
it can be closed: the following bus comes one frequency after the one you miss.

The file is typed in by hand and is not distributed with the project (see the readme).
If it is not there, all of this returns None and the rest keeps working the same.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FICHERO = "frecuencias.json"


def cargar(data_dir: Path = DATA_DIR) -> dict:
    """The published timetables, or {} if the file is missing or cannot be read."""
    try:
        datos = json.loads((data_dir / FICHERO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos.get("lineas", {}) if isinstance(datos, dict) else {}


def _minutos(hhmm: str) -> int | None:
    """'07:30' -> 450. None if it is not a time."""
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _horario(frecuencias: dict, linea: str, tipo_dia: str) -> dict | None:
    entrada = frecuencias.get(linea)
    return entrada.get(tipo_dia) if isinstance(entrada, dict) else None


def en_servicio(frecuencias: dict, linea: str, tipo_dia: str, ahora_min: int) -> bool | None:
    """Does that line run at that hour? None if its timetable is not on record.

    To tell "it no longer runs" from "it is not known" avoids saying "no arrival data"
    at eleven at night, when the truth is that the service has finished.
    """
    horario = _horario(frecuencias, linea, tipo_dia)
    if not horario:
        return None
    desde, hasta = _minutos(horario.get("desde")), _minutos(horario.get("hasta"))
    if desde is None or hasta is None:
        return None
    return desde <= ahora_min <= hasta


def intervalo_min(frecuencias: dict, linea: str, tipo_dia: str, ahora_min: int) -> float | None:
    """Minutes between buses of that line at that hour. None if it is not on record.

    The timetables come in three forms: a fixed frequency, time bands with different
    frequencies through the day, or loose departure times. In the last two cases, the
    band or the gap that matches the hour queried is used.
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
            # Several termini cover the same line. The slowest one rules, so the
            # wait promised is never shorter than the one you can get.
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
        # With no bands to disambiguate, the worst possible frequency is taken.
        return float(max(frecuencia))
    return None


def _intervalo_de_tramo(tramos: list, ahora_min: int) -> float | None:
    """The interval of the time band that contains `ahora_min`."""
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
            # Departures spread over the hour: three departures are one every twenty minutes.
            return 60.0 / len(minutos)
        salidas = tramo.get("salidas")
        if isinstance(salidas, list):
            return _hueco_entre_salidas(salidas, ahora_min)
    return None


def _hueco_entre_salidas(salidas: list, ahora_min: int) -> float | None:
    """Minutes between the two departures that surround `ahora_min`."""
    if not isinstance(salidas, list):
        return None
    horas = sorted(m for s in salidas if (m := _minutos(s)) is not None)
    if len(horas) < 2:
        return None
    for anterior, siguiente in zip(horas, horas[1:], strict=False):
        if anterior <= ahora_min <= siguiente:
            return float(siguiente - anterior)
    # Outside the range of departures, the typical gap is the most honest answer.
    huecos = [b - a for a, b in zip(horas, horas[1:], strict=False)]
    return float(max(huecos)) if huecos else None
