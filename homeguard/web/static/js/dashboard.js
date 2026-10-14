// Conexión del dashboard a /ws/estado: semáforo, banner de alarma y telemetría.
// Cada página puede registrar funciones en `alTelemetria` para usar los datos.
const alTelemetria = [];
const alAlerta = [];
let ultimaTelemetria = null;

const wsDashboard = conectarWS("/ws/estado", {
  alCambiarConexion: ok => marcarConexion(document.getElementById("conexion-dash"), ok),
  alMensaje: msg => {
    if (msg.tipo === "telemetria") {
      ultimaTelemetria = msg;
      actualizarBanner(msg.estado);
      alTelemetria.forEach(f => f(msg));
    } else if (msg.tipo === "alerta") {
      actualizarBanner(msg.estado, msg.evento);
      alAlerta.forEach(f => f(msg));
    } else if (msg.tipo === "estado") {
      actualizarBanner(msg.estado);
    }
  },
});

function actualizarBanner(estado, evento) {
  const banner = document.getElementById("banner-alarma");
  banner.classList.toggle("visible", estado !== 0);
  if (estado !== 0) {
    const activas = ANOMALIAS.filter((a, n) => bitActivo(estado, n)).map(a => a.nombre).join(" · ");
    document.getElementById("banner-texto").textContent =
      "¡Alarma! " + activas + (evento ? ` — ${evento.zona} (${evento.camara || evento.camara_id})` : "");
  }
}

document.getElementById("banner-silenciar").addEventListener("click", () => wsDashboard.enviar({ accion: "silenciar" }));

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, opciones);
  const datos = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const d = datos && datos.detail !== undefined ? datos.detail : datos;
    throw new Error(typeof d === "object" ? JSON.stringify(d) : (d || r.statusText));
  }
  return datos;
}

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
