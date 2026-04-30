"""
main.py — Bot Humanizado de Monitoreo de Eventos
Tecnologías: Python · Playwright · Flask · Requests
Entorno: Render (variables de entorno) + UptimeRobot (keep-alive)
"""

import os
import re
import time
import random
import threading
import logging
from datetime import datetime

import pytz
import requests
from flask import Flask
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Módulo de filtros externo ──────────────────────────────────────────────────
from filtros import analizar_evento

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Constantes / Variables de entorno ─────────────────────────────────────────
TZ          = pytz.timezone("America/Mexico_City")
URL_LOGIN   = os.getenv("URL_LOGIN",  "https://tusistema.com/login")
URL_EVENTS  = os.getenv("URL_EVENTS", "https://tusistema.com/eventos")
USER        = os.getenv("WEB_USER")
PASS        = os.getenv("WEB_PASS")
BOT_TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")

# Horas pico (CDMX) en que suelen publicarse eventos — el gestor de tiempo las
# respeta reduciendo el intervalo de espera en esos momentos.
HORAS_PICO = {6, 10, 14, 18, 22}   # 6am, 10am, 2pm, 6pm, 10pm

# ── Flask health-check (requerido por Render) ──────────────────────────────────
app = Flask(__name__)

@app.route("/")
def home():
    ahora = datetime.now(TZ).strftime("%d/%m/%Y %H:%M:%S")
    return f"✅ Bot activo — {ahora} CDMX"

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def enviar_telegram(mensaje: str) -> None:
    """Envía un mensaje al chat de Telegram configurado."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram no configurado (BOT_TOKEN / CHAT_ID vacíos).")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"},
            timeout=12
        )
        if not resp.ok:
            log.warning(f"Telegram respondió {resp.status_code}: {resp.text[:120]}")
    except requests.RequestException as exc:
        log.error(f"Error enviando Telegram: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — EXTRACCIÓN DE DATOS DEL HTML
# ══════════════════════════════════════════════════════════════════════════════

def extraer_datos_tabla(html: str) -> dict:
    """
    Parsea el HTML interno de la tabla de un evento y retorna un dict con:
    titulo, puesto, lugar, turnos, horario_texto, mins_entrada, fecha
    """
    datos = {
        "titulo":       "",
        "puesto":       "",
        "lugar":        "",
        "turnos":       "0",
        "horario_texto":"",
        "mins_entrada": 0,
        "fecha":        "",
    }
    try:
        # Título (primera celda colspan=2)
        m = re.search(r'colspan="2"[^>]*>(.*?)</td>', html, re.DOTALL)
        if m:
            datos["titulo"] = re.sub(r'<[^>]+>', '', m.group(1)).strip().upper()

        # Puesto
        m = re.search(r'PUESTO</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
        if m:
            datos["puesto"] = re.sub(r'<[^>]+>', '', m.group(1)).strip().upper()

        # Lugar
        m = re.search(r'LUGAR</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
        if m:
            datos["lugar"] = re.sub(r'<[^>]+>', '', m.group(1)).strip().upper()

        # Horario (contiene fecha, hora y turnos)
        m = re.search(r'HORARIO</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
        if m:
            texto_h = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            datos["horario_texto"] = texto_h

            # Turnos  (soporta "TURNOS: 1", "TURNOS 1.5", etc.)
            t = re.search(r'TURNOS\s*[:\-]?\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
            if t:
                datos["turnos"] = t.group(1)

            # Fecha de entrada  dd/mm/yyyy
            f = re.search(r'(\d{2}/\d{2}/\d{4})', texto_h)
            if f:
                datos["fecha"] = f.group(1)

            # Hora de entrada  HH:MM  (primera ocurrencia = hora inicio)
            h = re.search(r'(\d{2}):(\d{2})', texto_h)
            if h:
                datos["mins_entrada"] = int(h.group(1)) * 60 + int(h.group(2))

    except Exception as exc:
        log.error(f"extraer_datos_tabla: {exc}")

    return datos


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — LOGIN
# ══════════════════════════════════════════════════════════════════════════════

def login(page) -> bool:
    """
    Inicia sesión en el sistema.
    Retorna True si el login fue exitoso, False en caso contrario.
    """
    try:
        log.info("Navegando a la página de login…")
        page.goto(URL_LOGIN, wait_until="networkidle", timeout=60_000)
        _pausa(1.0, 2.5)   # pausa humana antes de escribir

        page.fill("input[name='usuario']", USER)
        _pausa(0.4, 1.0)
        page.fill("input[name='password']", PASS)
        _pausa(0.5, 1.5)

        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=30_000)
        _pausa(1.5, 3.0)

        # Verificación simple: si sigue en la URL de login → credenciales malas
        if "login" in page.url.lower():
            log.error("Login fallido — revisa WEB_USER / WEB_PASS.")
            return False

        log.info("Login exitoso.")
        return True

    except PWTimeout:
        log.error("Timeout durante el login.")
        return False
    except Exception as exc:
        log.error(f"Error en login: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — ESCANEO DE EVENTOS
# ══════════════════════════════════════════════════════════════════════════════

def escanear_eventos(page) -> list[dict]:
    """
    Navega a la sección de eventos, extrae SOLO los eventos DISPONIBLES,
    delega la decisión a filtros.py y retorna la lista de eventos procesados.

    Cada elemento del resultado es un dict con:
        titulo, datos (del extractor), accion ('CONFIRMAR'|'NOTIFICAR'|'IGNORAR'),
        motivo (str descriptivo del filtro), confirmado (bool)
    """
    resultados = []

    try:
        log.info("Navegando a la sección de eventos…")
        page.goto(URL_EVENTS, wait_until="domcontentloaded", timeout=60_000)
        _pausa(2.0, 4.0)

        # ── Localizar el contenedor de EVENTOS DISPONIBLES ────────────────────
        contenedor = page.query_selector("#div_eventos_disponibles")
        if not contenedor:
            log.warning("No se encontró #div_eventos_disponibles en la página.")
            return resultados

        # ── Comprobar si hay eventos o el mensaje "No hay eventos" ─────────────
        sin_eventos = contenedor.query_selector(".text-muted")
        if sin_eventos and "No hay eventos" in sin_eventos.inner_text():
            log.info("Sin eventos disponibles en este ciclo.")
            return resultados

        # ── Iterar sobre cada tarjeta de evento disponible ────────────────────
        cards = contenedor.query_selector_all(".card.border")
        log.info(f"Tarjetas encontradas en DISPONIBLES: {len(cards)}")

        for i, card in enumerate(cards):
            try:
                titulo_elem = card.query_selector("h6 a")
                if not titulo_elem:
                    continue

                titulo_raw  = titulo_elem.inner_text().strip()
                # El inner_text del <a> incluye la fecha en la siguiente línea; tomamos solo la primera
                titulo_texto = titulo_raw.split("\n")[0].strip().upper()
                log.info(f"  [{i+1}/{len(cards)}] Procesando: {titulo_texto}")

                # Abrir la tarjeta si está colapsada (clic humano)
                collapse_id = card.query_selector(".collapse")
                is_open = collapse_id and "show" in (collapse_id.get_attribute("class") or "")
                if not is_open:
                    titulo_elem.click()
                    _pausa(0.8, 1.8)

                # Extraer datos de la tabla interna
                tabla_html_elem = card.query_selector(".table-responsive")
                if not tabla_html_elem:
                    continue

                datos = extraer_datos_tabla(tabla_html_elem.inner_html())
                datos["titulo"] = datos["titulo"] or titulo_texto

                # Detectar badge PREASIGNADO dentro de la tarjeta
                badge_preasignado = card.query_selector(".badge")
                datos["preasignado"] = (
                    badge_preasignado is not None
                    and "PREASIGNADO" in badge_preasignado.inner_text().upper()
                )
                if datos["preasignado"]:
                    log.info(f"     🏷 Badge PREASIGNADO detectado en: {titulo_texto}")

                # Consultar filtros externos
                accion, motivo = analizar_evento(datos)
                log.info(f"     → Filtro: {accion} | {motivo}")

                confirmado = False

                if accion == "CONFIRMAR":
                    btn = card.query_selector("button[title='CONFIRMAR']")
                    if btn:
                        _pausa(0.3, 0.9)   # micro-pausa antes del clic
                        btn.click()
                        page.wait_for_timeout(2_500)
                        confirmado = True
                        log.info(f"     ✅ CONFIRMADO: {titulo_texto}")
                        # Notificación inmediata al confirmar
                        hora_str  = f"{datos['mins_entrada']//60:02d}:{datos['mins_entrada']%60:02d}"
                        badge_txt = "🏷 _PREASIGNADO_\n" if datos.get("preasignado") else ""
                        enviar_telegram(
                            f"🎯 *CONFIRMADO AUTOMÁTICAMENTE*\n\n"
                            f"📌 *{titulo_texto}*\n"
                            f"{badge_txt}"
                            f"👤 Puesto: {datos['puesto']}\n"
                            f"🏟 Lugar: {datos['lugar']}\n"
                            f"⏰ Entrada: {hora_str} | Turnos: {datos['turnos']}\n"
                            f"📋 Motivo: _{motivo}_"
                        )
                    else:
                        log.warning(f"     ⚠️ Botón CONFIRMAR no encontrado para: {titulo_texto}")

                resultados.append({
                    "titulo":     titulo_texto,
                    "datos":      datos,
                    "accion":     accion,
                    "motivo":     motivo,
                    "confirmado": confirmado,
                })

                _pausa(0.5, 1.5)   # pausa entre tarjetas

            except PWTimeout:
                log.warning(f"  Timeout procesando tarjeta {i+1}, continuando…")
            except Exception as exc:
                log.error(f"  Error en tarjeta {i+1}: {exc}")

    except PWTimeout:
        log.error("Timeout cargando la página de eventos.")
    except Exception as exc:
        log.error(f"Error en escanear_eventos: {exc}")

    return resultados


def enviar_resumen(resultados: list[dict]) -> None:
    """Envía un único mensaje con todos los eventos NOTIFICAR al final del ciclo."""
    pendientes = [r for r in resultados if r["accion"] == "NOTIFICAR" and not r["confirmado"]]

    if not pendientes:
        log.info("Sin eventos pendientes de notificar en este ciclo.")
        return

    lineas = []
    for r in pendientes:
        d = r["datos"]
        hora_str = f"{d['mins_entrada']//60:02d}:{d['mins_entrada']%60:02d}"
        emoji = "⚠️" if "REVISIÓN" in r["motivo"].upper() else "🔔"
        lineas.append(
            f"{emoji} *{r['titulo']}*\n"
            f"└ {d['puesto']} | {d['turnos']}T | {hora_str} | {d['lugar']}\n"
            f"└ _{r['motivo']}_"
        )

    mensaje = "📋 *RESUMEN — EVENTOS DISPONIBLES*\n\n" + "\n\n".join(lineas)
    enviar_telegram(mensaje)
    log.info(f"Resumen enviado: {len(pendientes)} evento(s).")


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 5 — CICLO PRINCIPAL (run_once)
# ══════════════════════════════════════════════════════════════════════════════

def run_once() -> None:
    """Lanza un browser headless, hace login, escanea y envía resultados."""
    log.info("═══ Iniciando ciclo de escaneo ═══")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="es-MX",
            )
            page = ctx.new_page()

            if not login(page):
                browser.close()
                return

            resultados = escanear_eventos(page)
            enviar_resumen(resultados)

            browser.close()

    except Exception as exc:
        log.error(f"Error fatal en run_once: {exc}")

    log.info("═══ Ciclo finalizado ═══")


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 6 — GESTOR DE TIEMPO (comportamiento humano)
# ══════════════════════════════════════════════════════════════════════════════

def _pausa(min_s: float, max_s: float) -> None:
    """Espera aleatoria entre min_s y max_s segundos."""
    time.sleep(random.uniform(min_s, max_s))


def _hora_cdmx() -> datetime:
    return datetime.now(TZ)


def _en_horario_sueno() -> bool:
    """
    Retorna True si el bot debe estar 'dormido'.
    Duerme a partir de las 23:00–01:00 (hora aleatoria) y despierta 05:00–06:00.
    La ventana exacta se recalcula cada noche para variar el patrón.
    """
    h = _hora_cdmx().hour
    return h >= 23 or h < 5   # simplificado; la variación se aplica en gestor_tiempo


def gestor_tiempo() -> None:
    """
    Bucle principal del bot.
    Gestiona:
      - Horarios de sueño nocturnos
      - Descansos largos aleatorios (15% de probabilidad)
      - Intervalos variables entre ciclos
      - Revisiones más frecuentes cerca de horas pico
    """
    log.info("gestor_tiempo iniciado.")

    # Hora de sueño esta noche (aleatoria entre 23:00 y 01:00 del día siguiente)
    hora_sueno   = random.randint(23, 24)   # 24 → se representa como la 1:00 am del día siguiente
    # Hora de despertar (aleatoria entre 05:00 y 06:00)
    hora_despertar = random.uniform(5.0, 6.0)

    while True:
        ahora  = _hora_cdmx()
        h_real = ahora.hour + ahora.minute / 60.0   # hora decimal

        # ── 1. Verificar ventana de sueño ─────────────────────────────────────
        dormido = (h_real >= hora_sueno) or (h_real < hora_despertar)
        if dormido:
            # Recalcular hora de despertar para esta madrugada
            hora_despertar = random.uniform(5.0, 6.0)
            log.info(f"😴 Modo sueño activo. Esperando hasta las {hora_despertar:.2f} h CDMX…")
            time.sleep(60 * 10)   # revisar cada 10 min si ya despertamos
            continue

        # Nueva hora de sueño para esta noche (puede variar cada ciclo)
        hora_sueno = random.randint(23, 24)

        # ── 2. Descanso largo aleatorio (15%) ─────────────────────────────────
        if random.random() < 0.15:
            descanso_min = random.randint(60, 180)
            log.info(f"☕ Descanso largo: {descanso_min} minutos (~{descanso_min/60:.1f} h)")
            time.sleep(descanso_min * 60)
            continue

        # ── 3. Ejecutar el escaneo ────────────────────────────────────────────
        run_once()

        # ── 4. Calcular próxima espera ────────────────────────────────────────
        hora_entera = ahora.hour
        cerca_pico  = any(abs(hora_entera - p) <= 1 for p in HORAS_PICO)

        if cerca_pico:
            # Cerca de hora pico: revisar cada 2–10 min
            espera = random.uniform(2 * 60, 10 * 60)
            log.info(f"⚡ Hora pico cercana → próxima revisión en {espera/60:.1f} min")
        else:
            # Fuera de pico: espera variable 5–35 min (con ocasional 35–60 min)
            if random.random() < 0.2:
                espera = random.uniform(35 * 60, 60 * 60)
                log.info(f"🕐 Espera larga → {espera/60:.1f} min")
            else:
                espera = random.uniform(5 * 60, 35 * 60)
                log.info(f"🕐 Próxima revisión en {espera/60:.1f} min")

        time.sleep(espera)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 7 — MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("🤖 Bot iniciando…")

    # Validar variables de entorno críticas
    for var in ("WEB_USER", "WEB_PASS", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        if not os.getenv(var):
            log.warning(f"Variable de entorno '{var}' no configurada.")

    # Hilo del bot (daemon → se detiene con el proceso principal)
    hilo = threading.Thread(target=gestor_tiempo, daemon=True, name="BotMonitor")
    hilo.start()

    # Servidor Flask (health-check para Render / UptimeRobot)
    port = int(os.environ.get("PORT", 10_000))
    log.info(f"Flask health-check en puerto {port}")
    app.run(host="0.0.0.0", port=port, use_reloader=False)


if __name__ == "__main__":
    main()
