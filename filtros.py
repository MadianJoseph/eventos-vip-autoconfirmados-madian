"""
filtros.py — Módulo de decisión de eventos
==========================================
Este archivo es el ÚNICO que debes editar para personalizar qué eventos
se confirman automáticamente, cuáles se notifican y cuáles se ignoran.

La función principal es:

    analizar_evento(datos_evento) -> tuple[str, str]

Retorna una tupla:
    accion  : "CONFIRMAR" | "NOTIFICAR" | "IGNORAR"
    motivo  : Texto descriptivo (aparece en Telegram)

El dict 'datos_evento' que recibe tiene estas claves garantizadas:
    titulo        (str)   Nombre del evento en mayúsculas
    puesto        (str)   Ej: "SEGURIDAD", "LOCAL CREW"
    lugar         (str)   Nombre del inmueble en mayúsculas
    turnos        (str)   Número de turnos, ej: "1", "1.5"
    horario_texto (str)   Texto completo del horario (para depuración)
    mins_entrada  (int)   Hora de entrada en minutos totales del día
                          (Ej: 930 = 15:30 h, 660 = 11:00 h)
    fecha         (str)   Fecha en formato "DD/MM/YYYY"
"""

# ══════════════════════════════════════════════════════════════════════════════
# ① CONFIGURACIÓN — EDITA ESTOS VALORES
# ══════════════════════════════════════════════════════════════════════════════

# Puestos que te interesan (siempre en MAYÚSCULAS)
PUESTOS_ACEPTADOS = [
    "SEGURIDAD",
    "LOCAL CREW",
]

# Lugares que NUNCA quieres tomar (siempre en MAYÚSCULAS)
LUGARES_BLOQUEADOS = [
    "ESTADIO AZTECA",
    "AZTECA",
    "ESTADIO CIUDAD DE LOS DEPORTES",
]

# ── Eventos que se confirman AUTOMÁTICAMENTE ──────────────────────────────────
# Cada regla es un dict con los campos que DEBEN coincidir.
# Campos opcionales: si no aparecen, no se evalúan (comodín).
#
# Claves disponibles:
#   palabras_titulo  : lista de palabras; el título debe contener AL MENOS UNA
#   puesto           : str exacto
#   turnos           : str exacto ("1", "1.5", etc.)
#   mins_min         : hora mínima de entrada (en minutos del día)
#   mins_max         : hora máxima de entrada (en minutos del día)
#   lugar_excluir    : lista de palabras que NO debe contener el lugar
#
# Referencia rápida de horas → minutos:
#   06:00 = 360    08:00 = 480    10:00 = 600    11:00 = 660
#   12:00 = 720    13:30 = 810    14:00 = 840    15:30 = 930
#   16:00 = 960    18:00 = 1080   20:00 = 1200   22:00 = 1320

