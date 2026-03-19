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
CHECK_INTERVAL = 90 # Mantener en 90s para no saturar
TZ = pytz.timezone("America/Mexico_City")

# Variables de Entorno (Ya configuradas en Render)
USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- FILTROS MAESTROS ACTUALIZADOS ---
EVENTOS_VIP = ["SYSTEM OF A DOWN", "SOAD", "ACDC", "AC/DC", "BTS"]
EVENTO_PRUEBA = "SOFTBOL DIABLOS 2026 SERIE DE LA REINA" # Nombre exacto

app = Flask(__name__)

@app.route("/")
def home(): 
    return f"Bot Cazador Madian (Modo Prueba Diablos) Activo - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "inicio": "", "lugar": "", "turnos": "0"}
    try:
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
    except Exception as e:
        print(f"Error extrayendo tabla: {e}")
    return info

def analizar_cazador(info, titulo_card):
    titulo = titulo_card.upper()
    puesto = info['puesto']
    turnos = info['turnos']
    
    # NUEVO: Detección de Preasignado
    es_preasignado = "PREASIGNADO" in titulo

    # --- LÓGICA DE PRUEBA: SOFTBOL DIABLOS ---
    if EVENTO_PRUEBA.upper() in titulo:
        if es_preasignado and puesto == "LOCAL CREW":
            return True, "PRUEBA DIABLOS: Criterios Perfectos", True # AUTO-CONFIRMAR
        else:
            return True, f"Diablos Detectado, pero NO PREASIGNADO o Puesto Incorrecto ({puesto})", False

    # --- LÓGICA VIP NORMAL (ACDC/SOAD/BTS) ---
    es_vip = any(vip in titulo for vip in EVENTOS_VIP)
    if es_vip:
        if "RESGUARDO" in titulo:
            return True, "Es un RESGUARDO VIP (Manual)", False
        
        # Filtro estricto para Estadio GNP
        if puesto == "SEGURIDAD" and turnos == "1.5":
            return True, "VIP PERFECTO (GNP)", True # AUTO-CONFIRMAR
        
        return True, f"VIP Detectado, pero Puesto/Turno no coincide ({puesto} - {turnos})", False
    
    return False, "No es de interés", False

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        logged = False

        while True:
            try:
                now_mx = datetime.now(TZ)
                
                if not logged:
                    print(f"[{now_mx}] Intentando Login...")
                    page.goto(URL_LOGIN, wait_until="networkidle")
                    page.wait_for_timeout(3000)
                    page.fill("input[name='usuario']", USER)
                    page.fill("input[name='password']", PASS)
                    page.click("button[type='submit']")
                    page.wait_for_timeout(6000)
                    logged = True
                    print(f"[{now_mx}] Login Exitoso.")

                page.goto(URL_EVENTS, wait_until="domcontentloaded")
                page.wait_for_timeout(3000) # Espera extra para render de tablas

                cards = page.query_selector_all(".card.border")
                eventos_vistos = []

                for card in cards:
                    titulo_elem = card.query_selector("h6 a")
                    if not titulo_elem: continue
                    titulo_texto = titulo_elem.inner_text().strip()
                    
                    eventos_vistos.append(titulo_texto)

                    # Desplegar para ver tabla (Necesario para analizar)
                    try:
                        titulo_elem.click()
                        page.wait_for_timeout(1000)
                        tabla_elem = card.query_selector(".table-responsive")
                        if not tabla_elem: continue
                        
                        info = extraer_datos_tabla(tabla_elem.inner_html())
                        interesa, motivo, auto_confirmar = analizar_cazador(info, titulo_texto)

                        if interesa:
                            if auto_confirmar:
                                btn = card.query_selector("button:has-text('CONFIRMAR')")
                                if btn:
                                    #btn.click() # COMENTADO PARA NO CONFIRMAR REALMENTE EN LA PRIMERA VUELTA
                                    #page.wait_for_timeout(3000)
                                    send(f"🎯 *MADIAN: (SIMULACIÓN DE ÉXITO)*\n📌 {titulo_texto}\n👤 {info['puesto']}\n📊 Turnos: {info['turnos']}\n✅ Criterios perfectos.")
                                else:
                                    send(f"⚠️ *MADIAN:* Criterios OK pero no hallé el botón en {titulo_texto}")
                            else:
                                # VIP/Prueba Detectado pero algo no cuadra (ej. es Local Crew o no es 1.5), enviamos aviso
                                send(f"🔔 *AVISO DE REVISIÓN:* {titulo_texto}\n❌ {motivo}\n📍 {info['lugar']}")
                    except:
                        pass # Error al hacer clic en una card específica

                # Notificación de escaneo silencioso (solo si quieres, la quité para no spam)
                print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Escaneado completado. Vistos: {len(eventos_vistos)}")

            except Exception as e:
                print(f"Error Crítico: {e}"); logged = False; time.sleep(30)
            
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
