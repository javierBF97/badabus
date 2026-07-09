(() => {
  "use strict";

  const CENTRO_BADAJOZ = [38.8794, -6.9707];
  const ZOOM_INICIAL = 14;
  const COLOR_HEX = /^#[0-9a-fA-F]{6}$/;
  const COLOR_FALLBACK = "#6b7280";
  const COLOR_BASE = "#1D9E75";

  const CAPAS_TILES = {
    claro: { url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" },
    oscuro: { url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" },
  };
  const ATRIBUCION =
    '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>';

  let lineas = {};
  let paradas = [];
  let map;
  let capaTiles;
  let capaMarcadores;
  let paradaActual = null;
  let lineaSeleccionada = "";
  let ultimasLlegadas = null;
  let popupActual = null;
  let avisoTimer = null;
  let peticionActual = 0;

  // ---------- Tema ----------

  function temaPreferido() {
    const guardado = localStorage.getItem("tema");
    if (guardado === "claro" || guardado === "oscuro") return guardado;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
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
      capaTiles = L.tileLayer(CAPAS_TILES[tema].url, { attribution: ATRIBUCION, maxZoom: 19 }).addTo(map);
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
    return String(texto).replace(/^L[ÍI]NEA\s+/i, "").trim();
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
    return div.innerHTML;
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
    capaMarcadores = L.layerGroup().addTo(map);
    map.on("popupclose", alCerrarPopup);
  }

  function alCerrarPopup(evento) {
    if (evento.popup !== popupActual) return;
    paradaActual = null;
    ultimasLlegadas = null;
    popupActual = null;
    if (lineaSeleccionada) refrescarMarcadores();
  }

  function refrescarMarcadores() {
    capaMarcadores.clearLayers();
    for (const parada of paradas) {
      if (!coordsValidas(parada)) continue;
      const enFiltro = !lineaSeleccionada || (parada.lineas || []).includes(lineaSeleccionada);
      if (!enFiltro && parada !== paradaActual) continue;
      const marcador = L.circleMarker([parada.lat, parada.lon], {
        radius: 5,
        weight: 1,
        color: "#ffffff",
        fillColor: enFiltro && lineaSeleccionada ? colorLinea(lineaSeleccionada) : COLOR_BASE,
        fillOpacity: 0.9,
      });
      marcador.on("click", () => seleccionarParada(parada));
      marcador.addTo(capaMarcadores);
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
        return `
          <div class="fila-llegada${seleccionada ? " resaltada" : ""}"${estilo}>
            <span class="chip-linea" style="background:${color};color:${textoSobre(color)}">${escaparHtml(codigo)}</span>
            <span class="fila-destino">${escaparHtml(destino)}</span>
            <span class="fila-tiempo">${escaparHtml(llegada.tiempo || "")}</span>
          </div>`;
      })
      .join("");
  }

  function htmlPopup(parada, cuerpo) {
    return `<div class="popup-titulo">${escaparHtml(parada.nombre)}</div>${cuerpo}`;
  }

  function mostrarPopup(parada, cuerpo) {
    popupActual = L.popup({ maxWidth: 300, minWidth: 210, className: "popup-badabus", autoPanPadding: [24, 24] })
      .setLatLng([parada.lat, parada.lon])
      .setContent(htmlPopup(parada, cuerpo));
    popupActual.openOn(map);
  }

  function actualizarPopup(parada, cuerpo) {
    if (!popupActual || paradaActual !== parada) return;
    popupActual.setContent(htmlPopup(parada, cuerpo));
    const el = popupActual.getElement();
    const boton = el && el.querySelector(".reintentar");
    if (boton) boton.addEventListener("click", () => seleccionarParada(parada));
  }

  function cuerpoError() {
    return '<div class="popup-estado">No se pudieron cargar los tiempos <button type="button" class="reintentar">Reintentar</button></div>';
  }

  async function seleccionarParada(parada) {
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

  function poblarChips() {
    const contenedor = document.getElementById("chips-lineas");
    const todas = document.createElement("button");
    todas.type = "button";
    todas.className = "chip-linea-btn todas";
    todas.textContent = "Todas";
    todas.addEventListener("click", () => seleccionarLinea(""));
    contenedor.appendChild(todas);
    const codigos = Object.keys(lineas).sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
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
    lineaSeleccionada = codigo;
    actualizarBotonLineas();
    refrescarMarcadores();
    if (paradaActual && ultimasLlegadas) {
      const filas = filasLlegadas(ultimasLlegadas);
      actualizarPopup(paradaActual, filas || '<div class="popup-estado">Sin llegadas próximas.</div>');
    }
    cerrarLineas();
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

  // ---------- Inicio ----------

  function inicializar() {
    document.getElementById("theme-toggle").addEventListener("click", alternarTema);
    document.getElementById("locate").addEventListener("click", localizarParadaMasCercana);
    document.getElementById("btn-lineas").addEventListener("click", abrirLineas);
    document.getElementById("cerrar-lineas").addEventListener("click", cerrarLineas);
    document.getElementById("scrim-lineas").addEventListener("click", cerrarLineas);
    const buscador = document.getElementById("buscar-parada");
    buscador.addEventListener("input", (evento) => renderResultados(buscarParadas(evento.target.value)));
    buscador.addEventListener("blur", ocultarResultados);
    document.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") {
        cerrarLineas();
        ocultarResultados();
        if (map) map.closePopup();
      }
    });

    crearMapa();
    aplicarTema(temaPreferido());

    cargarDatos()
      .then(() => {
        poblarChips();
        refrescarMarcadores();
      })
      .catch(() => mostrarAviso("No se pudieron cargar los datos del mapa. Recarga la página."));
  }

  document.addEventListener("DOMContentLoaded", inicializar);
})();
