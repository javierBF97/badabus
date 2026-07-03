# badabus

Proyecto exploratorio, no oficial, sobre los datos del servicio de autobús urbano
de Badajoz.

## Requisitos
Python 3.10+ (solo biblioteca estándar; sin `pip install`).

## Estado
En desarrollo incremental. El uso y la arquitectura se documentarán aquí a
medida que se añadan las piezas.

## Exploración
Esta herramienta nace de explorar los datos del servicio de autobús urbano de
Badajoz. El servicio no publica una API documentada, pero su web de tiempos
consume una API JSON interna. Observando las trazas de red (DevTools → *Network*)
al usar la web se identificaron sus endpoints:

- `?action=lineas` — listado de líneas.
- `?action=paradas&linea=<id>` — paradas de una línea, en orden.
- `?action=tiempos&parada=<id>` — próximas llegadas a una parada (en vivo).
- `?action=correspondencias&linea=<id>` — transbordos por parada y tipo de día.

`badabus/bus_data_api.py` reproduce esas mismas peticiones GET.

## Uso
`badabus/collector.py` descarga las líneas y sus paradas y guarda la red en `data/`
(`paradas.json`, `lineas.json`, `red.json`). Para (re)generar los datos:
```
python -m badabus.collector
```

## Aviso
Herramienta personal que consume datos públicos del servicio de autobús urbano de
Badajoz. No es un producto oficial y no redistribuye sus datos. Uso responsable.
