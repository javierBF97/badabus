import datetime
from collections.abc import Callable

from badabus import bus_data_api as api

# Day type by weekday (Monday=0). It does not tell holidays apart.
TIPOS_SEMANA = ("LV", "LV", "LV", "LV", "LV", "SAB", "DOM")

_cache: tuple[datetime.date, str, str] | None = None


def tipo_dia_local(hoy: datetime.date | None = None) -> str:
    """Day type from the calendar, without asking the service. It does not tell holidays apart."""
    return TIPOS_SEMANA[(hoy or datetime.date.today()).weekday()]


def tipo_dia_actual(
    fetcher: Callable[..., bytes] = api.fetch, hoy: datetime.date | None = None
) -> tuple[str, str]:
    """(tipo_dia, label) from the service, which does tell holidays apart.

    It is cached by local date: within the same day the answer does not change.
    """
    global _cache
    hoy = hoy or datetime.date.today()
    if _cache and _cache[0] == hoy:
        return _cache[1], _cache[2]
    lineas = api.fetch_json("lineas", fetcher=fetcher)
    if not lineas:
        raise ValueError("the API returned no lines to ask the day type for")
    tipo, etiqueta = api.fetch_dia(lineas[0]["id"], fetcher=fetcher)
    if not tipo:
        raise ValueError("the API returned no current_tipo_dia")
    _cache = (hoy, tipo, etiqueta)
    return tipo, etiqueta


def limpiar_cache() -> None:
    """Forgets the cached day type (for the tests)."""
    global _cache
    _cache = None
