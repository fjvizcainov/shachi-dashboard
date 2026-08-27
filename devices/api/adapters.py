"""
Adaptadores de dispositivos compartidos por las dos fachadas del hub:
  - REST  (api/server.py)      -> motor de recetas del dashboard
  - MCP   (mcp/server.py)      -> control en lenguaje natural desde Claude

Cada dispositivo implementa la misma interfaz. El driver se escribe UNA vez
aqui; ninguna de las dos fachadas reimplementa la logica de control.
Ver ../API_RESEARCH.md para la viabilidad real de cada integracion.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Credenciales (variables de entorno, nunca en el front ni en el repo)
LAMARZOCCO_USER = os.getenv("LAMARZOCCO_USER", "")
LAMARZOCCO_PASS = os.getenv("LAMARZOCCO_PASS", "")
GARMIN_USER = os.getenv("GARMIN_USER", "")
GARMIN_PASS = os.getenv("GARMIN_PASS", "")
PELOTON_USER = os.getenv("PELOTON_USER", "")
PELOTON_PASS = os.getenv("PELOTON_PASS", "")
BREVILLE_USER = os.getenv("BREVILLE_USER", "")
BREVILLE_PASS = os.getenv("BREVILLE_PASS", "")
# Home Assistant como backend local (enchufes inteligentes, plan B del grinder)
HA_URL = os.getenv("HA_URL", "")
HA_TOKEN = os.getenv("HA_TOKEN", "")


class DeviceAdapter:
    """Interfaz comun de todos los dispositivos."""

    id = "base"
    name = "Base"
    api_status = "none"          # official | partner | unofficial | none
    requires_confirmation = False  # True para acciones con calor / riesgo fisico

    def configured(self):
        return False

    def get_status(self):
        return {"connected": False, "detail": "no configurado"}

    def execute(self, command, params=None):
        raise NotImplementedError(f"{self.name}: comando '{command}' no soportado")


class LaMarzoccoAdapter(DeviceAdapter):
    """La Marzocco Linea Mini R via pylamarzocco (API cloud no oficial)."""

    id = "lamarzocco"
    name = "La Marzocco Linea Mini R"
    api_status = "unofficial"

    def configured(self):
        return bool(LAMARZOCCO_USER and LAMARZOCCO_PASS)

    def get_status(self):
        if not self.configured():
            return {"connected": False, "detail": "faltan LAMARZOCCO_USER/PASS"}
        # TODO: pylamarzocco -> LaMarzoccoCloudClient(...).get_thing_dashboard()
        return {"connected": True, "detail": "stub: pendiente conectar pylamarzocco"}

    def execute(self, command, params=None):
        if command in ("power_on", "power_off", "set_boiler_temp"):
            # TODO: pylamarzocco -> set_power / set_coffee_target_temperature
            logger.info("LaMarzocco: %s %s", command, params)
            return {"ok": True, "stub": True}
        return super().execute(command, params)


class GarminAdapter(DeviceAdapter):
    """Garmin via garminconnect (no oficial) o Health API (partner)."""

    id = "garmin"
    name = "Garmin"
    api_status = "partner"

    def configured(self):
        return bool(GARMIN_USER and GARMIN_PASS)

    def get_status(self):
        if not self.configured():
            return {"connected": False, "detail": "faltan GARMIN_USER/PASS"}
        return {"connected": True, "detail": "stub: pendiente conectar garminconnect"}

    def execute(self, command, params=None):
        if command in ("read_daily_metrics", "create_workout"):
            logger.info("Garmin: %s %s", command, params)
            return {"ok": True, "stub": True}
        return super().execute(command, params)


class PelotonAdapter(DeviceAdapter):
    """Peloton via API REST no oficial (api.onepeloton.com)."""

    id = "peloton"
    name = "Peloton"
    api_status = "unofficial"

    def configured(self):
        return bool(PELOTON_USER and PELOTON_PASS)

    def get_status(self):
        if not self.configured():
            return {"connected": False, "detail": "faltan PELOTON_USER/PASS"}
        return {"connected": True, "detail": "stub: pendiente conectar pylotoncycle"}

    def execute(self, command, params=None):
        if command == "read_last_workout":
            logger.info("Peloton: %s", command)
            return {"ok": True, "stub": True}
        return super().execute(command, params)


class JouleOvenAdapter(DeviceAdapter):
    """Breville Joule Oven Air Fryer Pro.

    NO tiene API publica. Este adaptador es el punto de enchufe para lo que
    salga del reverse engineering de la app Breville+ (ver ../mcp/REVERSE_ENGINEERING.md).
    La app SI puede arrancar el horno en remoto -> existe un comando cloud
    real que capturar y replicar aqui.

    Comandos con calor -> requires_confirmation = True (seguridad).
    """

    id = "joule_oven"
    name = "Breville Joule Oven Air Fryer Pro"
    api_status = "none"
    requires_confirmation = True

    def configured(self):
        # Cuando el driver este listo: bool(BREVILLE_USER and BREVILLE_PASS)
        return False

    def get_status(self):
        if not self.configured():
            return {"connected": False,
                    "detail": "sin driver: pendiente reverse engineering de Breville+"}
        return {"connected": True, "detail": "stub"}

    def execute(self, command, params=None):
        params = params or {}
        if command == "preheat":
            temp = params.get("temp_c")
            mode = params.get("mode", "bake")
            # TODO: reproducir la llamada cloud capturada de Breville+
            #   POST {cloud}/appliances/{id}/commands  {op: "preheat", temp, mode}
            logger.warning("JouleOven preheat -> temp=%s mode=%s (driver pendiente)", temp, mode)
            return {"ok": False, "pending_driver": True,
                    "detail": "capturar la llamada de Breville+ y pegarla aqui"}
        if command == "set_timer":
            logger.warning("JouleOven set_timer %s (driver pendiente)", params)
            return {"ok": False, "pending_driver": True}
        if command == "stop":
            logger.warning("JouleOven stop (driver pendiente)")
            return {"ok": False, "pending_driver": True}
        return super().execute(command, params)


class ThermomixAdapter(DeviceAdapter):
    """Thermomix TM6.

    Techo DURO: Vorwerk exige confirmacion fisica en el equipo para cualquier
    coccion; ni la propia app arranca en remoto. No hay comando de control que
    capturar. Este adaptador es SOLO LECTURA (contexto Cookidoo).
    """

    id = "thermomix"
    name = "Thermomix TM6"
    api_status = "none"

    def configured(self):
        return False

    def get_status(self):
        return {"connected": False,
                "detail": "solo lectura via Cookidoo; sin control remoto (diseno de Vorwerk)"}

    def execute(self, command, params=None):
        if command == "read_active_recipe":
            # TODO: wrapper no oficial de Cookidoo -> receta y paso actual
            logger.info("Thermomix read_active_recipe (stub Cookidoo)")
            return {"ok": True, "stub": True, "read_only": True}
        # Cualquier comando de control es imposible por diseno
        raise NotImplementedError(
            f"{self.name}: control remoto no posible (Vorwerk exige confirmacion fisica)")


class HomeAssistantAdapter(DeviceAdapter):
    """Puente generico a Home Assistant: enchufes inteligentes y todo lo que
    no tenga API directa (plan B del grinder Mahlkoenig)."""

    id = "home_assistant"
    name = "Home Assistant"
    api_status = "official"

    def configured(self):
        return bool(HA_URL and HA_TOKEN)

    def get_status(self):
        if not self.configured():
            return {"connected": False, "detail": "faltan HA_URL/HA_TOKEN"}
        return {"connected": True, "detail": "stub: pendiente ping a /api/"}

    def execute(self, command, params=None):
        if command == "call_service" and params:
            # TODO: POST {HA_URL}/api/services/{domain}/{service}
            #       headers: Authorization: Bearer HA_TOKEN
            logger.info("HA call_service: %s", params)
            return {"ok": True, "stub": True}
        return super().execute(command, params)


class StubAdapter(DeviceAdapter):
    """Dispositivos sin via de integracion (grinder directo, Tonal escritura)."""

    def __init__(self, id_, name, api_status="none", reason=""):
        self.id = id_
        self.name = name
        self.api_status = api_status
        self.reason = reason

    def get_status(self):
        return {"connected": False, "detail": self.reason}


def build_adapters():
    """Registro unico {id: adapter}. Lo consumen REST y MCP por igual."""
    return {a.id: a for a in [
        LaMarzoccoAdapter(),
        GarminAdapter(),
        PelotonAdapter(),
        JouleOvenAdapter(),
        ThermomixAdapter(),
        HomeAssistantAdapter(),
        StubAdapter("mahlkonig", "Mahlkoenig X54", "none",
                    "sin API; usar home_assistant con enchufe inteligente"),
        StubAdapter("tonal", "Tonal", "unofficial",
                    "GraphQL interna reverseada; solo lectura, pendiente adaptador"),
    ]}


ADAPTERS = build_adapters()
