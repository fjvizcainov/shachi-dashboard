"""
Shachi Device Hub - API Server (scaffold)
Integracion de dispositivos: cafe, cocina, fitness y wearables.

Mismo despliegue que api/server.py (Render.com / gunicorn).
Cada dispositivo se integra via un adaptador con interfaz comun; los que
no tienen API viable quedan como stubs honestos (ver ../API_RESEARCH.md).
"""

from flask import Flask, jsonify, request
import os
from datetime import datetime
import logging

try:  # ejecutado como paquete (python -m devices.api.server)
    from .adapters import ADAPTERS
except ImportError:  # ejecutado directo (python server.py)
    from adapters import ADAPTERS

try:
    from flask_cors import CORS
except ImportError:  # CORS es opcional para arrancar en local
    CORS = None

app = Flask(__name__)
if CORS:
    CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
