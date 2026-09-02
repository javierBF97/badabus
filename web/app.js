(() => {
  "use strict";

  const CENTRO_BADAJOZ = [38.8794, -6.9707];
  const ZOOM_INICIAL = 14;
  const COLOR_HEX = /^#[0-9a-fA-F]{6}$/;
  const COLOR_FALLBACK = "#6b7280";
  const COLOR_BASE = "#1D9E75";
  const ALIAS_LINEA = { BGM1: "BG1", BGM2: "BG2" };
  const BUSQUEDA_MIN_CARACTERES = 4;
  const BUSQUEDA_ESPERA_MS = 200;
  const BUSQUEDA_MS_ENTRE_PETICIONES = 1000;
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

  // ---------- Tema ----------

  function temaPreferido() {
    const guardado = localStorage.getItem("tema");
    if (guardado === "claro" || guardado === "oscuro") return guardado;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
  }

  async function cargarClaveMapa() {
    // Sin clave el mapa se ve con marca de agua, pero la app funciona igual.
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

  function aplicarTema(tema) {
    document.documentElement.dataset.theme = tema;
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.setAttribute("aria-pressed", tema === "oscuro" ? "true" : "false");
      toggle.setAttribute("aria-label", tema === "oscuro" ? "Activar modo claro" : "Activar modo oscuro");
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

  // ---------- Mapa y datos ----------

  function crearMapa() {
    map = L.map("map").setView(CENTRO_BADAJOZ, ZOOM_INICIAL);
    capaTrazado = L.layerGroup().addTo(map);
    capaRuta = L.layerGroup().addTo(map);
    capaMarcadores = L.layerGroup().addTo(map);
    map.on("popupclose", alCerrarPopup);
    map.on("click", alClicarElMapa);
  }

  function alCerrarPopup(evento) {
    if (evento.popup !== popupActual) return;
    paradaActual = null;
    ultimasLlegadas = null;
    popupActual = null;
    // Cierre diferido: si enseguida se abre otro popup (cambio de parada), no se limpia el vistazo.
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
      // Modo ruta: resalta origen/transbordo/destino (clicables) y difumina el resto en gris.
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
      // Vistazo como capa: resalta la línea del vistazo y la del selector; difumina el resto.
      if (sirve(lineaVistazo)) {
        return { radius: 7, weight: 2, color: "#ffffff", fillColor: colorLinea(lineaVistazo), fillOpacity: 0.95 };
      }
      if (lineaSeleccionada && sirve(lineaSeleccionada)) {
        return { radius: 7, weight: 2, color: "#ffffff", fillColor: colorLinea(lineaSeleccionada), fillOpacity: 0.95 };
      }
      return { radius: 5, weight: 1, color: "#cfcfcf", fillColor: "#e2e2e2", fillOpacity: 0.4 };
    }
    if (lineaSeleccionada) {
      // Filtro fijo: solo las paradas de la línea (y la parada abierta como excepción).
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
    if (!lineaVistazo && lineaSeleccionada) map.fitBounds(grupo.getBounds(), { padding: [30, 30] });
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

  // ---------- Tiempos (popup en el mapa) ----------

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
            <span class="fila-tiempo">${escaparHtml(llegada.tiempo || "")}</span>
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
    return '<div class="popup-estado">No se pudieron cargar los tiempos <button type="button" class="reintentar">Reintentar</button></div>';
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
    mostrarPopup(parada, '<div class="popup-estado">Cargando…</div>');
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
      actualizarPopup(parada, filas || '<div class="popup-estado">Sin llegadas próximas.</div>');
    } catch (err) {
      if (idPeticion === peticionActual) actualizarPopup(parada, cuerpoError());
    }
  }

  // ---------- Filtro por línea ----------

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
    todas.textContent = "Todas";
    todas.addEventListener("click", () => seleccionarLinea(""));
    contenedor.appendChild(todas);
    // Sin datos del día (ausente o lista vacía) se pintan todas: nunca se esconde una línea por un fallo.
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
      actualizarPopup(paradaActual, filas || '<div class="popup-estado">Sin llegadas próximas.</div>');
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
      texto.textContent = "Líneas";
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

  // ---------- Mi parada ----------

  function localizarParadaMasCercana() {
    if (!navigator.geolocation) {
      mostrarAviso("La geolocalización no está disponible en este dispositivo.");
      return;
    }
    mostrarAviso("Buscando tu ubicación…");
    navigator.geolocation.getCurrentPosition(
      (posicion) => {
        const { latitude, longitude } = posicion.coords;
        const cercana = paradaMasCercana(latitude, longitude, paradas);
        if (!cercana) {
          mostrarAviso("No se encontró ninguna parada cercana.");
          return;
        }
        map.setView([cercana.lat, cercana.lon], 16);
        seleccionarParada(cercana);
      },
      () => mostrarAviso("No se pudo obtener tu ubicación.")
    );
  }

  // ---------- Buscador de paradas ----------

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
      mostrarAviso("Esa parada no tiene ubicación en el mapa.");
      return;
    }
    map.setView([parada.lat, parada.lon], 16);
    seleccionarParada(parada);
  }

  // ---------- Cómo llegar ----------

  function abrirComoLlegar() {
    // El trazado de la línea elegida se solaparía con el de la ruta: se quita.
    if (lineaSeleccionada || lineaVistazo) seleccionarLinea("");
    document.getElementById("panel-comollegar").hidden = false;
    document.getElementById("scrim-comollegar").hidden = false;
    document.getElementById("btn-comollegar").setAttribute("aria-expanded", "true");
    renderSelector("origen");
    renderSelector("destino");
  }

  function cerrarComoLlegar() {
    document.getElementById("panel-comollegar").hidden = true;
    document.getElementById("scrim-comollegar").hidden = true;
    document.getElementById("btn-comollegar").setAttribute("aria-expanded", "false");
    origenSel = null;
    destinoSel = null;
    rutaActiva = null;
    document.body.classList.remove("ruta-activa");
    document.getElementById("cl-resultados").innerHTML = "";
    capaRuta.clearLayers();
    refrescarMarcadores();
  }

  function nombreParada(id) {
    return (paradaPorId[id] || {}).nombre || id;
  }

  // La selección puede ser una parada elegida a mano o un punto del mapa/una dirección:
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
          <button type="button" class="cl-quitar" aria-label="Quitar">&times;</button>
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
        <input type="text" class="cl-input" placeholder="Parada o dirección…" aria-label="Buscar parada o dirección de ${campo}" autocomplete="off">
        <div class="cl-resultados-busq" hidden></div>
      </div>
      <div class="cl-modos">
        <button type="button" class="cl-modo" data-modo="mapa">En el mapa</button>
        <button type="button" class="cl-modo" data-modo="cercana">Más cercana</button>
      </div>`;
    const input = cont.querySelector(".cl-input");
    const res = cont.querySelector(".cl-resultados-busq");
    input.addEventListener("input", () => renderBusquedaCL(res, campo, input.value));
    input.addEventListener("blur", () => setTimeout(() => { res.hidden = true; }, 150));
    cont.querySelector('[data-modo="mapa"]').addEventListener("click", () => activarModoMapa(campo));
    cont.querySelector('[data-modo="cercana"]').addEventListener("click", () => elegirCercana(campo));
  }

  const temporizadoresBusqueda = {};
  // Texto ya buscado -> direcciones. Repetir una búsqueda sale al instante y sin petición.
  const cacheDirecciones = new Map();
  let ultimaPeticionDirecciones = 0;

  function recordarDirecciones(clave, sitios) {
    if (cacheDirecciones.size >= BUSQUEDA_CACHE_MAX) {
      cacheDirecciones.delete(cacheDirecciones.keys().next().value);
    }
    cacheDirecciones.set(clave, sitios);
  }

  // Nominatim limita a una petición por segundo y prohíbe el autocompletado, así que la
  // espera corta solo decide cuándo *querríamos* buscar: el hueco mínimo entre peticiones
  // es lo que garantiza no pasarse. Una consulta que cae dentro de ese hueco no se
  // descarta, se retrasa, y sale con el último texto escrito. Menos de 4 caracteres no se
  // consulta. Al volver se comprueba que el texto siga igual, porque una respuesta lenta
  // de una consulta anterior podría pisar los resultados de la actual.
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
    const hueco = BUSQUEDA_MS_ENTRE_PETICIONES - (Date.now() - ultimaPeticionDirecciones);
    temporizadoresBusqueda[campo] = setTimeout(async () => {
      ultimaPeticionDirecciones = Date.now();
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
      // Un fallo no se guarda: si no, un corte de red dejaría ese texto vacío para siempre.
      if (respondio) recordarDirecciones(clave, encontradas);
      if (sigueVigente()) alTener("listo", encontradas);
    }, Math.max(BUSQUEDA_ESPERA_MS, hueco));
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
      // Las direcciones van primero porque son lo que se busca; las paradas salen al
      // instante y las empujaban fuera de la vista. Mientras llegan se deja puesta su
      // cabecera, para que las paradas no salten hacia abajo justo al ir a tocarlas.
      if (direcciones.length || buscando) cont.appendChild(cabeceraGrupo("Direcciones"));
      for (const sitio of direcciones) {
        cont.appendChild(
          itemResultado(`⌂ ${sitio.nombre}`, () => fijarPunto(campo, sitio.lat, sitio.lon, sitio.nombre))
        );
      }
      if (buscando) cont.appendChild(avisoBuscando());
      if (paradasEncontradas.length) {
        cont.appendChild(cabeceraGrupo("Paradas"));
        for (const parada of paradasEncontradas) {
          cont.appendChild(itemResultado(`● ${parada.nombre}`, () => fijarParada(campo, parada.id)));
        }
      }
      cont.hidden = false;
    };
    // El input puede haber cambiado cuando llegue la respuesta: solo se pinta si sigue igual.
    const inputActual = cont.parentElement.querySelector(".cl-input");
    buscarDirecciones(campo, texto, () => inputActual && inputActual.value === texto, pintar);
  }

  function avisoBuscando() {
    const div = document.createElement("div");
    div.className = "cl-buscando";
    div.textContent = "Buscando direcciones…";
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
    // Solo oculta el panel para poder tocar el mapa; conserva el estado (no es salir).
    modoMapa = campo;
    document.getElementById("panel-comollegar").hidden = true;
    document.getElementById("scrim-comollegar").hidden = true;
    mostrarAviso(campo === "origen" ? "Toca la parada de origen en el mapa" : "Toca la parada de destino en el mapa");
  }

  async function alClicarElMapa(evento) {
    // Solo cuando se está eligiendo origen o destino; si no, un clic en el mapa no hace nada.
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
        // Puede haber cambiado la selección mientras llegaba la respuesta.
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
      mostrarAviso("La geolocalización no está disponible en este dispositivo.");
      return;
    }
    mostrarAviso("Buscando tu ubicación…");
    navigator.geolocation.getCurrentPosition(
      (posicion) => {
        const cercana = paradaMasCercana(posicion.coords.latitude, posicion.coords.longitude, paradas);
        if (cercana) fijarParada(campo, cercana.id);
        else mostrarAviso("No se encontró ninguna parada cercana.");
      },
      () => mostrarAviso("No se pudo obtener tu ubicación.")
    );
  }

  async function buscarRuta() {
    const cont = document.getElementById("cl-resultados");
    if (!origenSel || !destinoSel) {
      cont.innerHTML = '<p class="cl-estado">Elige origen y destino.</p>';
      return;
    }
    cont.innerHTML = '<p class="cl-estado">Buscando ruta…</p>';
    const parametros = [paramsExtremo("origen", origenSel), paramsExtremo("destino", destinoSel)];
    try {
      const resp = await fetch(`/api/plan?${parametros.join("&")}`);
      if (!resp.ok) throw new Error("plan");
      const data = await resp.json();
      if (data.aviso === "fuera de la red") {
        cont.innerHTML = '<p class="cl-estado">Esa dirección no tiene paradas cerca.</p>';
        return;
      }
      if (data.aviso === "sin datos de paradas") {
        cont.innerHTML = '<p class="cl-estado">Faltan los datos de paradas. Recarga la página.</p>';
        return;
      }
      renderRutas(data.rutas || []);
    } catch (err) {
      cont.innerHTML = '<p class="cl-estado">No se pudo calcular la ruta.</p>';
    }
  }

  function paramsExtremo(prefijo, sel) {
    if (sel.tipo === "parada") return `${prefijo}=${encodeURIComponent(sel.id)}`;
    return `${prefijo}_lat=${encodeURIComponent(sel.lat)}&${prefijo}_lon=${encodeURIComponent(sel.lon)}`;
  }

  // Un tramo puede tener varias líneas que lo hacen igual: se pintan todas, porque
  // sirve la primera que pase y eso acorta la espera.
  function chipsDeTramo(tramo) {
    return [tramo.linea, ...(tramo.alternativas || [])]
      .map((linea) => {
        const color = colorLinea(linea);
        return `<span class="chip-linea" style="background:${color};color:${textoSobre(color)}">${escaparHtml(linea)}</span>`;
      })
      .join("");
  }

  function textoMinutos(ruta) {
    // El total lo calcula el servidor: aquí solo se pinta, para que no haya dos
    // fórmulas que puedan desincronizarse.
    if (ruta.total_min == null) return "";
    const partes = [`~${ruta.total_min} min`];
    if (ruta.andando_min != null) partes.push(`${ruta.andando_min} min andando`);
    if (ruta.espera_min != null) {
      partes.push(`próximo ${escaparHtml(ruta.tramos[0].linea)} en ${ruta.espera_min} min`);
    }
    return ` <span class="cl-ruta-min">· ${partes.join(" · ")}</span>`;
  }

  function renderRutas(rutas) {
    const cont = document.getElementById("cl-resultados");
    if (!rutas.length) {
      cont.innerHTML = '<p class="cl-estado">No se encontró ruta (prueba con otras paradas).</p>';
      capaRuta.clearLayers();
      rutaActiva = null;
      document.body.classList.remove("ruta-activa");
      refrescarMarcadores();
      return;
    }
    cont.innerHTML = "";
    rutas.forEach((ruta, idx) => {
      const tramos = ruta.tramos;
      const div = document.createElement("div");
      div.className = "cl-ruta" + (idx === 0 ? " activa" : "");
      const nt = tramos.length - 1;
      const cabecera = nt === 0 ? "Directo" : nt + (nt > 1 ? " transbordos" : " transbordo");
      const partes = [`<div class="cl-ruta-cab">${cabecera}${textoMinutos(ruta)}</div>`];
      tramos.forEach((tramo, i) => {
        partes.push(`<div class="cl-tramo"><span class="cl-lineas">${chipsDeTramo(tramo)}</span><span class="cl-tramo-txt">${escaparHtml(nombreParada(tramo.subir))} → ${escaparHtml(nombreParada(tramo.bajar))}</span></div>`);
        if (i < tramos.length - 1) partes.push(`<div class="cl-transbordo">↕ transbordo en ${escaparHtml(nombreParada(tramo.bajar))}</div>`);
      });
      div.innerHTML = partes.join("");
      div.addEventListener("click", () => {
        cont.querySelectorAll(".cl-ruta").forEach((r) => r.classList.remove("activa"));
        div.classList.add("activa");
        dibujarRuta(tramos);
      });
      cont.appendChild(div);
    });
    dibujarRuta(rutas[0].tramos);
  }

  function dibujarRuta(ruta) {
    capaRuta.clearLayers();
    const grupo = L.featureGroup();
    for (const tramo of ruta) {
      const puntos = puntosShape(tramo.linea, tramo.subir, tramo.bajar) || puntosPorParadas(tramo);
      if (puntos && puntos.length >= 2) {
        L.polyline(puntos, { color: colorLinea(tramo.linea), weight: 5, opacity: 0.9 }).addTo(grupo);
      }
    }
    rutaActiva = {
      origen: ruta[0].subir,
      destino: ruta[ruta.length - 1].bajar,
      transbordos: new Set(ruta.slice(0, -1).map((tramo) => tramo.bajar)),
    };
    document.body.classList.add("ruta-activa");
    if (grupo.getLayers().length) grupo.addTo(capaRuta);
    // Los marcadores de origen/transbordo/destino los pinta refrescarMarcadores (clicables).
    refrescarMarcadores();
    if (grupo.getLayers().length) map.fitBounds(grupo.getBounds(), { padding: [40, 40] });
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

  // Alineamiento monótono óptimo (programación dinámica) de las paradas sobre una polilínea:
  // para cada parada, el índice del punto que le corresponde, en orden no decreciente.
  // Al usar toda la secuencia de la línea, el contexto global resuelve las ambigüedades
  // de las calles por las que se pasa dos veces (ida y vuelta).
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

  // Trazado canónico de una línea: sus tramos de shape ordenados y orientados de la forma
  // que mejor explica su secuencia de paradas, con el punto que corresponde a cada parada.
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
    // El alineamiento es monótono, así que el tramo ya sale en orden de marcha.
    const j = i + rel + 1;
    if (canonico.porSeq[i] == null || canonico.porSeq[j] == null) return null;
    if (canonico.porSeq[j] < canonico.porSeq[i]) return null;
    // Se recorre el trazado insertando cada parada en su sitio, para que la ruta pase
    // exactamente por todas (si no, quedan desvíos y huecos en los transbordos).
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

  // ---------- Inicio ----------

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

    // La clave va primero: el mapa se crea con ella para no recargar los tiles después.
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
      .catch(() => mostrarAviso("No se pudieron cargar los datos del mapa. Recarga la página."));
  }

  document.addEventListener("DOMContentLoaded", inicializar);
})();
