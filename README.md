# badabus

Proyecto exploratorio, no oficial, sobre los datos del servicio de autobús urbano
de Badajoz.

## Requisitos
Python 3.10+ (solo biblioteca estándar; sin `pip install`).

## Estado
En desarrollo incremental. El uso y la arquitectura se documentarán aquí a
medida que se añadan las piezas.

## Cómo funciona
El servicio de autobús urbano de Badajoz expone una API JSON (acciones `lineas`,
`paradas`, `tiempos`). `badabus/bus_data_api.py` es el cliente que la consulta.

## Aviso
Herramienta personal que consume datos públicos del servicio de autobús urbano de
Badajoz. No es un producto oficial y no redistribuye sus datos. Uso responsable.