REGLAS_AUTO_CONFIRMAR = [

    # ── AC/DC 2026 — Turno completo (15:30) ───────────────────────────────────
    {
        "palabras_titulo": ["AC DC 2026", "ACDC", "AC/DC"],
        "puesto":   "SEGURIDAD",
        "turnos":   "1",
        "mins_min": 930,
        "mins_max": 930,
        "motivo":   "AC/DC 2026 — Turno 1 (15:30 h)",
    },

    # ── AC/DC 2026 — Turno 1.5 (13:30) ───────────────────────────────────────
    {
        "palabras_titulo": ["AC DC 2026", "ACDC", "AC/DC"],
        "puesto":   "SEGURIDAD",
        "turnos":   "1.5",
        "mins_min": 810,
        "mins_max": 810,
        "motivo":   "AC/DC 2026 — Turno 1.5 (13:30 h)",
    },

    # ── SYSTEM OF A DOWN — cualquier turno, entrada 12–15 h ──────────────────
    {
        "palabras_titulo": ["SYSTEM OF A DOWN", "SOAD"],
        "puesto":   "SEGURIDAD",
        "turnos":   "1.5",
        "mins_min": 720,
        "mins_max": 870,
        "motivo":   "SOAD — Turno 1.5 (rango estándar)",
    },

    # ── BTS — Seguridad turno 1.5 ─────────────────────────────────────────────
    {
        "palabras_titulo": ["BTS"],
        "puesto":   "SEGURIDAD",
        "turnos":   "1.5",
        "mins_min": 750,
        "mins_max": 870,
        "motivo":   "BTS — Turno 1.5",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # ✏️  AGREGA TUS PROPIAS REGLAS AQUÍ siguiendo el mismo formato
    # ─────────────────────────────────────────────────────────────────────────
    # Ejemplo: confirmar cualquier evento con "COLDPLAY" en el título
    # {
    #     "palabras_titulo": ["COLDPLAY"],
    #     "puesto":   "SEGURIDAD",
    #     "motivo":   "Coldplay — confirmación automática",
    # },
]

# ── Palabras clave que siempre generan NOTIFICACIÓN (sin auto-confirmar) ──────
# Úsalas para eventos VIP que quieres revisar manualmente antes de confirmar.
PALABRAS_NOTIFICAR = [
    "RESGUARDO",
    "METALLICA",
    "BAD BUNNY",
    "MADONNA",
    "ROLLING STONES",
    # Agrega aquí otros artistas de interés que no quieras confirmar a ciegas
]


# ══════════════════════════════════════════════════════════════════════════════
# ② LÓGICA DE DECISIÓN — generalmente no necesitas editar esto
# ══════════════════════════════════════════════════════════════════════════════

def _coincide_regla(datos: dict, regla: dict) -> bool:
    """Verifica si un evento cumple todos los criterios de una regla."""
    titulo = datos.get("titulo", "")
    puesto = datos.get("puesto", "")
    turnos = datos.get("turnos", "0")
    mins   = datos.get("mins_entrada", 0)
    lugar  = datos.get("lugar", "")

    # Palabras del título (OR): al menos una debe estar presente
    palabras = regla.get("palabras_titulo", [])
    if palabras and not any(p in titulo for p in palabras):
        return False

    # Puesto exacto (si se especifica)
    if "puesto" in regla and regla["puesto"] != puesto:
        return False

    # Turnos exactos (si se especifica)
    if "turnos" in regla and regla["turnos"] != turnos:
        return False

    # Rango de minutos de entrada
    if "mins_min" in regla and mins < regla["mins_min"]:
        return False
    if "mins_max" in regla and mins > regla["mins_max"]:
        return False

    # Exclusión de lugar
    excluir = regla.get("lugar_excluir", [])
    if any(ex in lugar for ex in excluir):
        return False

    return True


def analizar_evento(datos_evento: dict) -> tuple[str, str]:
    """
    Punto de entrada principal.

    Parámetros
    ----------
    datos_evento : dict con claves garantizadas por main.py

    Retorna
    -------
    (accion, motivo)
        accion  → "CONFIRMAR" | "NOTIFICAR" | "IGNORAR"
        motivo  → descripción legible para el mensaje de Telegram
    """
    titulo = datos_evento.get("titulo", "")
    puesto = datos_evento.get("puesto", "")
    lugar  = datos_evento.get("lugar", "")

    # ── PASO 1: Bloquear lugares no deseados ──────────────────────────────────
    for bloqueado in LUGARES_BLOQUEADOS:
        if bloqueado in lugar or bloqueado in titulo:
            return "IGNORAR", f"Lugar bloqueado: {bloqueado}"

    # ── PASO 2: Bloquear puestos no aceptados ─────────────────────────────────
    if puesto and puesto not in PUESTOS_ACEPTADOS:
        return "IGNORAR", f"Puesto no aceptado: {puesto}"

    # ── PASO 3: Verificar reglas de auto-confirmación ─────────────────────────
    for regla in REGLAS_AUTO_CONFIRMAR:
        if _coincide_regla(datos_evento, regla):
            return "CONFIRMAR", regla.get("motivo", "Regla auto-confirmar")

    # ── PASO 4: Verificar palabras de notificación forzada ────────────────────
    for palabra in PALABRAS_NOTIFICAR:
        if palabra in titulo:
            return "NOTIFICAR", f"Evento de interés: {palabra}"

    # ── PASO 5: Si el puesto es aceptado, notificar (revisión manual) ─────────
    if puesto in PUESTOS_ACEPTADOS:
        return "NOTIFICAR", f"Disponible — revisión manual ({puesto})"

    # ── PASO 6: Ignorar todo lo demás ─────────────────────────────────────────
    return "IGNORAR", "Sin criterio de interés"
