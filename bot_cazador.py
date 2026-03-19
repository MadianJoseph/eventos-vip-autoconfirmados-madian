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
    return f"Bot Madian V3.2 - Vigilando... {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "inicio": "", "turnos": "0", "mins_entrada": 0}
    try:
        puesto_m = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html_content)
        if puesto_m: info['puesto'] = puesto_m.group(1).strip().upper()
        
        horario_match = re.search(r'HORARIO</td><td.*?>(.*?)</td>', html_content, re.DOTALL)
        if horario_match:
            texto_h = horario_match.group(1)
            turnos_m = re.search(r'TURNOS\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
            if turnos_m: info['turnos'] = turnos_m.group(1)
            
            # Extraer hora de entrada (ej. 13:30)
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
    
    # Rango Concierto: 12:30 (750m) a 14:30 (870m)
    rango_concierto = 750 <= mins <= 870

    # 1. CASO DIABLOS (PRÁCTICA - Acepta Seguridad/Local Crew + Preasignado)
    if "SOFTBOL DIABLOS" in titulo:
        if "PREASIGNADO" in titulo and puesto in PUESTOS_ACEPTADOS:
            return True, "DIABLOS PREASIGNADO (Auto-Confirmar)", True
        return True, f"Diablos Detectado: {puesto} sin PREASIGNADO", False

    # 2. CASO VIP (SOAD, ACDC, BTS)
    es_vip = any(vip in titulo for vip in EVENTOS_VIP)
    if es_vip:
        if "RESGUARDO" in titulo:
            return True, "VIP es RESGUARDO (Revisión Manual)", False
        
        # Filtro estricto: Puesto + 1.5 Turnos + Horario de Concierto
        if puesto in PUESTOS_ACEPTADOS and turnos == "1.5":
            if rango_concierto:
                return True, "VIP PERFECTO (Auto-Confirmar)", True
            else:
                return True, f"VIP Manual: Horario fuera de rango ({mins//60}:{mins%60:02d})", False
        
        return True, f"VIP Manual: Puesto {puesto} / Turnos {turnos}", False

    return True, "Evento Nuevo (No VIP)", False

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context()
        page = context.new_page()
        logged = False

        while True:
            try:
                if not logged:
                    page.goto(URL_LOGIN)
                    page.fill("input[name='usuario']", USER)
                    page.fill("input[name='password']", PASS)
                    page.click("button[type='submit']")
                    page.wait_for_timeout(5000)
                    logged = True

                page.goto(URL_EVENTS, wait_until="networkidle")
                
                # Freno: Solo buscar en el contenedor de Disponibles
                disponibles = page.query_selector("#div_eventos_disponibles")
                if disponibles and "No hay eventos disponibles" in disponibles.inner_text():
                    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sin eventos.")
                else:
                    cards = disponibles.query_selector_all(".card.border") if disponibles else []

                    for card in cards:
                        titulo_elem = card.query_selector("h6 a")
                        if not titulo_elem: continue
                        titulo_texto = titulo_elem.inner_text().strip()

                        # Click para extraer tabla
                        titulo_elem.click()
                        page.wait_for_timeout(1000)
                        tabla = card.query_selector(".table-responsive")
                        
                        if tabla:
                            info = extraer_datos_tabla(tabla.inner_html())
                            interesa, motivo, auto = analizar_cazador(info, titulo_texto)

                            if motivo == "Evento Nuevo (No VIP)":
                                send(f"🔔 *EVENTO DISPONIBLE:* {titulo_texto}")
                            elif interesa:
                                if auto:
                                    btn = card.query_selector("button:has-text('CONFIRMAR')")
                                    if btn:
                                        btn.click()
                                        page.wait_for_timeout(4000)
                                        send(f"🎯 *MADIAN: EVENTO CONFIRMADO EXITOSAMENTE*\n📌 {titulo_texto}\n👤 {info['puesto']}\n📊 Turnos: {info['turnos']}")
                                    else:
                                        send(f"⚠️ *ERROR:* Criterios OK pero no vi el botón en {titulo_texto}")
                                else:
                                    send(f"⚠️ *REVISIÓN MANUAL:* {titulo_texto}\n❌ {motivo}")

            except Exception as e:
                print(f"Error: {e}"); logged = False; time.sleep(30)
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
