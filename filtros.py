def _coincide_regla(datos: dict, regla: dict) -> bool:
    """Verifica si un evento cumple todos los criterios de una regla."""
    titulo = datos.get("titulo", "")
    puesto = datos.get("puesto", "")
    turnos = datos.get("turnos", "0")
    mins   = datos.get("mins_entrada", 0)
    lugar  = datos.get("lugar", "")
    preasignado = datos.get("preasignado", False) # El main.py debe enviar esto

    # NUEVO: Filtro estricto de PREASIGNADO
    # Si la regla pide preasignado y el evento NO lo es, rechazar.
    if regla.get("solo_preasignado", False) and not preasignado:
        return False

    # Palabras del título (OR)
    palabras = regla.get("palabras_titulo", [])
    if palabras and not any(p in titulo for p in palabras):
        return False

    # Puesto exacto
    if "puesto" in regla and regla["puesto"] != puesto:
        return False

    # Turnos exactos
    if "turnos" in regla and regla["turnos"] != turnos:
        return False

    # Rango de minutos de entrada
    if "mins_min" in regla and mins < regla["mins_min"]:
        return False
    if "mins_max" in regla and mins > regla["mins_max"]:
        return False

    return True
