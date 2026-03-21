import time
import requests
import threading
import os
import re
from datetime import datetime
import pytz
from flask import Flask
from playwright.sync_api import sync_playwright

# ================= CONFIGURACIÓN =================
URL_LOGIN = "https://eventossistema.com.mx/login.html"
URL_EVENTS = "https://eventossistema.com.mx/confirmaciones/default.html"
CHECK_INTERVAL = 90 
TZ = pytz.timezone("America/Mexico_City")

USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

EVENTOS_VIP = ["SYSTEM OF A DOWN", "SOAD", "ACDC", "AC/DC", "BTS"]
PUESTOS_ACEPTADOS = ["SEGURIDAD", "LOCAL CREW"]

app = Flask(__name__)

@app.route("/")
def home(): 
    return f"Bot Rastreador VIP - Online - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "turnos": "0", "mins_entrada": 0}
    try:
        puesto_m = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html_content)
        if puesto_m: info['puesto'] = puesto_m.group(1).strip().upper()
        
        horario_match = re.search(r'HORARIO</td><td.*?>(.*?)</td>', html_content, re.DOTALL)
        if horario_match:
            texto_h = horario_match.group(1)
            turnos_m = re.search(r'TURNOS\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
            if turnos_m: info['turnos'] = turnos_m.group(1)
            
            hora_m = re.search(r'(\d{2}):(\d{2})', texto_h)
            if hora_m:
                h, m = int(hora_m.group(1)), int(hora_m.group(2))
                info['mins_entrada'] = (h * 60) + m
    except: pass
    return info

def analizar_cazador(info, titulo_card, tiene_badge_preasignado):
    titulo = titulo_card.upper()
    puesto = info['puesto']
    turnos = info['turnos']
    mins = info.get('mins_entrada', 0)
    
    # Rango Concierto: 12:30 a 14:30 (750m a 870m)
    rango_concierto = 750 <= mins <= 870

    # 1. REGLA VIP (SOAD, ACDC, BTS) -> AUTO-CONFIRMAR
    es_vip = any(vip in titulo for vip in EVENTOS_VIP)
    if es_vip:
        if "RESGUARDO" in titulo:
            return True, "VIP es RESGUARDO (Manual)", False
        
        # Filtros de auto-confirmación: Puesto + Turnos + Horario
        if puesto in PUESTOS_ACEPTADOS and turnos == "1.5" and rango_concierto:
            return True, "VIP PERFECTO (Auto)", True
        
        return True, f"REVISIÓN MANUAL VIP: {titulo} ({puesto}/{turnos}T)", False

    # 2. OTROS EVENTOS (Incluyendo Diablos ahora) -> SOLO NOTIFICAR
    return True, "Evento Nuevo Disponible", False

def run_once():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0...")
            page = context.new_page()

            # Proceso de Login
            page.goto(URL_LOGIN, wait_until="networkidle", timeout=60000)
            page.fill("input[name='usuario']", USER)
            page.fill("input[name='password']", PASS)
            page.click("button[type='submit']")
            page.wait_for_timeout(5000)

            # Ir a sección de confirmaciones
            page.goto(URL_EVENTS, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            
            # Rastreo global de tarjetas
            cards = page.query_selector_all(".card.border")
            
            for card in cards:
                # Si la tarjeta ya está confirmada, la ignoramos
                is_confirmed = card.evaluate("(node) => node.closest('#div_eventos_confirmados') !== null")
                if is_confirmed: continue

                # Detectar Badge Amarillo (Preasignado)
                badge = card.query_selector("span.badge.bg-warning")
                es_preasignado = bool(badge and "PREASIGNADO" in badge.inner_text().upper())

                titulo_elem = card.query_selector("h6 a")
                if not titulo_elem: continue
                titulo_texto = titulo_elem.inner_text().strip()

                # Abrir detalles para leer la tabla
                titulo_elem.click()
                page.wait_for_timeout(1500)
                tabla = card.query_selector(".table-responsive")
                
                if tabla:
                    info = extraer_datos_tabla(tabla.inner_html())
                    interesa, motivo, auto = analizar_cazador(info, titulo_texto, es_preasignado)

                    if auto:
                        btn = card.query_selector("button:has-text('CONFIRMAR')")
                        if btn:
                            btn.click()
                            page.wait_for_timeout(3000)
                            send(f"🎯 *CONFIRMADO:* {titulo_texto}\n👤 {info['puesto']}\n📊 Horario: {info['mins_entrada']//60}:{info['mins_entrada']%60:02d}")
                    else:
                        # Para cualquier otro evento (incluyendo Diablos o VIP manual)
                        if motivo == "Evento Nuevo Disponible":
                            send(f"🔔 *EVENTO DISPONIBLE:* {titulo_texto}")
                        else:
                            send(f"⚠️ *{motivo}*")
            
            browser.close()
    except Exception as e:
        print(f"Error en el ciclo: {e}")

def monitor_loop():
    while True:
        run_once()
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
    
