// Panel de alarma: sirena (Web Audio), parpadeo, vibración, ack y silenciar.
const $ = id => document.getElementById(id);
const lamparas = $("lamparas");
dibujarLamparas(lamparas);

let estado = 0;
let sistemaArmado = true;  // lo decide el dashboard (armar/desarmar sistema)
let armado = false;        // panel armado: el toque inicial que habilita el audio
let audio = null;      // AudioContext (se crea al tocar "ARMAR")
let sirena = null;     // { osc, gain, timer }
let vibracion = null;

// ---------- Sirena: oscilador que barre de 600 a 1200 Hz en bucle ----------
function iniciarSirena() {
  if (!audio || sirena) return;
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.type = "sawtooth";
  gain.gain.value = 0.5;
  osc.connect(gain).connect(audio.destination);
  const barrido = () => {
    const t = audio.currentTime;
    osc.frequency.setValueAtTime(600, t);
    osc.frequency.linearRampToValueAtTime(1200, t + 0.5);
    osc.frequency.linearRampToValueAtTime(600, t + 1.0);
  };
  barrido();
  osc.start();
  sirena = { osc, gain, timer: setInterval(barrido, 1000) };
}

function detenerSirena() {
  if (!sirena) return;
  clearInterval(sirena.timer);
  try { sirena.osc.stop(); } catch (e) { /* ya detenido */ }
  sirena = null;
}

// ---------- Vibración (Android; requiere que el navegador la permita) ----------
function iniciarVibracion() {
  if (vibracion || !("vibrate" in navigator)) return;
  const patron = () => navigator.vibrate([500, 200, 500]);
  patron();
  vibracion = setInterval(patron, 1400);
}

function detenerVibracion() {
  if (!vibracion) return;
  clearInterval(vibracion);
  vibracion = null;
  navigator.vibrate && navigator.vibrate(0);
}

// ---------- Estado ----------
function aplicarEstado(nuevo) {
  estado = nuevo;
  pintarLamparas(lamparas, estado);
  const enAlarma = estado !== 0;
  document.body.classList.toggle("alarma", enAlarma);
  const activas = ANOMALIAS.filter((a, n) => bitActivo(estado, n)).map(a => a.nombre);
  document.body.classList.toggle("desarmado", !sistemaArmado && !enAlarma);
  $("rotulo").textContent = enAlarma ? "¡Alarma!" : sistemaArmado ? "Sistema normal" : "SISTEMA DESARMADO";
  $("sub").textContent = enAlarma ? activas.join(" · ")
    : !sistemaArmado ? "No suena ninguna alarma hasta que se arme desde el dashboard"
    : (armado ? "Vigilando" : "Panel sin armar");
  if (enAlarma && armado) { iniciarSirena(); iniciarVibracion(); }
  else { detenerSirena(); detenerVibracion(); }
}

function mostrarEvento(ev) {
  if (!ev) return;
  $("evento").classList.add("visible");
  $("evento-foto").src = ev.foto;
  $("evento-tipo").textContent = nombreAnomalia(ev.tipo);
  $("evento-zona").textContent = "Zona: " + ev.zona;
  $("evento-camara").textContent = "Cámara: " + (ev.camara || ev.camara_id);
  const hora = ev.hora || (ev.creado_en || "").slice(11, 19);
  $("evento-hora").textContent = hora;
}

const conexion = conectarWS("/ws/alarma", {
  alCambiarConexion: ok => marcarConexion($("conexion"), ok),
  alMensaje: msg => {
    if (msg.tipo === "alerta") {
      // ack inmediato: el servidor mide la latencia detección -> panel
      conexion.enviar({ accion: "ack", evento_id: msg.evento.id });
      mostrarEvento(msg.evento);
      aplicarEstado(msg.estado);
    } else if (msg.tipo === "estado") {
      if (msg.ultimo_evento) mostrarEvento(msg.ultimo_evento);
      const cambioArmado = msg.armado !== undefined && msg.armado !== sistemaArmado;
      if (msg.armado !== undefined) sistemaArmado = msg.armado;
      if (msg.estado !== estado || cambioArmado) aplicarEstado(msg.estado);
    }
  },
});

// ---------- Botones ----------
$("btn-armar").addEventListener("click", async () => {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  audio = new Ctx();
  await audio.resume();
  // pitido corto de confirmación
  const o = audio.createOscillator(), g = audio.createGain();
  g.gain.value = 0.3; o.frequency.value = 880; o.connect(g).connect(audio.destination);
  o.start(); o.stop(audio.currentTime + 0.15);
  try { await document.documentElement.requestFullscreen(); } catch (e) { /* no soportado */ }
  try { if ("wakeLock" in navigator) await navigator.wakeLock.request("screen"); } catch (e) { /* requiere HTTPS */ }
  armado = true;
  $("armar").classList.add("oculto");
  aplicarEstado(estado);
});

$("btn-silenciar").addEventListener("click", () => {
  conexion.enviar({ accion: "silenciar" });
  aplicarEstado(0);
});

$("btn-probar").addEventListener("click", () => {
  if (!audio) return;
  iniciarSirena();
  setTimeout(() => { if (estado === 0) detenerSirena(); }, 2000);
});
