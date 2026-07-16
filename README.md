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

`badabus/bus_data_api.py` reproduce las peticiones GET de `lineas`, `paradas` y
`tiempos`. `correspondencias` se documenta como hallazgo, pero **no se usa**: los
transbordos se deducen de las líneas que pasan por cada parada.

Aparte de esa API, la **geometría de los recorridos** (trazados) vive en otro host:
la web de planos de línea consume `https://tubasa.eu/planos_de_lineas/datos/shape<id>.json`,
que devuelve la polilínea de una línea como array de puntos (`shape_pt_lat`,
`shape_pt_lon`, `sentido`). `badabus/bus_data_api.py` (`fetch_shape`) la baja y
`parse_shape` la agrupa por sentido para poder dibujar el trazado en el mapa.

## Uso
`badabus/collector.py` descarga líneas, paradas y trazados y guarda la red en `data/`
(`paradas.json`, `lineas.json`, `red.json`, `shapes.json`). Para (re)generar los datos:
```
python -m badabus.collector
```

## Servidor
`badabus/server.py` levanta un servidor local (`http.server`, escuchando solo en
`127.0.0.1`) con dos rutas:

- `GET /data/<paradas|lineas|red|shapes>.json` — sirve la red generada por el recolector.
- `GET /api/parada/<id>` — próximas llegadas a una parada (dato en vivo).

Arrancarlo:
```
python -m badabus.server
```

### El servidor actúa como proxy para evitar el CORS

```
[Navegador: página en localhost:8000]
        │  fetch("/api/parada/202")   ← MISMO origen (localhost:8000) → permitido sin más
        ▼
[Nuestro servidor Python en localhost:8000]
        │  urllib → https://tubasa.autobus.cloud/...   ← servidor→servidor, SIN navegador → sin CORS
        ▼
[API del servicio]  →  responde los datos  →  el servidor se los devuelve a la página
```

## Aviso
Herramienta personal que consume datos públicos del servicio de autobús urbano de
Badajoz. No es un producto oficial y no redistribuye sus datos. Uso responsable.
