(() => {
  "use strict";

  const CENTRO_BADAJOZ = [38.8794, -6.9707];
  const ZOOM_INICIAL = 14;
  const COLOR_HEX = /^#[0-9a-fA-F]{6}$/;
  const COLOR_FALLBACK = "#6b7280";
  const COLOR_BASE = "#1D9E75";
  const ALIAS_LINEA = { BGM1: "BG1", BGM2: "BG2" };
  // Why a closed total cannot be given. The wait for the next bus is never invented:
  // the service gives only one arrival per line.
  const AVISOS_ESPERA = {
    no_llegas: "aviso_no_llegas",
    sin_datos: "aviso_sin_datos",
    fuera_de_servicio: "aviso_fuera_de_servicio",
  };
  const BUSQUEDA_MIN_CARACTERES = 3;
  const BUSQUEDA_ESPERA_MS = 200;
  const BUSQUEDA_CACHE_MAX = 50;

  const CAPAS_TILES = {
    claro: { url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" },
    oscuro: { url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" },
  };
  const ATRIBUCION =
    '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>';

  let lineas = {};
  let paradas = [];
  let shapes = {};
  let claveMapa = "";
  let map;
  let capaTiles;
  let capaTrazado;
  let capaMarcadores;
  let paradaActual = null;
  let lineaSeleccionada = "";
  let lineaVistazo = "";
  let ultimasLlegadas = null;
  let popupActual = null;
  let avisoTimer = null;
  let peticionActual = 0;
  let cierreVistazoPendiente = null;
  let red = {};
  let dias = {};
  const paradaPorId = {};
  let capaRuta;
  let origenSel = null;
  let destinoSel = null;
  let modoMapa = null;
  let rutaActiva = null;
  let limitesEncuadre = null;
  let encuadreAutomatico = true;
  let encuadrando = false;
  let pendienteEncuadre = false;

  // ---------- Theme ----------

  function temaPreferido() {
    const guardado = localStorage.getItem("tema");
    if (guardado === "claro" || guardado === "oscuro") return guardado;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
  }

  async function cargarClaveMapa() {
    // Without a key the map shows a watermark, but the application works the same.
    try {
      const resp = await fetch("/api/config");
      if (resp.ok) claveMapa = (await resp.json()).carto_key || "";
    } catch (err) {
      /* sin ajustes: se usa el mapa sin clave */
    }
  }

  function urlTiles(tema) {
    const base = CAPAS_TILES[tema].url;
    return claveMapa ? `${base}?key=${encodeURIComponent(claveMapa)}` : base;
  }


  // ---------- Language ----------

  // A flat dictionary, key -> text. The variable pieces go in braces and t() replaces
  // them: a sentence can then be ordered differently in each language, which is exactly
  // what concatenating loose pieces does not allow.
  // Stop and street names are not translated: they are data, and in Badajoz a street
  // has the same name in both languages.
  const TEXTOS = {
    es: {
      buscar_parada_ph: "Buscar parada…",
      buscar_parada_aria: "Buscar parada",
      como_llegar: "Cómo llegar",
      lineas: "Líneas",
      parada_cercana: "Parada más cercana",
      // The button leads to the *other* language, so its label is in that other language.
      cambiar_idioma: "View in English",
      tema_claro: "Activar modo claro",
      tema_oscuro: "Activar modo oscuro",
      elegir_linea: "Elegir línea",
      elige_linea: "Elige una línea",
      cerrar: "Cerrar",
      origen: "Origen",
      destino: "Destino",
      invertir: "Invertir origen y destino",
      buscar_ruta: "Buscar ruta",
      todas: "Todas",
      quitar: "Quitar",
      parada_o_direccion_ph: "Parada o dirección…",
      buscar_origen_aria: "Buscar parada o dirección de origen",
      buscar_destino_aria: "Buscar parada o dirección de destino",
      en_el_mapa: "En el mapa",
      mas_cercana: "Más cercana",
      direcciones: "Direcciones",
      paradas: "Paradas",
      buscando_direcciones: "Buscando direcciones…",
      cargando: "Cargando…",
      sin_llegadas: "Sin llegadas próximas.",
      error_tiempos: "No se pudieron cargar los tiempos",
      reintentar: "Reintentar",
      llegada_ya: "Próximo",
      sin_geo: "La geolocalización no está disponible en este dispositivo.",
      buscando_ubicacion: "Buscando tu ubicación…",
      sin_parada_cerca: "No se encontró ninguna parada cercana.",
      sin_ubicacion: "No se pudo obtener tu ubicación.",
      parada_sin_mapa: "Esa parada no tiene ubicación en el mapa.",
      toca_origen: "Toca la parada de origen en el mapa",
      toca_destino: "Toca la parada de destino en el mapa",
      elige_extremos: "Elige origen y destino.",
      buscando_ruta: "Buscando ruta…",
      fuera_de_red: "Esa dirección no tiene paradas cerca.",
      sin_datos_paradas: "Faltan los datos de paradas. Recarga la página.",
      error_ruta: "No se pudo calcular la ruta.",
      sin_ruta: "No se encontró ruta (prueba con otras paradas).",
      error_datos_mapa: "No se pudieron cargar los datos del mapa. Recarga la página.",
      transbordo_en: "↕ transbordo en {parada}",
      baja_y_anda: "↕ baja en {a} y anda hasta {b}{cuanto}",
      directo: "Directo",
      transbordo_1: "1 transbordo",
      transbordos_n: "{n} transbordos",
      total_aprox: "~{n} min",
      total_desde: "desde {n} min",
      min_andando: "{n} min andando",
      proximo_linea: "próximo {linea} en {n} min",
      siguiente_linea: "siguiente {linea} en {n} min",
      espera_max: "hasta {n} min de espera",
      espera_transbordo: "{n} min de transbordo",
      aviso_no_llegas: "no te da tiempo a coger el próximo",
      aviso_sin_datos: "sin datos de paso ahora mismo",
      aviso_fuera_de_servicio: "esa línea ya no pasa a estas horas",
      apie_gana: "Andando, y llegas antes",
      apie_alternativa: "O puedes ir andando",
    },
    en: {
      buscar_parada_ph: "Search stop…",
      buscar_parada_aria: "Search stop",
      como_llegar: "Directions",
      lineas: "Lines",
      parada_cercana: "Nearest stop",
      cambiar_idioma: "Ver en español",
      tema_claro: "Switch to light mode",
      tema_oscuro: "Switch to dark mode",
      elegir_linea: "Choose line",
      elige_linea: "Choose a line",
      cerrar: "Close",
      origen: "From",
      destino: "To",
      invertir: "Swap start and destination",
      buscar_ruta: "Find route",
      todas: "All",
      quitar: "Remove",
      parada_o_direccion_ph: "Stop or address…",
      buscar_origen_aria: "Search starting stop or address",
      buscar_destino_aria: "Search destination stop or address",
      en_el_mapa: "On the map",
      mas_cercana: "Nearest",
      direcciones: "Addresses",
      paradas: "Stops",
      buscando_direcciones: "Searching addresses…",
      cargando: "Loading…",
      sin_llegadas: "No arrivals due.",
      error_tiempos: "Could not load arrival times",
      reintentar: "Try again",
      llegada_ya: "Due",
      sin_geo: "Location is not available on this device.",
      buscando_ubicacion: "Finding your location…",
      sin_parada_cerca: "No stop found nearby.",
      sin_ubicacion: "Could not get your location.",
      parada_sin_mapa: "That stop has no place on the map.",
      toca_origen: "Tap the starting stop on the map",
      toca_destino: "Tap the destination stop on the map",
      elige_extremos: "Choose where you start and where you are going.",
      buscando_ruta: "Finding a route…",
      fuera_de_red: "That address has no stops nearby.",
      sin_datos_paradas: "The stop data is missing. Reload the page.",
      error_ruta: "Could not work out a route.",
      sin_ruta: "No route found (try other stops).",
      error_datos_mapa: "Could not load the map data. Reload the page.",
      transbordo_en: "↕ change at {parada}",
      baja_y_anda: "↕ get off at {a} and walk to {b}{cuanto}",
      directo: "Direct",
      transbordo_1: "1 change",
      transbordos_n: "{n} changes",
      total_aprox: "~{n} min",
      total_desde: "from {n} min",
      min_andando: "{n} min walking",
      proximo_linea: "next {linea} in {n} min",
      siguiente_linea: "the {linea} after that in {n} min",
      espera_max: "up to {n} min waiting",
      espera_transbordo: "{n} min to change",
      aviso_no_llegas: "you cannot make the next one",
      aviso_sin_datos: "no arrival data right now",
      aviso_fuera_de_servicio: "that line no longer runs at this hour",
      apie_gana: "On foot, and you get there sooner",
      apie_alternativa: "Or you can walk",
    },
  };

  let idioma = idiomaGuardado();
  let ultimasRutas = null;
  let ultimoAPie = null;

  function idiomaGuardado() {
    const guardado = localStorage.getItem("idioma");
    if (guardado === "es" || guardado === "en") return guardado;
    return String(navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es";
  }

  function t(clave, datos) {
    const tabla = TEXTOS[idioma] || TEXTOS.es;
    let texto = tabla[clave] != null ? tabla[clave] : TEXTOS.es[clave];
    if (texto == null) return clave;
    if (datos) {
      for (const nombre of Object.keys(datos)) {
        texto = texto.replaceAll("{" + nombre + "}", datos[nombre]);
      }
    }
    return texto;
  }

  // The service returns its arrival text in Spanish ("PRÓXIMO", "5 min"). In English
  // it is rewritten from the minutes, which is the only data it carries inside. If they
  // cannot be read, the text is left as it is rather than invent something else.
  function textoLlegada(tiempo) {
    const bruto = String(tiempo || "");
    if (idioma === "es" || !bruto) return bruto;
    const minutos = minutosDe(bruto);
    if (minutos === 0) return t("llegada_ya");
    return Number.isFinite(minutos) ? minutos + " min" : bruto;
  }

  function aplicarIdioma(nuevo) {
    idioma = nuevo;
    document.documentElement.lang = idioma;
    localStorage.setItem("idioma", idioma);
    for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
    for (const el of document.querySelectorAll("[data-i18n-aria]")) {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
    }
    for (const el of document.querySelectorAll("[data-i18n-ph]")) el.placeholder = t(el.dataset.i18nPh);
    // The button shows the language it leads to, not the one in use.
    const chip = document.getElementById("lang-texto");
    if (chip) chip.textContent = idioma === "es" ? "EN" : "ES";
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      const oscuro = document.documentElement.dataset.theme === "oscuro";
      toggle.setAttribute("aria-label", t(oscuro ? "tema_claro" : "tema_oscuro"));
    }
    repintarLoDinamico();
  }

  // What JS draws carries no data-i18n, so it has to be redrawn. Only what is on
  // screen is redrawn: with no route searched there are no results to redraw.
  function repintarLoDinamico() {
    const texto = document.getElementById("btn-texto");
    if (texto && lineaSeleccionada) texto.textContent = lineaSeleccionada;
    const panel = document.getElementById("panel-comollegar");
    if (panel && !panel.hidden) {
      renderSelector("origen");
      renderSelector("destino");
    }
    if (ultimasRutas) renderRutas(ultimasRutas, ultimoAPie);
    if (paradaActual && ultimasLlegadas) {
      const filas = filasLlegadas(ultimasLlegadas);
      actualizarPopup(paradaActual, filas || `<div class="popup-estado">${t("sin_llegadas")}</div>`);
    }
  }

  function aplicarTema(tema) {
    document.documentElement.dataset.theme = tema;
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.setAttribute("aria-pressed", tema === "oscuro" ? "true" : "false");
      toggle.setAttribute("aria-label", t(tema === "oscuro" ? "tema_claro" : "tema_oscuro"));
    }
    if (map) {
      if (capaTiles) map.removeLayer(capaTiles);
      capaTiles = L.tileLayer(urlTiles(tema), { attribution: ATRIBUCION, maxZoom: 19 }).addTo(map);
    }
  }

  function alternarTema() {
    const actual = document.documentElement.dataset.theme === "oscuro" ? "oscuro" : "claro";
    const nuevo = actual === "oscuro" ? "claro" : "oscuro";
    localStorage.setItem("tema", nuevo);
    aplicarTema(nuevo);
  }

  // ---------- Helpers ----------

  function codigoLinea(texto) {
    const codigo = String(texto).replace(/^L[ÍI]NEA\s+/i, "").trim();
    return ALIAS_LINEA[codigo] || codigo;
  }

  function minutosDe(tiempo) {
    const texto = String(tiempo || "");
    const encontrado = texto.match(/\d+/);
    if (encontrado) return parseInt(encontrado[0], 10);
    if (/pr[óo]ximo/i.test(texto)) return 0;
    return Infinity;
  }

  function colorLinea(codigo) {
    const color = (lineas[codigo] || {}).color;
    return COLOR_HEX.test(color) ? color : COLOR_FALLBACK;
  }

  function conAlfa(hex, alfa) {
    const m = /^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/.exec(hex);
    if (!m) return "transparent";
    return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alfa})`;
  }

  function textoSobre(hex) {
    const m = /^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/.exec(hex);
    if (!m) return "#ffffff";
    const r = parseInt(m[1], 16) / 255;
    const g = parseInt(m[2], 16) / 255;
    const b = parseInt(m[3], 16) / 255;
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 ? "#111111" : "#ffffff";
  }

  function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = String(texto);
    return div.innerHTML.replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  function coordsValidas(parada) {
    return Number.isFinite(parada.lat) && Number.isFinite(parada.lon);
  }

  function haversine(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const toRad = (deg) => (deg * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function paradaMasCercana(lat, lon, listaParadas) {
    let mejor = null;
    let mejorDistancia = Infinity;
    for (const parada of listaParadas) {
      if (!coordsValidas(parada)) continue;
      const distancia = haversine(lat, lon, parada.lat, parada.lon);
      if (distancia < mejorDistancia) {
        mejorDistancia = distancia;
        mejor = parada;
      }
    }
    return mejor;
  }

  function mostrarAviso(mensaje) {
    const toast = document.getElementById("toast");
    toast.textContent = mensaje;
    toast.hidden = false;
    clearTimeout(avisoTimer);
    avisoTimer = setTimeout(() => { toast.hidden = true; }, 3500);
  }

  // ---------- Map and data ----------

  function crearMapa() {
    // zoomSnap in quarters: with whole levels the fit falls up to half short, because
    // it takes the last level that fits whole. The + and - buttons still step one at a
    // time (zoomDelta).
    map = L.map("map", { zoomSnap: 0.25 }).setView(CENTRO_BADAJOZ, ZOOM_INICIAL);
    capaTrazado = L.layerGroup().addTo(map);
    capaRuta = L.layerGroup().addTo(map);
    capaMarcadores = L.layerGroup().addTo(map);
    map.on("popupclose", alCerrarPopup);
    map.on("click", alClicarElMapa);
    vigilarElHueco();
  }

  function alCerrarPopup(evento) {
    if (evento.popup !== popupActual) return;
    paradaActual = null;
    ultimasLlegadas = null;
    popupActual = null;
    // Deferred close: if another popup opens right away (a stop change), the preview is kept.
    clearTimeout(cierreVistazoPendiente);
    cierreVistazoPendiente = setTimeout(() => {
      if (popupActual) return;
      if (lineaVistazo) {
        lineaVistazo = "";
        refrescarMarcadores();
        dibujarTrazado();
      } else if (lineaSeleccionada) {
        refrescarMarcadores();
      }
    }, 0);
  }

  function refrescarMarcadores() {
    capaMarcadores.clearLayers();
    for (const parada of paradas) {
      if (!coordsValidas(parada)) continue;
      const opciones = estiloMarcador(parada);
      if (!opciones) continue;
      const marcador = L.circleMarker([parada.lat, parada.lon], opciones);
      marcador.on("click", () => seleccionarParada(parada));
      marcador.addTo(capaMarcadores);
    }
  }

  function estiloMarcador(parada) {
    const sirve = (codigo) => (parada.lineas || []).includes(codigo);
    if (rutaActiva) {
      // Route mode: it highlights origin, transfer and destination (clickable) and fades the rest.
      if (parada.id === rutaActiva.origen) {
        return { radius: 9, weight: 3, color: "#ffffff", fillColor: "#1D9E75", fillOpacity: 1 };
      }
      if (parada.id === rutaActiva.destino) {
        return { radius: 9, weight: 3, color: "#ffffff", fillColor: "#E24B4A", fillOpacity: 1 };
      }
      if (rutaActiva.transbordos.has(parada.id)) {
        return { radius: 8, weight: 3, color: "#555555", fillColor: "#ffffff", fillOpacity: 1 };
      }
      return { radius: 4, weight: 1, color: "#d5d5d5", fillColor: "#e6e6e6", fillOpacity: 0.5 };
    }
    if (lineaVistazo) {
      // Preview as a layer: it highlights the preview line and the selected one, and fades the rest.
      if (sirve(lineaVistazo)) {
        return { radius: 7, weight: 2, color: "#ffffff", fillColor: colorLinea(lineaVistazo), fillOpacity: 0.95 };
      }
      if (lineaSeleccionada && sirve(lineaSeleccionada)) {
        return { radius: 7, weight: 2, color: "#ffffff", fillColor: colorLinea(lineaSeleccionada), fillOpacity: 0.95 };
      }
      return { radius: 5, weight: 1, color: "#cfcfcf", fillColor: "#e2e2e2", fillOpacity: 0.4 };
    }
    if (lineaSeleccionada) {
      // Fixed filter: only the stops of the line, with the open stop as an exception.
      if (sirve(lineaSeleccionada)) {
        return { radius: 8, weight: 2, color: "#ffffff", fillColor: colorLinea(lineaSeleccionada), fillOpacity: 0.95 };
      }
      if (parada === paradaActual) {
        return { radius: 8, weight: 2, color: "#ffffff", fillColor: COLOR_BASE, fillOpacity: 0.9 };
      }
      return null;
    }
    return { radius: 5, weight: 2, color: "#ffffff", fillColor: COLOR_BASE, fillOpacity: 0.9 };
  }

  function dibujarTrazado() {
    capaTrazado.clearLayers();
    const grupo = L.featureGroup();
    dibujarRutaEn(grupo, lineaSeleccionada);
    if (lineaVistazo && lineaVistazo !== lineaSeleccionada) dibujarRutaEn(grupo, lineaVistazo);
    if (!grupo.getLayers().length) return;
    grupo.addTo(capaTrazado);
    if (!lineaVistazo && lineaSeleccionada) {
      encuadreAutomatico = true;
      encuadrar(grupo.getBounds());
    }
  }

  function dibujarRutaEn(grupo, codigo) {
    if (!codigo) return;
    const trazado = shapes[codigo];
    if (!trazado) return;
    const color = colorLinea(codigo);
    for (const puntos of Object.values(trazado)) {
      if (puntos.length < 2) continue;
      const linea = L.polyline(puntos, { color, weight: 3, opacity: 0.8, dashArray: "4 10" });
      linea.addTo(grupo);
      if (L.Symbol && L.polylineDecorator) {
        L.polylineDecorator(linea, {
          patterns: [{
            offset: 20,
            repeat: 70,
            symbol: L.Symbol.arrowHead({
              pixelSize: 9,
              polygon: true,
              pathOptions: { color, fillOpacity: 0.9, weight: 0 },
            }),
          }],
        }).addTo(grupo);
      }
    }
  }

  async function cargarDatos() {
    const [respLineas, respParadas] = await Promise.all([
      fetch("/data/lineas.json"),
      fetch("/data/paradas.json"),
    ]);
    if (!respLineas.ok || !respParadas.ok) throw new Error("datos no disponibles");
    lineas = await respLineas.json();
    paradas = await respParadas.json();
    for (const parada of paradas) paradaPorId[parada.id] = parada;
    try {
      const [respShapes, respRed, respDias] = await Promise.all([
        fetch("/data/shapes.json"),
        fetch("/data/red.json"),
        fetch("/data/dias.json"),
      ]);
      if (respShapes.ok) shapes = await respShapes.json();
      if (respRed.ok) red = await respRed.json();
      if (respDias.ok) dias = await respDias.json();
    } catch (err) {
      /* shapes/red/dias opcionales: sin ellos se degradan trazado, ruta y filtro por día */
    }
  }

  // ---------- Arrivals (map popup) ----------

  function filasLlegadas(llegadas) {
    const ordenadas = [...llegadas].sort((a, b) => minutosDe(a.tiempo) - minutosDe(b.tiempo));
    if (lineaSeleccionada) {
      ordenadas.sort((a, b) => {
        const sa = codigoLinea(a.linea) === lineaSeleccionada ? 0 : 1;
        const sb = codigoLinea(b.linea) === lineaSeleccionada ? 0 : 1;
        return sa - sb;
      });
    }
    return ordenadas
      .map((llegada) => {
        const codigo = codigoLinea(llegada.linea);
        const color = colorLinea(codigo);
        const destino = (lineas[codigo] || {}).nombre || codigo;
        const seleccionada = lineaSeleccionada && codigo === lineaSeleccionada;
        const estilo = seleccionada ? ` style="background:${conAlfa(color, 0.16)}"` : "";
        const conocida = Boolean(lineas[codigo]);
        const claseChip = conocida ? "chip-linea chip-clicable" : "chip-linea";
        const dataLinea = conocida ? ` data-linea="${escaparHtml(codigo)}"` : "";
        return `
          <div class="fila-llegada${seleccionada ? " resaltada" : ""}"${estilo}>
            <span class="${claseChip}"${dataLinea} style="background:${color};color:${textoSobre(color)}">${escaparHtml(codigo)}</span>
            <span class="fila-destino"><span class="destino-texto">${escaparHtml(destino)}</span></span>
            <span class="fila-tiempo">${escaparHtml(textoLlegada(llegada.tiempo))}</span>
          </div>`;
      })
      .join("");
  }

  function htmlPopup(parada, cuerpo) {
    return `<div class="popup-titulo">${escaparHtml(parada.nombre)}</div>${cuerpo}`;
  }

  function mostrarPopup(parada, cuerpo) {
    clearTimeout(cierreVistazoPendiente);
    popupActual = L.popup({ maxWidth: 300, minWidth: 210, className: "popup-badabus", autoPanPadding: [24, 24] })
      .setLatLng([parada.lat, parada.lon])
      .setContent(htmlPopup(parada, cuerpo));
    popupActual.openOn(map);
  }

  function actualizarPopup(parada, cuerpo) {
    if (!popupActual || paradaActual !== parada) return;
    popupActual.setContent(htmlPopup(parada, cuerpo));
    const el = popupActual.getElement();
    if (!el) return;
    const boton = el.querySelector(".reintentar");
    if (boton) boton.addEventListener("click", () => seleccionarParada(parada));
    el.querySelectorAll(".chip-clicable").forEach((chip) => {
      chip.addEventListener("click", () => vistazoLinea(chip.dataset.linea));
    });
    setTimeout(() => activarMarquesinas(el), 60);
  }

  function activarMarquesinas(el) {
    const GAP = 20;
    el.querySelectorAll(".destino-texto").forEach((texto) => {
      if (texto.children.length) return;
      if (texto.scrollWidth - texto.parentElement.clientWidth <= 1) return;
      const original = texto.textContent;
      const copia1 = document.createElement("span");
      copia1.textContent = original;
      const copia2 = document.createElement("span");
      copia2.textContent = original;
      copia2.setAttribute("aria-hidden", "true");
      texto.textContent = "";
      texto.style.gap = `${GAP}px`;
      texto.append(copia1, copia2);
      const recorrido = Math.round(copia1.getBoundingClientRect().width + GAP);
      texto.style.setProperty("--recorrido", `-${recorrido}px`);
      texto.style.animationDuration = `${Math.max(7, Math.round(recorrido / 24))}s`;
      texto.classList.add("marquee");
    });
  }

  function cuerpoError() {
    return `<div class="popup-estado">${t("error_tiempos")} <button type="button" class="reintentar">${t("reintentar")}</button></div>`;
  }

  async function seleccionarParada(parada) {
    if (modoMapa) {
      const campo = modoMapa;
      modoMapa = null;
      fijarParada(campo, parada.id);
      abrirComoLlegar();
      return;
    }
    paradaActual = parada;
    ultimasLlegadas = null;
    const idPeticion = ++peticionActual;
    if (lineaSeleccionada) refrescarMarcadores();
    mostrarPopup(parada, `<div class="popup-estado">${t("cargando")}</div>`);
    try {
      const resp = await fetch(`/api/parada/${encodeURIComponent(parada.id)}`);
      if (idPeticion !== peticionActual) return;
      if (!resp.ok) {
        actualizarPopup(parada, cuerpoError());
        return;
      }
      const llegadas = await resp.json();
      if (idPeticion !== peticionActual) return;
      if (!Array.isArray(llegadas)) {
        actualizarPopup(parada, cuerpoError());
        return;
      }
      ultimasLlegadas = llegadas;
      const filas = filasLlegadas(llegadas);
      actualizarPopup(parada, filas || `<div class="popup-estado">${t("sin_llegadas")}</div>`);
    } catch (err) {
      if (idPeticion === peticionActual) actualizarPopup(parada, cuerpoError());
    }
  }

  // ---------- Filter by line ----------

  function tipoDiaLocal(fecha) {
    const diaSemana = fecha.getDay(); // 0 domingo, 6 sábado
    if (diaSemana === 0) return "DOM";
    if (diaSemana === 6) return "SAB";
    return "LV";
  }

  async function obtenerTipoDia() {
    try {
      const resp = await fetch("/api/dia");
      if (resp.ok) {
        const datos = await resp.json();
        if (datos.tipo_dia) return datos.tipo_dia;
      }
    } catch (err) {
      /* sin servicio se cae al calendario, que no distingue festivos */
    }
    return tipoDiaLocal(new Date());
  }

  function poblarChips(tipoDia) {
    const contenedor = document.getElementById("chips-lineas");
    const todas = document.createElement("button");
    todas.type = "button";
    todas.className = "chip-linea-btn todas";
    todas.textContent = t("todas");
    todas.addEventListener("click", () => seleccionarLinea(""));
    contenedor.appendChild(todas);
    // With no day data, missing or an empty list, all are drawn: a line is never hidden by a fault.
    const activas = dias[tipoDia];
    const codigos = Object.keys(lineas)
      .filter((codigo) => !activas || activas.length === 0 || activas.includes(codigo))
      .sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
    for (const codigo of codigos) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip-linea-btn";
      chip.textContent = codigo;
      chip.style.background = colorLinea(codigo);
      chip.style.color = textoSobre(colorLinea(codigo));
      chip.addEventListener("click", () => seleccionarLinea(codigo));
      contenedor.appendChild(chip);
    }
  }

  function seleccionarLinea(codigo) {
    lineaVistazo = "";
    lineaSeleccionada = codigo;
    actualizarBotonLineas();
    refrescarMarcadores();
    dibujarTrazado();
    if (paradaActual && ultimasLlegadas) {
      const filas = filasLlegadas(ultimasLlegadas);
      actualizarPopup(paradaActual, filas || `<div class="popup-estado">${t("sin_llegadas")}</div>`);
    }
    cerrarLineas();
  }

  function vistazoLinea(codigo) {
    if (codigo === lineaSeleccionada) return;
    lineaVistazo = codigo;
    refrescarMarcadores();
    dibujarTrazado();
  }

  function actualizarBotonLineas() {
    const chip = document.getElementById("btn-chip");
    const texto = document.getElementById("btn-texto");
    if (lineaSeleccionada) {
      chip.style.display = "inline-block";
      chip.style.background = colorLinea(lineaSeleccionada);
      texto.textContent = lineaSeleccionada;
    } else {
      chip.style.display = "none";
      texto.textContent = t("lineas");
    }
  }

  function abrirLineas() {
    document.getElementById("panel-lineas").hidden = false;
    document.getElementById("scrim-lineas").hidden = false;
    document.getElementById("btn-lineas").setAttribute("aria-expanded", "true");
    document.getElementById("cerrar-lineas").focus();
  }

  function cerrarLineas() {
    const panel = document.getElementById("panel-lineas");
    const estabaAbierto = !panel.hidden;
    panel.hidden = true;
    document.getElementById("scrim-lineas").hidden = true;
    document.getElementById("btn-lineas").setAttribute("aria-expanded", "false");
    if (estabaAbierto) document.getElementById("btn-lineas").focus();
  }

  // ---------- Nearest stop ----------

  function localizarParadaMasCercana() {
    if (!navigator.geolocation) {
      mostrarAviso(t("sin_geo"));
      return;
    }
    mostrarAviso(t("buscando_ubicacion"));
    navigator.geolocation.getCurrentPosition(
      (posicion) => {
        const { latitude, longitude } = posicion.coords;
        const cercana = paradaMasCercana(latitude, longitude, paradas);
        if (!cercana) {
          mostrarAviso(t("sin_parada_cerca"));
          return;
        }
        map.setView([cercana.lat, cercana.lon], 16);
        seleccionarParada(cercana);
      },
      () => mostrarAviso(t("sin_ubicacion"))
    );
  }

  // ---------- Stop search ----------

  function buscarParadas(texto) {
    const consulta = texto.trim().toLowerCase();
    if (!consulta) return [];
    const encontradas = [];
    for (const parada of paradas) {
      if (String(parada.nombre).toLowerCase().includes(consulta)) {
        encontradas.push(parada);
        if (encontradas.length >= 8) break;
      }
    }
    return encontradas;
  }

  function renderResultados(lista) {
    const contenedor = document.getElementById("resultados-busqueda");
    const buscador = document.getElementById("buscar-parada");
    contenedor.innerHTML = "";
    if (!lista.length) {
      contenedor.hidden = true;
      buscador.setAttribute("aria-expanded", "false");
      return;
    }
    for (const parada of lista) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "resultado-item";
      item.setAttribute("role", "option");
      item.textContent = parada.nombre;
      item.addEventListener("mousedown", (evento) => {
        evento.preventDefault();
        elegirBusqueda(parada);
      });
      contenedor.appendChild(item);
    }
    contenedor.hidden = false;
    buscador.setAttribute("aria-expanded", "true");
  }

  function ocultarResultados() {
    document.getElementById("resultados-busqueda").hidden = true;
    document.getElementById("buscar-parada").setAttribute("aria-expanded", "false");
  }

  function elegirBusqueda(parada) {
    document.getElementById("buscar-parada").value = parada.nombre;
    ocultarResultados();
    if (!coordsValidas(parada)) {
      mostrarAviso(t("parada_sin_mapa"));
      return;
    }
    map.setView([parada.lat, parada.lon], 16);
    seleccionarParada(parada);
  }

  // ---------- Directions ----------

  function abrirComoLlegar() {
    // The shape of the selected line would overlap the route, so it is removed.
    if (lineaSeleccionada || lineaVistazo) seleccionarLinea("");
    document.getElementById("panel-comollegar").hidden = false;
    document.getElementById("scrim-comollegar").hidden = false;
    document.getElementById("btn-comollegar").setAttribute("aria-expanded", "true");
    renderSelector("origen");
    renderSelector("destino");
  }

  // Swapping is an everyday case: you look up the outward trip and then the return
  // one. Without a button, both endpoints have to be retyped by hand.
  function invertirExtremos() {
    const antes = origenSel;
    origenSel = destinoSel;
    destinoSel = antes;
    renderSelector("origen");
    renderSelector("destino");
    if (origenSel && destinoSel) {
      buscarRuta();
      return;
    }
    // With one endpoint loose, what is on screen no longer belongs to this trip.
    limpiarResultados();
  }

  function limpiarResultados() {
    ultimasRutas = null;
    ultimoAPie = null;
    rutaActiva = null;
    limitesEncuadre = null;
    document.getElementById("cl-resultados").innerHTML = "";
    document.body.classList.remove("ruta-activa");
    capaRuta.clearLayers();
    refrescarMarcadores();
  }

  function cerrarComoLlegar() {
    document.getElementById("panel-comollegar").hidden = true;
    document.getElementById("scrim-comollegar").hidden = true;
    document.getElementById("btn-comollegar").setAttribute("aria-expanded", "false");
    origenSel = null;
    destinoSel = null;
    limpiarResultados();
  }

  function nombreParada(id) {
    return (paradaPorId[id] || {}).nombre || id;
  }

  // A selection can be a stop picked by hand, or a point on the map or an address:
  // {tipo: "parada", id, nombre} | {tipo: "punto", lat, lon, nombre}
  function fijarSeleccion(campo, seleccion) {
    if (campo === "origen") origenSel = seleccion;
    else destinoSel = seleccion;
    renderSelector(campo);
  }

  function fijarParada(campo, id) {
    fijarSeleccion(campo, { tipo: "parada", id, nombre: nombreParada(id) });
  }

  function fijarPunto(campo, lat, lon, nombre) {
    fijarSeleccion(campo, { tipo: "punto", lat, lon, nombre: nombre || "Punto en el mapa" });
  }

  function renderSelector(campo) {
    const cont = document.getElementById(campo === "origen" ? "cl-origen" : "cl-destino");
    const sel = campo === "origen" ? origenSel : destinoSel;
    if (sel) {
      cont.innerHTML = `
        <div class="cl-elegida">
          <span class="cl-punto"></span>
          <span class="cl-nombre">${escaparHtml(sel.nombre)}</span>
          <button type="button" class="cl-quitar" aria-label="${t("quitar")}">&times;</button>
        </div>`;
      cont.querySelector(".cl-quitar").addEventListener("click", () => {
        if (campo === "origen") origenSel = null;
        else destinoSel = null;
        renderSelector(campo);
      });
      return;
    }
    cont.innerHTML = `
      <div class="cl-buscar-campo">
        <input type="text" class="cl-input" placeholder="${t("parada_o_direccion_ph")}" aria-label="${t(campo === "origen" ? "buscar_origen_aria" : "buscar_destino_aria")}" autocomplete="off">
        <div class="cl-resultados-busq" hidden></div>
      </div>
      <div class="cl-modos">
        <button type="button" class="cl-modo" data-modo="mapa">${t("en_el_mapa")}</button>
        <button type="button" class="cl-modo" data-modo="cercana">${t("mas_cercana")}</button>
      </div>`;
    const input = cont.querySelector(".cl-input");
    const res = cont.querySelector(".cl-resultados-busq");
    input.addEventListener("input", () => renderBusquedaCL(res, campo, input.value));
    input.addEventListener("blur", () => setTimeout(() => { res.hidden = true; }, 150));
    cont.querySelector('[data-modo="mapa"]').addEventListener("click", () => activarModoMapa(campo));
    cont.querySelector('[data-modo="cercana"]').addEventListener("click", () => elegirCercana(campo));
  }

  const temporizadoresBusqueda = {};
  // Text already searched -> addresses. To repeat a search is instant and costs no request.
  const cacheDirecciones = new Map();

  function recordarDirecciones(clave, sitios) {
    if (cacheDirecciones.size >= BUSQUEDA_CACHE_MAX) {
      cacheDirecciones.delete(cacheDirecciones.keys().next().value);
    }
    cacheDirecciones.set(clave, sitios);
  }

  // The geocoder allows search as you type, so no forced gap between requests is
  // needed. A short delay remains out of courtesy — one request per keystroke would
  // abuse a free service — and so does the cache, which makes a repeated search
  // instant. On return, the text is checked to be the same: a slow answer from an
  // earlier query could overwrite the current results.
  function buscarDirecciones(campo, texto, sigueVigente, alTener) {
    clearTimeout(temporizadoresBusqueda[campo]);
    const clave = texto.trim().toLowerCase();
    if (clave.length < BUSQUEDA_MIN_CARACTERES) {
      alTener("listo", []);
      return;
    }
    if (cacheDirecciones.has(clave)) {
      alTener("listo", cacheDirecciones.get(clave));
      return;
    }
    alTener("buscando", []);
    temporizadoresBusqueda[campo] = setTimeout(async () => {
      let encontradas = [];
      let respondio = false;
      try {
        const resp = await fetch(`/api/buscar?q=${encodeURIComponent(texto)}`);
        if (resp.ok) {
          encontradas = await resp.json();
          respondio = true;
        }
      } catch (err) {
        /* sin direcciones: las paradas siguen saliendo */
      }
      // A failure is not cached: a network drop would otherwise leave that text empty forever.
      if (respondio) recordarDirecciones(clave, encontradas);
      if (sigueVigente()) alTener("listo", encontradas);
    }, BUSQUEDA_ESPERA_MS);
  }

  function renderBusquedaCL(cont, campo, texto) {
    const paradasEncontradas = buscarParadas(texto);
    const pintar = (estado, direcciones) => {
      cont.innerHTML = "";
      const buscando = estado === "buscando";
      if (!paradasEncontradas.length && !direcciones.length && !buscando) {
        cont.hidden = true;
        return;
      }
      // Addresses go first, because they are what is being searched. Stops appear
      // instantly and push the addresses out of sight. While the addresses arrive
      // their heading stays in place, so the stops do not jump down just as you reach
      // to tap them.
      if (direcciones.length || buscando) cont.appendChild(cabeceraGrupo(t("direcciones")));
      for (const sitio of direcciones) {
        cont.appendChild(
          itemResultado(`⌂ ${sitio.nombre}`, () => fijarPunto(campo, sitio.lat, sitio.lon, sitio.nombre))
        );
      }
      if (buscando) cont.appendChild(avisoBuscando());
      if (paradasEncontradas.length) {
        cont.appendChild(cabeceraGrupo(t("paradas")));
        for (const parada of paradasEncontradas) {
          cont.appendChild(itemResultado(`● ${parada.nombre}`, () => fijarParada(campo, parada.id)));
        }
      }
      cont.hidden = false;
    };
    // The input can change before the answer arrives: it is drawn only if it is still the same.
    const inputActual = cont.parentElement.querySelector(".cl-input");
    buscarDirecciones(campo, texto, () => inputActual && inputActual.value === texto, pintar);
  }

  function avisoBuscando() {
    const div = document.createElement("div");
    div.className = "cl-buscando";
    div.textContent = t("buscando_direcciones");
    return div;
  }

  function cabeceraGrupo(titulo) {
    const div = document.createElement("div");
    div.className = "cl-grupo";
    div.textContent = titulo;
    return div;
  }

  function itemResultado(texto, alElegir) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "resultado-item";
    item.textContent = texto;
    item.addEventListener("mousedown", (evento) => {
      evento.preventDefault();
      alElegir();
    });
    return item;
  }

  function activarModoMapa(campo) {
    // It only hides the panel so the map can be touched. The state is kept: this is not an exit.
    modoMapa = campo;
    document.getElementById("panel-comollegar").hidden = true;
    document.getElementById("scrim-comollegar").hidden = true;
    mostrarAviso(t(campo === "origen" ? "toca_origen" : "toca_destino"));
  }

  async function alClicarElMapa(evento) {
    // Only while an origin or a destination is being picked. Otherwise a map click does nothing.
    if (!modoMapa) return;
    const campo = modoMapa;
    modoMapa = null;
    const { lat, lng } = evento.latlng;
    fijarPunto(campo, lat, lng, "Punto en el mapa");
    abrirComoLlegar();
    try {
      const resp = await fetch(`/api/direccion?lat=${lat}&lon=${lng}`);
      if (resp.ok) {
        const { nombre } = await resp.json();
        // The selection can have changed while the answer was on its way.
        const actual = campo === "origen" ? origenSel : destinoSel;
        if (nombre && actual && actual.tipo === "punto" && actual.lat === lat && actual.lon === lng) {
          fijarPunto(campo, lat, lng, nombre);
        }
      }
    } catch (err) {
      /* sin nombre: se queda como "Punto en el mapa" */
    }
  }

  function elegirCercana(campo) {
    if (!navigator.geolocation) {
      mostrarAviso(t("sin_geo"));
      return;
    }
    mostrarAviso(t("buscando_ubicacion"));
    navigator.geolocation.getCurrentPosition(
      (posicion) => {
        const cercana = paradaMasCercana(posicion.coords.latitude, posicion.coords.longitude, paradas);
        if (cercana) fijarParada(campo, cercana.id);
        else mostrarAviso(t("sin_parada_cerca"));
      },
      () => mostrarAviso(t("sin_ubicacion"))
    );
  }

  async function buscarRuta() {
    const cont = document.getElementById("cl-resultados");
    if (!origenSel || !destinoSel) {
      cont.innerHTML = `<p class="cl-estado">${t("elige_extremos")}</p>`;
      return;
    }
    cont.innerHTML = `<p class="cl-estado">${t("buscando_ruta")}</p>`;
    const parametros = [paramsExtremo("origen", origenSel), paramsExtremo("destino", destinoSel)];
    try {
      const resp = await fetch(`/api/plan?${parametros.join("&")}`);
      if (!resp.ok) throw new Error("plan");
      const data = await resp.json();
      if (data.aviso === "fuera de la red") {
        cont.innerHTML = `<p class="cl-estado">${t("fuera_de_red")}</p>`;
        return;
      }
      if (data.aviso === "sin datos de paradas") {
        cont.innerHTML = `<p class="cl-estado">${t("sin_datos_paradas")}</p>`;
        return;
      }
      renderRutas(data.rutas || [], data.a_pie);
    } catch (err) {
      cont.innerHTML = `<p class="cl-estado">${t("error_ruta")}</p>`;
    }
  }

  function paramsExtremo(prefijo, sel) {
    if (sel.tipo === "parada") return `${prefijo}=${encodeURIComponent(sel.id)}`;
    return `${prefijo}_lat=${encodeURIComponent(sel.lat)}&${prefijo}_lon=${encodeURIComponent(sel.lon)}`;
  }

  // One leg can have several lines that serve it alike: all of them are drawn,
  // because the first one that comes will do, and that shortens the wait.
  // A transfer can be at the same stop, or it can require a walk to a nearby one. To
  // say "change at X" when there is a walk would leave out what matters most.
  function textoTransbordo(tramo, siguiente) {
    if (tramo.bajar === siguiente.subir) {
      const donde = escaparHtml(nombreParada(tramo.bajar));
      return `<div class="cl-transbordo">${t("transbordo_en", { parada: donde })}</div>`;
    }
    const a = paradaPorId[tramo.bajar];
    const b = paradaPorId[siguiente.subir];
    const metros = a && b ? Math.round(haversine(a.lat, a.lon, b.lat, b.lon)) : null;
    const cuanto = metros != null ? ` (${metros} m)` : "";
    const texto = t("baja_y_anda", {
      a: escaparHtml(nombreParada(tramo.bajar)),
      b: escaparHtml(nombreParada(siguiente.subir)),
      cuanto,
    });
    return `<div class="cl-transbordo">${texto}</div>`;
  }

  function chipsDeTramo(tramo) {
    return [tramo.linea, ...(tramo.alternativas || [])]
      .map((linea) => {
        const color = colorLinea(linea);
        return `<span class="chip-linea" style="background:${color};color:${textoSobre(color)}">${escaparHtml(linea)}</span>`;
      })
      .join("");
  }

  function textoMinutos(ruta) {
    // The server calculates the total. Here it is only drawn, so that there are not
    // two formulas that can drift apart.
    if (ruta.total_min == null) return "";
    // With the wait inside, the total holds up, even if the bus is the following one
    // and not the announced one. Without it the total is a floor, and "from" says so.
    const cerrado = ruta.espera_min != null;
    const partes = [t(cerrado ? "total_aprox" : "total_desde", { n: ruta.total_min })];
    if (ruta.andando_min) partes.push(t("min_andando", { n: ruta.andando_min }));
    const linea = escaparHtml(ruta.tramos[0].linea);
    if (cerrado) {
      const cual = ruta.aviso_espera === "no_llegas" ? "siguiente_linea" : "proximo_linea";
      partes.push(t(cual, { linea, n: ruta.espera_min }));
    } else if (ruta.espera_max_min != null) {
      // With no record of the last bus, the frequency bounds how long it can take.
      partes.push(t("espera_max", { n: ruta.espera_max_min }));
    }
    if (ruta.espera_transbordo_min != null) {
      partes.push(t("espera_transbordo", { n: ruta.espera_transbordo_min }));
    }
    const clave = AVISOS_ESPERA[ruta.aviso_espera];
    const cola = clave ? ` <span class="cl-aviso">${t(clave)}</span>` : "";
    return ` <span class="cl-ruta-min">· ${partes.join(" · ")}</span>${cola}`;
  }

  // Walking wins on short trips, and where it does not win it is still useful to know
  // that it exists: how many minutes it is, and whether waiting for the bus pays off.
  function tarjetaAPie(aPie, rutas) {
    if (!aPie || aPie.minutos == null) return "";
    const mejor = rutas.length ? rutas[0].total_min : null;
    const gana = mejor == null || aPie.minutos <= mejor;
    if (!gana && aPie.minutos > 25) return "";
    const km = aPie.metros >= 1000 ? `${(aPie.metros / 1000).toFixed(1)} km` : `${aPie.metros} m`;
    const cab = t(gana ? "apie_gana" : "apie_alternativa");
    return `<div class="cl-ruta cl-apie"><div class="cl-ruta-cab">${cab}</div>` +
      `<div class="cl-tramo"><span class="cl-tramo-txt">${aPie.minutos} min · ${km}</span></div></div>`;
  }

  function renderRutas(rutas, aPie) {
    // They are kept so they can be redrawn on a language change without asking again.
    ultimasRutas = rutas;
    ultimoAPie = aPie;
    const cont = document.getElementById("cl-resultados");
    if (!rutas.length) {
      const pie = tarjetaAPie(aPie, rutas);
      cont.innerHTML = pie || `<p class="cl-estado">${t("sin_ruta")}</p>`;
      capaRuta.clearLayers();
      rutaActiva = null;
      document.body.classList.remove("ruta-activa");
      refrescarMarcadores();
      return;
    }
    cont.innerHTML = "";
    const pie = tarjetaAPie(aPie, rutas);
    const pieGana = pie && aPie.minutos <= rutas[0].total_min;
    if (pieGana) cont.insertAdjacentHTML("beforeend", pie);
    rutas.forEach((ruta, idx) => {
      const tramos = ruta.tramos;
      const div = document.createElement("div");
      div.className = "cl-ruta" + (idx === 0 ? " activa" : "");
      const nt = tramos.length - 1;
      const cabecera = nt === 0
        ? t("directo")
        : (nt > 1 ? t("transbordos_n", { n: nt }) : t("transbordo_1"));
      const partes = [`<div class="cl-ruta-cab">${cabecera}${textoMinutos(ruta)}</div>`];
      tramos.forEach((tramo, i) => {
        partes.push(`<div class="cl-tramo"><span class="cl-lineas">${chipsDeTramo(tramo)}</span><span class="cl-tramo-txt">${escaparHtml(nombreParada(tramo.subir))} → ${escaparHtml(nombreParada(tramo.bajar))}</span></div>`);
        if (i < tramos.length - 1) partes.push(textoTransbordo(tramo, tramos[i + 1]));
      });
      div.innerHTML = partes.join("");
      div.addEventListener("click", () => {
        cont.querySelectorAll(".cl-ruta").forEach((r) => r.classList.remove("activa"));
        div.classList.add("activa");
        dibujarRuta(tramos);
      });
      cont.appendChild(div);
    });
    if (pie && !pieGana) cont.insertAdjacentHTML("beforeend", pie);
    dibujarRuta(rutas[0].tramos);
  }

  // ---------- Map framing ----------

  // The panels sit *on top of* the map: on a phone as a bottom sheet across the full
  // width, on a desktop as a card against the right edge. To fit against the whole map
  // leaves the route half covered, so what they take is subtracted and the route is
  // centred in what remains.
  const MARGEN_ENCUADRE = 40;
  // If a panel covers almost everything, to fit against the strip that is left would
  // give an absurd zoom: no more than this share of the screen is given up to it.
  const MAXIMO_TAPADO = 0.6;

  function loQueTapanLosPaneles() {
    const mapa = map.getContainer().getBoundingClientRect();
    let abajo = 0;
    let derecha = 0;
    for (const id of ["panel-comollegar", "panel-lineas"]) {
      const panel = document.getElementById(id);
      if (!panel || panel.hidden) continue;
      const caja = panel.getBoundingClientRect();
      if (!caja.width || !caja.height) continue;
      // Full width means the bottom sheet. Otherwise it is the card on the right.
      if (caja.width > mapa.width * 0.8) abajo = Math.max(abajo, mapa.bottom - caja.top);
      else derecha = Math.max(derecha, mapa.right - caja.left);
    }
    return {
      abajo: Math.min(Math.max(abajo, 0), mapa.height * MAXIMO_TAPADO),
      derecha: Math.min(Math.max(derecha, 0), mapa.width * MAXIMO_TAPADO),
    };
  }

  function encuadrar(limites) {
    if (limites) limitesEncuadre = limites;
    if (!limitesEncuadre || !limitesEncuadre.isValid()) return;
    const tapado = loQueTapanLosPaneles();
    // No animation on purpose: the move is then synchronous and can be told apart
    // from a move by the user, which is what turns the automatic framing off.
    encuadrando = true;
    map.fitBounds(limitesEncuadre, {
      paddingTopLeft: [MARGEN_ENCUADRE, MARGEN_ENCUADRE],
      paddingBottomRight: [MARGEN_ENCUADRE + tapado.derecha, MARGEN_ENCUADRE + tapado.abajo],
      animate: false,
    });
    encuadrando = false;
  }

  // The results sheet changes height on its own: when the routes arrive, when it is
  // dragged, when the phone turns. The visible gap changes with it, so the map has to
  // be framed again — unless the user has already moved the map by hand, and then the
  // user rules.
  function reencuadrar() {
    if (!encuadreAutomatico || pendienteEncuadre) return;
    pendienteEncuadre = true;
    requestAnimationFrame(() => {
      pendienteEncuadre = false;
      encuadrar(null);
    });
  }

  function vigilarElHueco() {
    const loMuevoYo = () => { if (!encuadrando) encuadreAutomatico = false; };
    map.on("dragstart", loMuevoYo);
    map.on("zoomstart", loMuevoYo);
    window.addEventListener("resize", reencuadrar);
    if (!window.ResizeObserver) return;
    const observador = new ResizeObserver(reencuadrar);
    for (const id of ["panel-comollegar", "panel-lineas"]) {
      const panel = document.getElementById(id);
      if (panel) observador.observe(panel);
    }
  }

  function dibujarRuta(ruta) {
    capaRuta.clearLayers();
    const grupo = L.featureGroup();
    for (const [i, tramo] of ruta.entries()) {
      const puntos = puntosShape(tramo.linea, tramo.subir, tramo.bajar) || puntosPorParadas(tramo);
      if (puntos && puntos.length >= 2) {
        L.polyline(puntos, { color: colorLinea(tramo.linea), weight: 5, opacity: 0.9 }).addTo(grupo);
      }
      // A transfer on foot leaves a gap between one leg and the next. With nothing
      // in between the route looks broken, so a dashed straight line joins them: it is
      // not the real path, which would need a pedestrian router, but it is the way.
      const siguiente = ruta[i + 1];
      if (siguiente && siguiente.subir !== tramo.bajar) {
        const a = paradaPorId[tramo.bajar];
        const b = paradaPorId[siguiente.subir];
        if (a && b && coordsValidas(a) && coordsValidas(b)) {
          L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
            color: "#6b7280", weight: 3, opacity: 0.9, dashArray: "2 8",
          }).addTo(grupo);
        }
      }
    }
    // The key stops include the one you walk to: that is where the bus is boarded.
    const clave = new Set();
    for (const [i, tramo] of ruta.entries()) {
      if (i < ruta.length - 1) clave.add(tramo.bajar);
      if (i > 0 && tramo.subir !== ruta[i - 1].bajar) clave.add(tramo.subir);
    }
    rutaActiva = {
      origen: ruta[0].subir,
      destino: ruta[ruta.length - 1].bajar,
      transbordos: clave,
    };
    document.body.classList.add("ruta-activa");
    if (grupo.getLayers().length) grupo.addTo(capaRuta);
    // refrescarMarcadores draws the origin, transfer and destination markers (clickable).
    refrescarMarcadores();
    if (grupo.getLayers().length) {
      // A new route: the framing takes over again, even if the user had moved the map.
      encuadreAutomatico = true;
      encuadrar(grupo.getBounds());
    }
  }

  function puntosPorParadas(tramo) {
    const seq = red[tramo.linea] || [];
    const i = seq.indexOf(tramo.subir);
    if (i < 0) return null;
    const rel = seq.slice(i + 1).indexOf(tramo.bajar);
    if (rel < 0) return null;
    return seq.slice(i, i + rel + 2)
      .map((id) => paradaPorId[id])
      .filter((p) => p && coordsValidas(p))
      .map((p) => [p.lat, p.lon]);
  }

  const MAX_TRAMOS_SHAPE = 3;
  const canonicoLinea = {};

  function permutaciones(items) {
    if (items.length <= 1) return [items];
    return items.flatMap((x, i) =>
      permutaciones([...items.slice(0, i), ...items.slice(i + 1)]).map((resto) => [x, ...resto])
    );
  }

  // Optimal monotonic alignment (dynamic programming) of the stops onto a polyline:
  // for each stop, the index of the point that matches it, in non-decreasing order.
  // Using the whole line sequence, the global context resolves the ambiguity of the
  // streets that a line runs through twice, outward and back.
  function alinear(puntos, anclas) {
    const n = puntos.length;
    const k = anclas.length;
    let previo = new Float64Array(n);
    const elecciones = [];
    for (let j = 0; j < n; j++) previo[j] = distancia2(puntos[j], anclas[0]);
    for (let m = 1; m < k; m++) {
      const actual = new Float64Array(n);
      const eleccion = new Int32Array(n);
      let menor = Infinity;
      let menorIdx = 0;
      for (let j = 0; j < n; j++) {
        if (previo[j] < menor) { menor = previo[j]; menorIdx = j; }
        actual[j] = distancia2(puntos[j], anclas[m]) + menor;
        eleccion[j] = menorIdx;
      }
      elecciones.push(eleccion);
      previo = actual;
    }
    let fin = 0;
    let coste = Infinity;
    for (let j = 0; j < n; j++) if (previo[j] < coste) { coste = previo[j]; fin = j; }
    const idx = new Array(k);
    let j = fin;
    for (let m = k - 1; m >= 1; m--) { idx[m] = j; j = elecciones[m - 1][j]; }
    idx[0] = j;
    return { idx, coste };
  }

  // The canonical shape of a line: its shape segments ordered and oriented in the way
  // that best explains its stop sequence, with the point that matches each stop.
  function canonicoDe(linea) {
    if (linea in canonicoLinea) return canonicoLinea[linea];
    const trazado = shapes[linea] || {};
    const seq = red[linea] || [];
    const tramos = Object.values(trazado).filter((s) => s.length >= 2);
    const paradasSeq = seq.map((id) => paradaPorId[id]);
    const validas = paradasSeq.filter((p) => p && coordsValidas(p));
    let mejor = null;
    if (tramos.length && tramos.length <= MAX_TRAMOS_SHAPE && validas.length >= 2) {
      for (const orden of permutaciones(tramos.map((_, i) => i))) {
        for (let mascara = 0; mascara < (1 << tramos.length); mascara++) {
          let cadena = [];
          for (const i of orden) {
            const s = tramos[i];
            cadena = cadena.concat((mascara >> i) & 1 ? s.slice().reverse() : s);
          }
          const alineado = alinear(cadena, validas);
          if (!mejor || alineado.coste < mejor.coste) {
            mejor = { coste: alineado.coste, puntos: cadena, idx: alineado.idx };
          }
        }
      }
      const porSeq = new Array(paradasSeq.length).fill(null);
      let v = 0;
      for (let z = 0; z < paradasSeq.length; z++) {
        if (paradasSeq[z] && coordsValidas(paradasSeq[z])) porSeq[z] = mejor.idx[v++];
      }
      mejor.porSeq = porSeq;
    }
    canonicoLinea[linea] = mejor;
    return mejor;
  }

  function puntosShape(linea, subir, bajar) {
    const seq = red[linea] || [];
    const i = seq.indexOf(subir);
    if (i < 0) return null;
    const rel = seq.slice(i + 1).indexOf(bajar);
    if (rel < 0) return null;
    const canonico = canonicoDe(linea);
    if (!canonico) return null;
    // The alignment is monotonic, so the leg already comes out in order of travel.
    const j = i + rel + 1;
    if (canonico.porSeq[i] == null || canonico.porSeq[j] == null) return null;
    if (canonico.porSeq[j] < canonico.porSeq[i]) return null;
    // The shape is walked and each stop is inserted in its place, so that the route
    // passes exactly through all of them. Otherwise detours and gaps appear at the
    // transfers.
    const tramo = [];
    let previo = null;
    for (let z = i; z <= j; z++) {
      const k = canonico.porSeq[z];
      const parada = paradaPorId[seq[z]];
      if (k == null || !parada || !coordsValidas(parada)) continue;
      if (previo != null && k > previo + 1) {
        for (const punto of canonico.puntos.slice(previo + 1, k)) tramo.push(punto);
      }
      tramo.push([parada.lat, parada.lon]);
      previo = k;
    }
    return tramo.length >= 2 ? tramo : null;
  }

  function distancia2(punto, parada) {
    const dlat = punto[0] - parada.lat;
    const dlon = punto[1] - parada.lon;
    return dlat * dlat + dlon * dlon;
  }

  // ---------- Start ----------

  function inicializar() {
    document.getElementById("theme-toggle").addEventListener("click", alternarTema);
    document.getElementById("locate").addEventListener("click", localizarParadaMasCercana);
    document.getElementById("btn-lineas").addEventListener("click", abrirLineas);
    document.getElementById("cerrar-lineas").addEventListener("click", cerrarLineas);
    document.getElementById("scrim-lineas").addEventListener("click", cerrarLineas);
    document.getElementById("btn-comollegar").addEventListener("click", abrirComoLlegar);
    document.getElementById("cerrar-comollegar").addEventListener("click", cerrarComoLlegar);
    document.getElementById("scrim-comollegar").addEventListener("click", cerrarComoLlegar);
    document.getElementById("cl-buscar").addEventListener("click", buscarRuta);
    document.getElementById("cl-invertir").addEventListener("click", invertirExtremos);
    document.getElementById("lang-toggle")
      .addEventListener("click", () => aplicarIdioma(idioma === "es" ? "en" : "es"));
    aplicarIdioma(idioma);
    const buscador = document.getElementById("buscar-parada");
    buscador.addEventListener("input", (evento) => renderResultados(buscarParadas(evento.target.value)));
    buscador.addEventListener("blur", ocultarResultados);
    document.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") {
        cerrarLineas();
        cerrarComoLlegar();
        ocultarResultados();
        if (map) map.closePopup();
      }
    });

    // The key goes first: the map is created with it, so the tiles are not reloaded later.
    cargarClaveMapa()
      .then(() => {
        crearMapa();
        aplicarTema(temaPreferido());
        return cargarDatos();
      })
      .then(async () => {
        refrescarMarcadores();
        poblarChips(await obtenerTipoDia());
      })
      .catch(() => mostrarAviso(t("error_datos_mapa")));
  }

  document.addEventListener("DOMContentLoaded", inicializar);
})();
