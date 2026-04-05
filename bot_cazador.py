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

# Nombre específico actualizado para AC/DC 2026
EVENTOS_VIP = ["SYSTEM OF A DOWN", "SOAD", "AC DC 2026 SEGURIDAD", "ACDC", "AC/DC", "BTS"]
PUESTOS_ACEPTADOS = ["SEGURIDAD", "LOCAL CREW"]

# Inmuebles bloqueados (Fútbol/No interés)
INMUEBLES_BLOQUEADOS = ["ESTADIO CIUDAD DE LOS DEPORTES", "ESTADIO AZTECA", "AZTECA"]

app = Flask(__name__)

@app.route("/")
def home(): 
    return f"Bot VIP AC/DC 2026 - Online - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "turnos": "0", "mins_entrada": 0, "lugar": ""}
    try:
        puesto_m = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html_content)
        if puesto_m: info['puesto'] = puesto_m.group(1).strip().upper()

        lugar_m = re.search(r'LUGAR</td><td.*?>(.*?)</td>', html_content)
        if lugar_m: info['lugar'] = lugar_m.group(1).strip().upper()
        
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

def analizar_cazador(info, titulo_card):
    titulo = titulo_card.upper()
    puesto = info['puesto']
    turnos = info['turnos']
    mins = info.get('mins_entrada', 0)
    lugar = info['lugar']
    
    # --- FILTRO DE EXCLUSIÓN (Estadios No deseados) ---
    for bloqueado in INMUEBLES_BLOQUEADOS:
        if bloqueado in titulo or bloqueado in lugar:
            return False, "Bloqueado", False

    es_vip = any(vip in titulo for vip in EVENTOS_VIP)
    
    if es_vip:
        if "RESGUARDO" in titulo:
            return True, "VIP RESGUARDO (Manual)", False
        
        # AC/DC - Filtro por nombre específico y horarios actualizados
        if "AC DC 2026" in titulo or "ACDC" in titulo or "AC/DC" in titulo:
            # Turno 1.0 (15:30 = 930 mins)
            if turnos == "1" and mins == 930 and puesto in PUESTOS_ACEPTADOS:
                return True, "AC/DC 1T (Auto)", True
            # Turno 1.5 (13:30 = 810 mins)
            if turnos == "1.5" and mins == 810 and puesto in PUESTOS_ACEPTADOS:
                return True, "AC/DC 1.5T (Auto)", True

        # SOAD / BTS / Otros VIP
        rango_estandar = 750 <= mins <= 870
        if puesto in PUESTOS_ACEPTADOS and turnos == "1.5" and rango_estandar:
            return True, "VIP PERFECTO (Auto)", True
        
        return True, f"REVISIÓN VIP: {titulo}", False

    return True, "Disponible", False

def run_once():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0...")
            page = context.new_page()

            page.goto(URL_LOGIN, wait_until="networkidle", timeout=60000)
            page.fill("input[name='usuario']", USER)
            page.fill("input[name='password']", PASS)
            page.click("button[type='submit']")
            page.wait_for_timeout(4000)

            page.goto(URL_EVENTS, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            
            cards = page.query_selector_all(".card.border")
            eventos_disponibles = []
            
            for card in cards:
                if card.evaluate("(node) => node.closest('#div_eventos_confirmados') !== null"):
                    continue

                titulo_elem = card.query_selector("h6 a")
                if not titulo_elem: continue
                titulo_texto = titulo_elem.inner_text().strip()

                titulo_elem.click()
                page.wait_for_timeout(1200)
                tabla = card.query_selector(".table-responsive")
                
                if tabla:
                    info = extraer_datos_tabla(tabla.inner_html())
                    interesa, motivo, auto = analizar_cazador(info, titulo_texto)

                    if not interesa:
                        continue

                    if auto:
                        btn = card.query_selector("button:has-text('CONFIRMAR')")
                        if btn:
                            btn.click()
                            page.wait_for_timeout(2500)
                            send(f"🎯 *CONFIRMADO:* {titulo_texto}\n👤 {info['puesto']} - {info['turnos']}T\n✅ Filtro: {motivo}")
                    else:
                        emoji = "⚠️" if "REVISIÓN" in motivo else "🔔"
                        hora_str = f"{info['mins_entrada']//60:02d}:{info['mins_entrada']%60:02d}"
                        eventos_disponibles.append(f"{emoji} *{titulo_texto}*\n└ {info['puesto']} | {info['turnos']}T | {hora_str}")

            if eventos_disponibles:
                mensaje_final = "📋 *RESUMEN DE EVENTOS DISPONIBLES*\n\n" + "\n\n".join(eventos_disponibles)
                send(mensaje_final)
            
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
            
