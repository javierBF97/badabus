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

## Cómo se buscan las rutas

Esta parte se ha medido más que decidido, y conviene dejar constancia de lo que se probó,
porque casi nada salió como se esperaba.

El planificador buscaba un par origen-destino cada vez. Mientras solo se miraban las cuatro
paradas más cercanas iba sobrado, pero cuatro paradas juntas suelen ser de las mismas
líneas, así que había líneas que no se consideraban nunca: la parada de una línea a 500 m
podía ser la vigésima más próxima y no entrar jamás en la búsqueda. Al ampliar a todas las
de 1 km, los pares pasaron a ser miles y el coste se disparó a **2.700 ms**.

Se probaron tres caminos:

- **Desde todos los orígenes a la vez, enumerando todas las rutas.** Salió peor:
  **15.000 ms**, y encima con resultados de menos calidad. Al enumerarlo todo, las primeras
  posiciones se llenaban de variantes del mismo viaje y las opciones buenas desaparecían.
- **Hacia atrás, partiendo del destino.** Más rápido cuando el destino tiene menos paradas
  que el origen (6 ms frente a 11), pero invirtiendo los extremos gana la búsqueda normal.
  Ganar siempre exige mantener las dos direcciones, y son milisegundos que no se notan.
- **Por rondas, recordando solo unas pocas formas de llegar a cada parada.** Una ronda es
  un bus más y recorre la red una sola vez, se salga de una parada o de setenta. **25 ms**
  en el peor caso.

Se quedó la tercera. Lo interesante es que recordar pocos caminos no es un mal menor que se
acepta a cambio de velocidad: **da mejor resultado que enumerarlo todo**, porque no ahoga
las alternativas buenas entre variantes de un mismo viaje.

Después apareció otro cuello de botella, este de cosecha propia: los tiempos en vivo se
pedían parada por parada y en fila, así que con setenta paradas eran **8 segundos**. Se
piden solo donde alguna ruta hace subir, y todas a la vez: **medio segundo**.

Por último, de 216 rutas encontradas en una consulta real, **195 eran la misma combinación
de líneas cogida en otra parada**. Se deja una por combinación, la más rápida. Y cuando dos
líneas recorren exactamente el mismo tramo, en lugar de descartar una se enseñan las dos:
sirve la primera que pase, y saberlo acorta la espera.

## Lo que no se sabe, no se inventa

El servicio da **una sola llegada por línea y parada**: cuándo pasa el siguiente bus no lo
dice nadie. Eso obliga a distinguir tres situaciones en lugar de dar siempre un número:

- **Se sabe y da tiempo a llegar**: se muestra el total completo, con la espera dentro.
- **Se sabe pero no da tiempo**: si el bus pasa antes de que termines de andar hasta la
  parada, ese bus no es el tuyo, y cuándo pasa el siguiente es desconocido.
- **No hay dato de paso**: igual, la espera no se sabe.

En los dos últimos casos se muestra **"desde X min"** —el suelo real, andar más bus— y se
explica por qué. Contar esa espera como cero era lo cómodo, pero premiaba precisamente a las
rutas peor conocidas: en una consulta real, **el 54 % de las rutas llevaba un total que no se
sostenía**, y las cuatro primeras que se ofrecían eran todas de ese grupo.

Las rutas se siguen mostrando aunque no llegues al próximo bus. La ruta puede ser buena; lo
que falta es el dato, y decirlo es más útil que esconderla o que fingir un número.

## Frecuencias de paso

El servicio no publica sus frecuencias en ninguna API: están en su web como **imágenes**, una
por línea, con la hora de inicio, la de fin, cada cuánto pasa y en qué minutos sale de
cabecera. Ese dato es lo único que permite estimar cuándo pasa el **siguiente** bus, porque el
endpoint de tiempos solo informa del próximo.

Por eso ese dato se transcribe a mano a **`data/frecuencias.json`**, que **no se incluye
aquí**: es del operador y este proyecto no lo redistribuye, igual que el resto de `data/`.
Quien quiera esa precisión lo crea con el formato de abajo.

**La aplicación funciona sin ese fichero.** Sin él las esperas quedan como desconocidas y las
tarjetas lo dicen ("desde X min · sin datos de paso"), que es el mismo camino que ya se sigue
cuando el dato en vivo falla. Con él, los tiempos se cierran.

Cada línea aparece en una de tres formas, según cómo publique el operador su horario:

```jsonc
{
  "lineas": {
    "EJEMPLO-1": {                      // frecuencia fija: lo más común
      "LV": { "desde": "07:00", "hasta": "23:20", "frecuencia_min": 20,
              "cabeceras": { "Cabecera Norte": [0, 20, 40] } }
    },
    "EJEMPLO-2": {                      // la frecuencia cambia durante el día
      "LV": { "desde": "07:00", "hasta": "23:10", "frecuencia_min": [15, 20],
              "tramos": { "Cabecera Norte": [
                { "desde": "07:00", "hasta": "13:00", "minutos": [0, 15, 30, 45] },
                { "desde": "13:00", "hasta": "23:00", "minutos": [0, 20, 40] }
              ] } }
    },
    "EJEMPLO-3": {                      // sin patrón: horas de salida sueltas
      "LV": { "desde": "06:30", "hasta": "22:45",
              "salidas": { "Cabecera Norte": ["06:30", "08:00", "09:30"] } }
    }
  }
}
```

Cada línea se indexa por tipo de día (`LV`, `SAB`, `DOM`), como `dias.json`. El fichero dice
**qué horario sigue una línea cuando circula**; de si circula hoy sigue respondiendo el dato en
vivo, que es más fiable: algunas líneas solo salen ciertos domingos y eso no se modela.

Se publican como imágenes sin número de versión, así que **caduca sin avisar**. El campo
`transcrito` guarda la fecha en que se copió.

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
