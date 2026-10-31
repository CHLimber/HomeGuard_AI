// Página "Prueba con video": subir, reproducir y borrar medios de prueba (modo exposición).
const DETECTORES = [
  { clave: "rostros", nombre: "🚷 Intrusión" },
  { clave: "piscina", nombre: "🏊 Piscina" },
  { clave: "fuego",   nombre: "🔥 Fuego" },
  { clave: "caidas",  nombre: "🧍 Caída" },
  { clave: "puerta",  nombre: "🚪 Puerta" },
];
const EXT_IMAGEN = /\.(jpe?g|png|bmp|webp)$/i;
const semaforo = document.getElementById("semaforo");
let medios = [], activa = null;

dibujarLamparas(semaforo);
document.getElementById("opciones-detector").innerHTML = DETECTORES.map(d =>
  `<label class="casilla"><input type="checkbox" name="detectores" value="${d.clave}"> ${d.nombre}</label>`).join("");

const nombreDetectores = lista => lista.map(c => DETECTORES.find(d => d.clave === c)?.nombre || c).join(" ");

async function cargar() {
  const datos = await api("/api/pruebas");
  medios = datos.medios;
  activa = datos.activa;
  const lista = document.getElementById("lista");
  lista.innerHTML = medios.length ? medios.map(p => `
    <tr class="${p.activa ? "fila-activa" : ""}">
      <td>${escapar(p.nombre)}${p.existe ? "" : ' <span class="etiqueta mal">falta el archivo</span>'}</td>
      <td class="datos">${p.tipo === "video" ? "video" : `${p.imagenes} foto(s) · ${p.segundos_por_imagen} s c/u`}</td>
      <td>${nombreDetectores(p.detectores)}</td>
      <td class="datos">${p.zonas.length ? escapar(p.zonas.join(", ")) : '<span class="etiqueta aviso">sin zonas</span>'}</td>
      <td style="white-space:nowrap">
        <button onclick="reproducir('${p.id}')">${p.activa ? "↺ Reiniciar" : "▶ Reproducir"}</button>
        ${p.activa ? `<button class="secundario" onclick="detener()">■ Detener</button>` : ""}
        <a class="boton secundario" href="/zonas?camara=${p.camara_id}">Zonas</a>
        <button class="secundario" onclick="borrar('${p.id}', '${escapar(p.nombre).replace(/'/g, "\\'")}')">Borrar</button>
      </td></tr>`).join("")
    : `<tr><td colspan="5" class="vacio">Todavía no hay pruebas. Subí un video o fotos con el formulario.</td></tr>`;
  mostrarActiva();
  avisos(datos);
}

function mostrarActiva() {
  const medio = medios.find(p => p.activa);
  const video = document.getElementById("video");
  document.getElementById("titulo-video").textContent = medio ? medio.nombre : "Elegí una prueba y tocá «Reproducir»";
  const etq = document.getElementById("etq-activa");
  etq.textContent = medio ? "reproduciendo" : "sin reproducir";
  etq.className = "etiqueta " + (medio ? "ok" : "");
  const src = medio ? `/stream/${medio.camara_id}?t=${Date.now()}` : "/static/img/vacio.svg";
  if (!medio || !video.src.includes(`/stream/${medio.camara_id}`)) video.src = src;
}

function avisos(datos) {
  const medio = medios.find(p => p.activa);
  const lista = [];
  if (!datos.armado) lista.push("El sistema está DESARMADO: se analiza el video pero no va a sonar nada. Armalo con el botón de arriba.");
  if (medio && medio.detectores.includes("rostros") && datos.residentes > 0)
    lista.push(`Hay ${datos.residentes} residente(s) registrado(s): si la persona del video es uno de ellos, no es intrusión.`);
  if (medio && medio.detectores.includes("puerta"))
    lista.push("Puerta: tiene que cambiar el 25 % de la zona. Si la puerta no ocupa casi todo el cuadro, dibujá la zona sobre la puerta (botón «Zonas») y tocá «Reiniciar».");
  if (medio && !medio.zonas.length && medio.detectores.some(d => d !== "caidas"))
    lista.push("Esta prueba no tiene zonas: intrusión, piscina y puerta necesitan una. Dibujala en Zonas.");
  document.getElementById("avisos").innerHTML = lista.map(t => `<div class="mensaje error">${escapar(t)}</div>`).join("");
}

