(() => {
  "use strict";

  const CENTRO_BADAJOZ = [38.8794, -6.9707];
  const ZOOM_INICIAL = 14;
  const COLOR_HEX = /^#[0-9a-fA-F]{6}$/;
  const COLOR_FALLBACK = "#6b7280";

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
  const marcadorPorParada = new Map();
  let paradaActual = null;

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

  // ---------- Mapa y datos ----------

  function crearMapa() {
    map = L.map("map").setView(CENTRO_BADAJOZ, ZOOM_INICIAL);
  }

  function pintarParadas() {
    for (const parada of paradas) {
      if (!coordsValidas(parada)) continue;
      const marcador = L.circleMarker([parada.lat, parada.lon], {
        radius: 5,
        weight: 1,
        color: "#ffffff",
        fillColor: "#1D9E75",
        fillOpacity: 0.9,
      }).addTo(map);
      marcador.on("click", () => seleccionarParada(parada));
      marcadorPorParada.set(parada.id, marcador);
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

  // ---------- Panel ----------

  function contenidoPanel() {
    return document.getElementById("panel-contenido");
  }

  function abrirPanelMovil() {
    document.getElementById("panel").classList.add("abierto");
  }

  function cerrarPanel() {
    document.getElementById("panel").classList.remove("abierto");
  }

  function renderCargando(parada) {
    contenidoPanel().innerHTML = `
      <h2 class="panel-titulo">${escaparHtml(parada.nombre)}</h2>
      <p class="panel-estado">Cargando…</p>
    `;
  }

  function renderError(parada) {
    contenidoPanel().innerHTML = `
      <h2 class="panel-titulo">${escaparHtml(parada.nombre)}</h2>
      <p class="panel-error">No se pudieron cargar los tiempos
        <button id="reintentar" type="button">Reintentar</button>
      </p>
    `;
    document.getElementById("reintentar").addEventListener("click", () => seleccionarParada(parada));
  }

  function renderAviso(mensaje) {
    contenidoPanel().innerHTML = `<p class="panel-estado">${escaparHtml(mensaje)}</p>`;
  }

  function renderLlegadas(parada, llegadas) {
    const ordenadas = [...llegadas].sort((a, b) => minutosDe(a.tiempo) - minutosDe(b.tiempo));
    const filas = ordenadas
      .map((llegada) => {
        const codigo = codigoLinea(llegada.linea);
        const destino = (lineas[codigo] || {}).nombre || codigo;
        return `
          <div class="fila-llegada">
            <span class="chip-linea" style="background:${colorLinea(codigo)}">${escaparHtml(codigo)}</span>
            <span class="fila-destino">${escaparHtml(destino)}</span>
            <span class="fila-tiempo">${escaparHtml(llegada.tiempo || "")}</span>
          </div>
        `;
      })
      .join("");
    contenidoPanel().innerHTML = `
      <h2 class="panel-titulo">${escaparHtml(parada.nombre)}</h2>
      ${filas || '<p class="panel-estado">Sin llegadas próximas.</p>'}
    `;
  }

  function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = String(texto);
    return div.innerHTML;
  }

  async function seleccionarParada(parada) {
    paradaActual = parada;
    renderCargando(parada);
    abrirPanelMovil();
    try {
      const resp = await fetch(`/api/parada/${encodeURIComponent(parada.id)}`);
      if (paradaActual !== parada) return;
      if (!resp.ok) {
        renderError(parada);
        return;
      }
      const llegadas = await resp.json();
      if (paradaActual !== parada) return;
      if (!Array.isArray(llegadas)) {
        renderError(parada);
        return;
      }
      renderLlegadas(parada, llegadas);
    } catch (err) {
      if (paradaActual === parada) renderError(parada);
    }
  }

  // ---------- Mi parada ----------

  function localizarParadaMasCercana() {
    if (!navigator.geolocation) {
      renderAviso("La geolocalización no está disponible en este dispositivo.");
      abrirPanelMovil();
      return;
    }
    renderAviso("Buscando tu ubicación…");
    abrirPanelMovil();
    navigator.geolocation.getCurrentPosition(
      (posicion) => {
        const { latitude, longitude } = posicion.coords;
        const cercana = paradaMasCercana(latitude, longitude, paradas);
        if (!cercana) {
          renderAviso("No se encontró ninguna parada cercana.");
          return;
        }
        map.setView([cercana.lat, cercana.lon], 16);
        seleccionarParada(cercana);
      },
      () => renderAviso("No se pudo obtener tu ubicación.")
    );
  }

  // ---------- Inicio ----------

  function inicializar() {
    document.getElementById("theme-toggle").addEventListener("click", alternarTema);
    document.getElementById("locate").addEventListener("click", localizarParadaMasCercana);
    document.getElementById("cerrar-panel").addEventListener("click", cerrarPanel);
    document.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") cerrarPanel();
    });

    crearMapa();
    aplicarTema(temaPreferido());

    cargarDatos()
      .then(pintarParadas)
      .catch(() => renderAviso("No se pudieron cargar los datos del mapa. Recarga la página."));
  }

  document.addEventListener("DOMContentLoaded", inicializar);
})();
