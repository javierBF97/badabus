import datetime
from collections.abc import Callable

from badabus import bus_data_api as api

# Tipo de día por día de la semana (lunes=0). No distingue festivos.
TIPOS_SEMANA = ("LV", "LV", "LV", "LV", "LV", "SAB", "DOM")

_cache: tuple[datetime.date, str, str] | None = None


def tipo_dia_local(hoy: datetime.date | None = None) -> str:
    """Tipo de día por calendario, sin consultar el servicio. No distingue festivos."""
    return TIPOS_SEMANA[(hoy or datetime.date.today()).weekday()]


def tipo_dia_actual(
    fetcher: Callable[..., bytes] = api.fetch, hoy: datetime.date | None = None
) -> tuple[str, str]:
    """(tipo_dia, etiqueta) según el servicio, que sí distingue festivos.

    Se cachea por fecha local: dentro del mismo día la respuesta no cambia.
    """
    global _cache
    hoy = hoy or datetime.date.today()
    if _cache and _cache[0] == hoy:
        return _cache[1], _cache[2]
    lineas = api.fetch_json("lineas", fetcher=fetcher)
    if not lineas:
        raise ValueError("la API no devolvió líneas para consultar el tipo de día")
    tipo, etiqueta = api.fetch_dia(lineas[0]["id"], fetcher=fetcher)
    if not tipo:
        raise ValueError("la API no devolvió current_tipo_dia")
    _cache = (hoy, tipo, etiqueta)
    return tipo, etiqueta


def limpiar_cache() -> None:
    """Olvida el tipo de día cacheado (para los tests)."""
    global _cache
    _cache = None
