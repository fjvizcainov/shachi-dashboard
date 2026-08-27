"""
Shachi Device Hub - servidor MCP (FastMCP)

Segunda fachada de los mismos adaptadores que usa la API REST del hub.
Expone el control de dispositivos como TOOLS de Claude, para poder decir en
lenguaje natural cosas como:

    "precalienta el horno a 180 en modo air fryer cuando la Thermomix
     vaya por el paso 4"

El driver de cada dispositivo vive en devices/api/adapters.py y se escribe
UNA sola vez. Aqui solo se envuelve en tools MCP.

Conectar a Claude Code:
    claude mcp add shachi-devices -- python /ruta/devices/mcp/server.py

Requiere:  pip install "mcp[cli]"
"""

import sys
import os
import logging

# Reutilizamos los adaptadores del hub (carpeta hermana ../api)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from adapters import ADAPTERS  # noqa: E402

try:
    # mcp >= 2.x: FastMCP se renombro a MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:
    try:
        # mcp 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError:
        sys.stderr.write(
            "Falta el SDK de MCP. Instala con:  pip install \"mcp[cli]\"\n")
        raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shachi-devices-mcp")

mcp = _Server("shachi-devices")


# ── Herramientas transversales ───────────────────────────────────────────

@mcp.tool()
def list_devices() -> list[dict]:
    """Lista los dispositivos del hub con su viabilidad de integracion.

    api_status: official | partner | unofficial | none
    """
    return [
        {"id": a.id, "name": a.name, "api_status": a.api_status,
         "configured": a.configured(),
         "requires_confirmation": getattr(a, "requires_confirmation", False)}
        for a in ADAPTERS.values()
    ]


@mcp.tool()
def device_status(device_id: str) -> dict:
    """Estado de un dispositivo concreto (conectado, detalle de config)."""
    adapter = ADAPTERS.get(device_id)
    if adapter is None:
        return {"error": f"dispositivo desconocido: {device_id}"}
    return {"id": adapter.id, "name": adapter.name, **adapter.get_status()}


def _run(device_id: str, command: str, params: dict | None = None) -> dict:
    """Ejecuta un comando en un adaptador y normaliza el resultado/errores."""
    adapter = ADAPTERS.get(device_id)
    if adapter is None:
        return {"ok": False, "error": f"dispositivo desconocido: {device_id}"}
    try:
        result = adapter.execute(command, params or {})
        return {"ok": True, "device": device_id, "command": command, "result": result}
    except NotImplementedError as exc:
        return {"ok": False, "device": device_id, "command": command, "error": str(exc)}


# ── Cafe ─────────────────────────────────────────────────────────────────

@mcp.tool()
def coffee_power(on: bool = True) -> dict:
    """Enciende o apaga la La Marzocco Linea Mini R."""
    return _run("lamarzocco", "power_on" if on else "power_off")


@mcp.tool()
def coffee_set_temp(temp_c: float) -> dict:
    """Fija la temperatura de la caldera de cafe de la La Marzocco (en grados C)."""
    return _run("lamarzocco", "set_boiler_temp", {"temp_c": temp_c})


@mcp.tool()
def grinder_start() -> dict:
    """Activa la molienda del Mahlkoenig via enchufe inteligente de Home Assistant.

    El grinder no tiene API: lo controla un enchufe con medicion de energia.
    """
    return _run("home_assistant", "call_service",
                {"domain": "switch", "service": "turn_on",
                 "entity_id": "switch.grinder_mahlkonig"})


# ── Cocina ───────────────────────────────────────────────────────────────

@mcp.tool()
def oven_preheat(temp_c: float, mode: str = "bake", confirm: bool = False) -> dict:
    """Precalienta el Breville Joule Oven.

    ACCION CON CALOR: requiere confirm=True explicito. Encender un horno en
    remoto sin nadie delante es un riesgo real; por eso esta tool no ejecuta
    hasta que se confirma.

    Args:
        temp_c: temperatura objetivo en grados C.
        mode:   bake | air_fryer | roast | broil ...
        confirm: debe ser True para ejecutar de verdad.
    """
    if not confirm:
        return {"ok": False, "needs_confirmation": True,
                "message": f"Vas a precalentar el horno a {temp_c} C en modo {mode}. "
                           "Confirma que hay supervision fisica y repite con confirm=True."}
    return _run("joule_oven", "preheat", {"temp_c": temp_c, "mode": mode})


@mcp.tool()
def oven_stop(confirm: bool = False) -> dict:
    """Apaga / detiene el Breville Joule Oven."""
    if not confirm:
        return {"ok": False, "needs_confirmation": True,
                "message": "Confirma con confirm=True para apagar el horno."}
    return _run("joule_oven", "stop")


@mcp.tool()
def thermomix_active_recipe() -> dict:
    """Lee la receta y el paso activo de la Thermomix (SOLO LECTURA via Cookidoo).

    La Thermomix no admite control remoto por diseno de Vorwerk; esta tool
    sirve como disparador/contexto, no como actuador.
    """
    return _run("thermomix", "read_active_recipe")


# ── Fitness / salud ──────────────────────────────────────────────────────

@mcp.tool()
def garmin_daily_metrics() -> dict:
    """Lee las metricas del dia de Garmin (FC, sueno, body battery, actividades)."""
    return _run("garmin", "read_daily_metrics")


@mcp.tool()
def garmin_create_workout(name: str, description: str = "") -> dict:
    """Crea un entrenamiento en Garmin Connect (p. ej. consolidar Tonal + Peloton)."""
    return _run("garmin", "create_workout", {"name": name, "description": description})


@mcp.tool()
def peloton_last_workout() -> dict:
    """Lee las metricas de la ultima clase de Peloton."""
    return _run("peloton", "read_last_workout")


if __name__ == "__main__":
    logger.info("Iniciando servidor MCP shachi-devices (stdio)...")
    mcp.run()
