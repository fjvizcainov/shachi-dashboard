# Device Hub — servidor MCP

Segunda fachada de los adaptadores del hub (`devices/api/adapters.py`), expuesta
como **tools de Claude** vía el protocolo MCP. El mismo driver que usa el motor
de recetas REST se controla ahora en lenguaje natural.

## Qué es (y qué NO es) un MCP aquí

- **Es** un envoltorio: convierte cada `adapter.execute(...)` en una tool que
  Claude puede invocar. La lógica de control vive en `../api/adapters.py`, no aquí.
- **No es** una capacidad nueva: el MCP no puede controlar nada que el adaptador
  no sepa hacer. Si el driver de un dispositivo es un stub, la tool devuelve
  `pending_driver`.

## Instalar y conectar

```bash
pip install "mcp[cli]"

# Claude Code (stdio):
claude mcp add shachi-devices -- python /ruta/a/devices/mcp/server.py

# Probar el servidor de forma aislada con el inspector:
mcp dev devices/mcp/server.py
```

Credenciales por variables de entorno (nunca en el repo). Las lee
`adapters.py`: `LAMARZOCCO_USER/PASS`, `GARMIN_USER/PASS`, `PELOTON_USER/PASS`,
`HA_URL/HA_TOKEN`, y (cuando exista el driver) `BREVILLE_USER/PASS`.

## Tools expuestas

| Tool | Dispositivo | Estado |
|------|-------------|--------|
| `list_devices` / `device_status` | — | listo |
| `coffee_power`, `coffee_set_temp` | La Marzocco | driver stub (pylamarzocco) |
| `grinder_start` | Mahlkönig vía enchufe HA | driver stub (Home Assistant) |
| `oven_preheat`, `oven_stop` | Joule Oven | **requiere confirmación**; driver pendiente de reverse engineering |
| `thermomix_active_recipe` | Thermomix | **solo lectura** (Cookidoo); control imposible por diseño |
| `garmin_daily_metrics`, `garmin_create_workout` | Garmin | driver stub (garminconnect) |
| `peloton_last_workout` | Peloton | driver stub (pylotoncycle) |

## Seguridad: comandos con calor

`oven_preheat` y `oven_stop` no ejecutan hasta recibir `confirm=True`. Encender
un horno en remoto sin supervisión es exactamente el riesgo por el que los
fabricantes capan esta función; la tool obliga a una confirmación explícita.
El adaptador marca estos dispositivos con `requires_confirmation = True`.

## Los dos casos de cocina

- **Joule Oven** → candidato real. La app Breville+ arranca el horno en remoto,
  así que existe un comando cloud que capturar. Ver
  [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md). Al conseguirlo, se rellena
  `JouleOvenAdapter.execute()` y las tools funcionan sin tocar el MCP.
- **Thermomix** → techo duro. Vorwerk exige confirmación física en el equipo
  para cualquier cocción; ni la propia app arranca en remoto. No hay comando que
  capturar. Se integra como **sensor/contexto** (lectura de Cookidoo), no como
  actuador. La receta "handoff Thermomix → Joule" sigue siendo viable: el
  disparador es de lectura, la acción va al horno.
