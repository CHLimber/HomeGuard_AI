// Utilidades compartidas por el panel y el dashboard.

// Mismo orden de bits que homeguard/reglas/estado.py
const ANOMALIAS = [
  { tipo: "intrusion", nombre: "Intrusión", icono: "🚷" },
  { tipo: "piscina",   nombre: "Piscina",   icono: "🏊" },
  { tipo: "fuego",     nombre: "Fuego",     icono: "🔥" },
  { tipo: "caida",     nombre: "Caída",     icono: "🧍" },
  { tipo: "puerta",    nombre: "Puerta",    icono: "🚪" },
];

// Decodifica el byte de estado: bit n encendido => anomalía n activa
function bitActivo(estado, n) { return (estado & (1 << n)) !== 0; }

function dibujarLamparas(contenedor) {
  contenedor.innerHTML = ANOMALIAS.map((a, n) =>
    `<div class="lampara" data-bit="${n}"><span class="icono">${a.icono}</span>${a.nombre}</div>`).join("");
}

// estado: alarmas confirmadas (rojo). activos: condición presente ahora (ámbar).
function pintarLamparas(contenedor, estado, activos = 0) {
  contenedor.querySelectorAll(".lampara").forEach(el => {
    const n = Number(el.dataset.bit);
    el.classList.toggle("on", bitActivo(estado, n));
    el.classList.toggle("atencion", !bitActivo(estado, n) && bitActivo(activos, n));
  });
}

// WebSocket con reconexión automática y latido: si no llega nada en 6 s, reconecta.
function conectarWS(ruta, { alMensaje, alCambiarConexion }) {
  let ws = null, espera = 500, ultimo = Date.now();
  const url = () => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + ruta;
  function abrir() {
    ws = new WebSocket(url());
    ws.onopen = () => { espera = 500; ultimo = Date.now(); alCambiarConexion && alCambiarConexion(true); };
    ws.onmessage = ev => { ultimo = Date.now(); try { alMensaje(JSON.parse(ev.data)); } catch (e) { console.error(e); } };
    ws.onclose = () => {
      alCambiarConexion && alCambiarConexion(false);
      setTimeout(abrir, espera);
      espera = Math.min(espera * 2, 5000);
    };
    ws.onerror = () => ws.close();
  }
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN && Date.now() - ultimo > 6000) ws.close();
  }, 2000);
  abrir();
  return { enviar: obj => ws && ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(obj)) };
}

function marcarConexion(el, ok) {
  el.classList.toggle("ok", ok);
  el.textContent = ok ? "Conectado" : "Desconectado";
}

function nombreAnomalia(tipo) {
  const a = ANOMALIAS.find(x => x.tipo === tipo);
  return a ? a.nombre : tipo;
}
