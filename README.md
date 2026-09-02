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

`badabus/bus_data_api.py` reproduce las peticiones GET de `lineas`, `paradas`,
`tiempos` y `correspondencias`. De `correspondencias` se sacan **qué tipo de día es
hoy** (laborable, sábado o domingo/festivo) y **qué líneas circulan cada día**; los
transbordos de una ruta se deducen de las líneas que pasan por cada parada.

Aparte de esa API, la **geometría de los recorridos** (trazados) vive en otro host:
la web de planos de línea consume `https://tubasa.eu/planos_de_lineas/datos/shape<id>.json`,
que devuelve la polilínea de una línea como array de puntos (`shape_pt_lat`,
`shape_pt_lon`, `sentido`). `badabus/bus_data_api.py` (`fetch_shape`) la baja y
`parse_shape` la agrupa por sentido para poder dibujar el trazado en el mapa.

La duración de un trayecto se estima a partir de una velocidad medida de los propios
datos: cada llegada de `tiempos` trae los metros que le faltan al bus y los minutos que
tardará, así que `metros/minutos` da su velocidad comercial. Una muestra de decenas de
buses dio una mediana de ~20 km/h, que es la que usa el planificador para ordenar las
rutas, corregida por un factor de sinuosidad al pasar de la distancia en línea recta al
recorrido real.

El tiempo andando se estima con el mismo criterio: la distancia en línea recta corregida por
un factor de callejeo, porque el peatón tampoco atraviesa edificios. Sirve para ordenar
alternativas y dar una idea, no es un tiempo real de caminata.

## Direcciones
Nadie piensa un viaje en paradas: piensa en "quiero ir a Calle Menacho 12". Para traducir
una cosa en la otra se usa **Nominatim**, el geocodificador de OpenStreetMap, acotado a
Badajoz.

Se consulta **desde el servidor, nunca desde el navegador**. Su política de uso limita a una
petición por segundo, exige un `User-Agent` identificable y prohíbe expresamente el
autocompletado; por eso el buscador espera a que dejes de escribir, no consulta con menos de
cuatro caracteres y reutiliza lo ya buscado. Concentrarlo en el servidor permite cumplir todo
eso en un único sitio, igual que ya se hace de proxy con los tiempos.

Partiendo de una dirección, la parada más cercana no siempre es la mejor: a 90 m puede haber
una de una línea que va al lado contrario, y a 250 m otra que lleva directo. Por eso se
prueban varias paradas próximas y se deja que el ranking decida, con el tiempo andando ya
sumado al total.

## Uso
`badabus/collector.py` descarga líneas, paradas y trazados y guarda la red en `data/`
(`paradas.json`, `lineas.json`, `red.json`, `shapes.json`, `dias.json`). Para (re)generar los datos:
```
python -m badabus.collector
```

## Servidor
`badabus/server.py` levanta un servidor local (`http.server`) que por defecto solo
acepta conexiones de este equipo, con estas rutas:

- `GET /data/<paradas|lineas|red|shapes|dias>.json` — sirve la red generada por el recolector.
- `GET /api/parada/<id>` — próximas llegadas a una parada (dato en vivo).
- `GET /api/dia` — tipo de día vigente (laborable, sábado o domingo/festivo).
- `GET /api/plan?origen=<id>&destino=<id>` — rutas entre dos paradas, con transbordos si hacen
  falta, ordenadas por tiempo estimado y con la espera del próximo bus. Cada extremo acepta
  también coordenadas (`origen_lat`/`origen_lon`), para partir de una dirección o de un punto
  del mapa en vez de una parada.
- `GET /api/buscar?q=<texto>` — direcciones de Badajoz que coinciden con el texto.
- `GET /api/direccion?lat=<lat>&lon=<lon>` — nombre del sitio que hay en unas coordenadas.
- `GET /api/config` — ajustes que el navegador necesita y no viven en el código.

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

## Configuración
Los ajustes locales van en un `.env` en la raíz, que no se sube al repositorio. `.env.example`
lista los disponibles:

- `CARTO_API_KEY` — clave gratuita de los mapas base. Sin ella el mapa funciona igual, pero
  se ve con marca de agua.
- `BADABUS_HOST` — dirección en la que escucha el servidor. Sin tocarlo solo atiende a este
  equipo. Puesto a `0.0.0.0` se abre a la red local, para probar la app desde el móvil, e
  imprime al arrancar la dirección a la que conectarse. Hazlo solo en redes de confianza:
  queda expuesta a quien esté en esa red.

## Aviso
Herramienta personal que consume datos públicos del servicio de autobús urbano de
Badajoz. No es un producto oficial y no redistribuye sus datos. Uso responsable.
