import json
import re
from collections.abc import Callable
from pathlib import Path

from badabus import bus_data_api as api


def collect(fetch: Callable[..., bytes] = api.fetch) -> tuple[list[dict], dict, dict]:
    """Descarga líneas y sus paradas; devuelve (paradas únicas, meta de líneas, recorridos).

    - paradas: dedup por stop_code, con las líneas que la sirven.
    - meta: {lin: {color, nombre}}.
    - red: {lin: [stop_code en orden de recorrido]}.
    """
    lineas = api.fetch_json("lineas", fetch=fetch)
    by_code: dict[str, dict] = {}
    red: dict[str, list[str]] = {}
    for linea in lineas:
        try:
            paradas = api.fetch_json("paradas", fetch=fetch, linea=linea["id"])
        except (OSError, ValueError) as exc:
            print(f"  ! fallo en línea {linea['id']}: {exc}")
            continue
        red[linea["lin"]] = [
            p["stop_code"] for p in sorted(paradas, key=lambda p: int(p["secuencia"]))
        ]
        for p in paradas:
            stop = by_code.setdefault(p["stop_code"], {
                "id": p["stop_code"],
                "nombre": p["stop_name"],
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "lineas": set(),
            })
            stop["lineas"].add(linea["lin"])
    stops = []
    for stop in by_code.values():
        stop["lineas"] = sorted(stop["lineas"], key=natural_key)
        stops.append(stop)
    meta = {
        linea["lin"]: {"color": "#" + linea["color_fondo"], "nombre": linea["descripcion"]}
        for linea in lineas
    }
    return stops, meta, red


def save_json(obj: list | dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    stops, meta, red = collect()
    save_json(stops, str(data_dir / "paradas.json"))
    save_json(meta, str(data_dir / "lineas.json"))
    save_json(red, str(data_dir / "red.json"))
    print(f"Guardadas {len(stops)} paradas, {len(meta)} líneas y {len(red)} recorridos en {data_dir}")


def natural_key(name: str) -> tuple[int, list[tuple[int, int, str]]]:
    parts = re.findall(r"\d+|\D+", name)
    key = [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts]
    lead = 0 if name[:1].isdigit() else 1
    return (lead, key)


if __name__ == "__main__":
    main()