async function reproducir(id) {
  await api(`/api/pruebas/${id}/reproducir`, { method: "POST" });
  document.getElementById("ultimo-evento").innerHTML = "";
  await cargar();
}

async function detener() {
  await api("/api/pruebas/detener", { method: "POST" });
  await cargar();
}

async function borrar(id, nombre) {
  if (!confirm(`¿Borrar la prueba «${nombre}»? Se borra el archivo subido (los eventos quedan en el historial).`)) return;
  await api(`/api/pruebas/${id}`, { method: "DELETE" });
  await cargar();
}

// segundos por foto: solo tiene sentido si se suben imágenes
document.getElementById("archivos").addEventListener("change", ev => {
  const archivos = [...ev.target.files];
  document.getElementById("campo-segundos").style.display =
    archivos.length && archivos.every(f => EXT_IMAGEN.test(f.name)) ? "" : "none";
});

document.getElementById("form-prueba").addEventListener("submit", async ev => {
  ev.preventDefault();
  const res = document.getElementById("resultado");
  const form = new FormData(ev.target);
  if (!form.getAll("detectores").length) {
    res.innerHTML = `<div class="mensaje error">Elegí al menos una anomalía.</div>`;
    return;
  }
  // las casillas sin marcar no se envían: se mandan explícitas como false
  for (const casilla of ["zonas_completas", "reproducir"]) if (!form.has(casilla)) form.append(casilla, "false");
  const boton = document.getElementById("btn-subir");
  boton.disabled = true; boton.textContent = "Subiendo…";
  try {
    const m = await api("/api/pruebas", { method: "POST", body: form });
    const extra = m.tipo === "video" ? `${m.resolucion}, ${m.duracion_s ?? "?"} s` : `${m.imagenes} foto(s), ${m.resolucion}`;
    res.innerHTML = `<div class="mensaje ok">«${escapar(m.nombre)}» guardada (${escapar(extra)}).</div>`;
    ev.target.reset();
    document.getElementById("campo-segundos").style.display = "none";
    await cargar();
  } catch (e) {
    res.innerHTML = `<div class="mensaje error">No se pudo subir: ${escapar(e.message)}</div>`;
  } finally {
    boton.disabled = false; boton.textContent = "Subir y analizar";
  }
});

alTelemetria.push(t => {
  pintarLamparas(semaforo, t.estado, t.activos);
  const medio = medios.find(p => p.activa);
  const cam = medio && t.camaras.find(c => c.id === medio.camara_id);
  const est = document.getElementById("estado-video");
  est.textContent = cam ? (cam.conectada ? "analizando" : "sin señal") : "—";
  est.className = "etiqueta " + (cam ? (cam.conectada ? "ok" : "mal") : "");
  document.getElementById("info-video").textContent = cam
    ? `análisis ${cam.fps_proceso} FPS · ${cam.ms_por_frame} ms/frame · ${cam.resolucion || "—"}` + (cam.error ? ` · ${cam.error}` : "")
    : "";
});

alAlerta.push(msg => {
  const e = msg.evento;
  const medio = medios.find(p => p.activa);
  if (!medio || e.camara_id !== medio.camara_id) return;
  document.getElementById("ultimo-evento").innerHTML = `
    <div class="mensaje ok"><b>¡${escapar(e.etiqueta)}!</b> confirmada a las ${escapar(e.hora)}
      (confianza ${(e.confianza * 100).toFixed(0)} %). Ya sonó el panel y quedó en el
      <a href="/historial">Historial</a>.<br><img src="${e.foto}" alt="Foto del evento" style="max-width:100%;margin-top:6px"></div>`;
});

cargar();
