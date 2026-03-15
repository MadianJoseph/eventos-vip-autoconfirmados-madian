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

# Variables de Entorno (Configurar en Render)
USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Filtros Maestros
EVENTOS_VIP = ["SYSTEM OF A DOWN", "SOAD", "ACDC", "AC/DC", "BTS"]
PUESTOS_OK = ["SEGURIDAD", "LOCAL CREW"]

app = Flask(__name__)

@app.route("/")
def home(): 
    return "Bot Cazador Madian (Solo VIP) Activo"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "inicio": "", "lugar": "", "turnos": "0"}
    # Extraer Lugar
    lugar_m = re.search(r'LUGAR</td><td.*?>(.*?)</td>', html_content)
    if lugar_m: info['lugar'] = lugar_m.group(1).strip().upper()
    # Extraer Puesto
    puesto_m = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html_content)
    if puesto_m: info['puesto'] = puesto_m.group(1).strip().upper()
    # Extraer Turnos e Inicio
    horario_match = re.search(r'HORARIO</td><td.*?>(.*?)</td>', html_content, re.DOTALL)
    if horario_match:
        texto_h = horario_match.group(1)
        fecha_m = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2})', texto_h)
        if fecha_m: info['inicio'] = fecha_m.group(1)
        turnos_m = re.search(r'TURNOS\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
        if turnos_m: info['turnos'] = turnos_m.group(1)
    return info

def analizar_cazador(info, titulo_card):
    titulo = titulo_card.upper()
    puesto = info['puesto']
    turnos = info['turnos']
    
    # 1. ¿Es un evento VIP?
    es_vip = any(vip in titulo for vip in EVENTOS_VIP)
    if not es_vip:
        return False, "No es VIP", False

    # 2. ¿Es resguardo? (Ignorar para auto-confirmar)
    if "RESGUARDO" in titulo:
        return False, "Es un RESGUARDO", False

    # 3. ¿Cumple puesto y turnos exactos? (1.5)
    if puesto in PUESTOS_OK and turnos == "1.5":
        return True, "CRITERIOS PERFECTOS", True # True final significa AUTO-CONFIRMAR
    
    return True, f"VIP Detectado pero Puesto/Turno no coincide ({puesto} - {turnos})", False

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        logged = False

        while True:
            try:
                if not logged:
                    page.goto(URL_LOGIN)
                    page.wait_for_timeout(3000)
                    page.fill("input[name='usuario']", USER)
                    page.fill("input[name='password']", PASS)
                    page.click("button[type='submit']")
                    page.wait_for_timeout(5000)
                    logged = True

                page.goto(URL_EVENTS, wait_until="networkidle")
                
                # Obtener eventos ya confirmados para no repetir
                confirmados_area = page.query_selector("#div_eventos_confirmados")
                texto_confirmados = confirmados_area.inner_text().upper() if confirmados_area else ""

                cards = page.query_selector_all(".card.border")
                for card in cards:
                    titulo_elem = card.query_selector("h6 a")
                    if not titulo_elem: continue
                    titulo_texto = titulo_elem.inner_text().upper()

                    # Si ya está confirmado, saltar
                    if titulo_texto in texto_confirmados: continue

                    # Desplegar para ver tabla
                    titulo_elem.click()
                    page.wait_for_timeout(1500)
                    tabla_elem = card.query_selector(".table-responsive")
                    if not tabla_elem: continue
                    
                    info = extraer_datos_tabla(tabla_elem.inner_html())
                    interesa, motivo, auto_confirmar = analizar_cazador(info, titulo_texto)

                    if interesa:
                        if auto_confirmar:
                            btn = card.query_selector("button:has-text('CONFIRMAR')")
                            if btn:
                                btn.click()
                                page.wait_for_timeout(3000) # Esperar cuadro de carga
                                send(f"🎯 *MADIAN: AUTO-CONFIRMADO*\n📌 {titulo_texto}\n👤 {info['puesto']}\n📊 Turnos: {info['turnos']}")
                            else:
                                send(f"⚠️ *MADIAN:* VIP perfecto pero no hallé el botón en {titulo_texto}")
                        else:
                            # Es VIP pero algo no cuadra (ej. es Local Crew o no es 1.5), enviamos aviso
                            send(f"🔔 *REVISIÓN MANUAL:* {titulo_texto}\n❌ {motivo}\n📍 {info['lugar']}")

                print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Escaneando...")

            except Exception as e:
                print(f"Error: {e}"); logged = False; time.sleep(30)
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
