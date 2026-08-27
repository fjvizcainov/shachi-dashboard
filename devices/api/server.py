"""
Shachi Device Hub - API Server (scaffold)
Integracion de dispositivos: cafe, cocina, fitness y wearables.

Mismo despliegue que api/server.py (Render.com / gunicorn).
Cada dispositivo se integra via un adaptador con interfaz comun; los que
no tienen API viable quedan como stubs honestos (ver ../API_RESEARCH.md).
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Credenciales (variables de entorno, nunca en el front)
LAMARZOCCO_USER = os.getenv("LAMARZOCCO_USER", "")
LAMARZOCCO_PASS = os.getenv("LAMARZOCCO_PASS", "")
GARMIN_USER = os.getenv("GARMIN_USER", "")
GARMIN_PASS = os.getenv("GARMIN_PASS", "")
PELOTON_USER = os.getenv("PELOTON_USER", "")
PELOTON_PASS = os.getenv("PELOTON_PASS", "")
# Home Assistant como backend local (enchufes inteligentes, plan B del grinder)
HA_URL = os.getenv("HA_URL", "")          # p. ej. https://mi-ha.duckdns.org
HA_TOKEN = os.getenv("HA_TOKEN", "")      # long-lived access token


# ── Adaptadores ──────────────────────────────────────────────────────────

class DeviceAdapter:
    """Interfaz comun de todos los dispositivos."""

    id = "base"
    name = "Base"
    api_status = "none"  # official | partner | unofficial | none

    def configured(self):
        return False

    def get_status(self):
        return {"connected": False, "detail": "no configurado"}

    def execute(self, command, params=None):
        raise NotImplementedError(f"{self.name}: comando '{command}' no soportado")


class LaMarzoccoAdapter(DeviceAdapter):
    """La Marzocco Linea Mini R via pylamarzocco (API cloud no oficial).

    Comandos previstos: power_on, power_off, set_boiler_temp.
    Eventos: machine_ready, brewing_started.
    """

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
        # TODO: garminconnect -> Garmin(user, pass).login()
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
        # command = "call_service", params = {domain, service, entity_id}
        if command == "call_service" and params:
            # TODO: POST {HA_URL}/api/services/{domain}/{service}
            #       headers: Authorization: Bearer HA_TOKEN
            logger.info("HA call_service: %s", params)
            return {"ok": True, "stub": True}
        return super().execute(command, params)


class StubAdapter(DeviceAdapter):
    """Dispositivos sin via de integracion todavia (Thermomix, Joule Oven,
    Tonal escritura, grinder directo). Mantienen contrato y devuelven 501."""

    def __init__(self, id_, name, api_status="none", reason=""):
        self.id = id_
        self.name = name
        self.api_status = api_status
        self.reason = reason

    def get_status(self):
        return {"connected": False, "detail": self.reason}


ADAPTERS = {a.id: a for a in [
    LaMarzoccoAdapter(),
    GarminAdapter(),
    PelotonAdapter(),
    HomeAssistantAdapter(),
    StubAdapter("mahlkonig", "Mahlkoenig X54", "none",
                "sin API; usar HomeAssistantAdapter con enchufe inteligente"),
    StubAdapter("thermomix", "Thermomix TM6", "none",
                "Vorwerk no expone API de dispositivo; solo Cookidoo lectura"),
    StubAdapter("joule_oven", "Breville Joule Oven", "none",
                "app Breville+ sin API publica"),
    StubAdapter("tonal", "Tonal", "unofficial",
                "GraphQL interna reverseada; solo lectura, pendiente adaptador"),
]}


# ── Motor de reglas (en memoria; persistir en JSON/DB al crecer) ─────────

RULES = []  # {id, name, trigger: {device, event}, action: {device, command, params}, enabled}


def run_rule(rule):
    """Ejecuta la accion de una regla y devuelve el resultado."""
    action = rule["action"]
    adapter = ADAPTERS.get(action["device"])
    if adapter is None:
        return {"ok": False, "error": f"dispositivo desconocido: {action['device']}"}
    try:
        result = adapter.execute(action["command"], action.get("params"))
        return {"ok": True, "result": result}
    except NotImplementedError as exc:
        return {"ok": False, "error": str(exc)}


# ── Endpoints ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({
        "service": "Shachi Device Hub API",
        "version": "0.1.0",
        "status": "running",
        "endpoints": ["/api/devices", "/api/devices/<id>/status",
                      "/api/devices/<id>/execute", "/api/rules",
                      "/api/events/<device_id>/<event>"],
    })


@app.route('/api/devices')
def list_devices():
    return jsonify([
        {"id": a.id, "name": a.name, "api_status": a.api_status,
         "configured": a.configured()}
        for a in ADAPTERS.values()
    ])


@app.route('/api/devices/<device_id>/status')
def device_status(device_id):
    adapter = ADAPTERS.get(device_id)
    if adapter is None:
        return jsonify({"error": "dispositivo desconocido"}), 404
    return jsonify({"id": adapter.id, **adapter.get_status()})


@app.route('/api/devices/<device_id>/execute', methods=['POST'])
def device_execute(device_id):
    adapter = ADAPTERS.get(device_id)
    if adapter is None:
        return jsonify({"error": "dispositivo desconocido"}), 404
    body = request.get_json(silent=True) or {}
    command = body.get("command", "")
    try:
        result = adapter.execute(command, body.get("params"))
        return jsonify({"ok": True, "result": result})
    except NotImplementedError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 501


@app.route('/api/rules', methods=['GET', 'POST'])
def rules():
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        for field in ("name", "trigger", "action"):
            if field not in body:
                return jsonify({"error": f"falta el campo '{field}'"}), 400
        rule = {
            "id": f"r{len(RULES) + 1}",
            "name": body["name"],
            "trigger": body["trigger"],
            "action": body["action"],
            "enabled": body.get("enabled", True),
            "created": datetime.now().isoformat(),
        }
        RULES.append(rule)
        return jsonify(rule), 201
    return jsonify(RULES)


@app.route('/api/events/<device_id>/<event>', methods=['POST'])
def ingest_event(device_id, event):
    """Punto de entrada de eventos (webhook desde Home Assistant, poller de
    Garmin/Peloton, etc.). Dispara las reglas cuyo trigger coincida."""
    fired = []
    for rule in RULES:
        trig = rule["trigger"]
        if rule["enabled"] and trig.get("device") == device_id and trig.get("event") == event:
            fired.append({"rule": rule["id"], **run_rule(rule)})
    logger.info("evento %s/%s -> %d reglas disparadas", device_id, event, len(fired))
    return jsonify({"event": f"{device_id}/{event}", "fired": fired})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
