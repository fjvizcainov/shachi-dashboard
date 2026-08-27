# Reverse engineering del Breville Joule Oven (app Breville+)

Objetivo: capturar la llamada cloud que la app **Breville+** hace al pulsar
"precalentar", para replicarla desde `JouleOvenAdapter.execute()` y así darle
control real al hub y al MCP. Es exactamente el método por el que nació
`pylamarzocco` para la cafetera.

> **Solo tu propia cuenta y tu propio horno.** Esto va contra los ToS de
> Breville; es riesgo propio. No publiques credenciales ni tokens capturados.

## Por qué el Joule Oven es viable (y la Thermomix no)

| | Joule Oven | Thermomix TM6 |
|---|---|---|
| ¿La app arranca en remoto? | **Sí** (precalentar desde el móvil) | **No** — exige botón físico en el equipo |
| ¿Existe un comando cloud que capturar? | Sí | No hay comando que capturar |
| Precedente | Joule sous-vide original reverseado (gRPC/Firebase) | — |
| Resultado alcanzable | Control headless | Solo lectura (Cookidoo) |

## Montaje de captura

1. **Emulador Android** (Android Studio / Genymotion) o un móvil viejo dedicado.
2. **mitmproxy** como proxy HTTPS:
   ```bash
   pip install mitmproxy
   mitmweb --listen-port 8080
   ```
   Configura el proxy del dispositivo a `IP_DEL_PC:8080` e instala el certificado
   CA de mitmproxy como CA del sistema (emulador con imagen *sin* Google Play para
   poder escribir en el almacén de CAs del sistema).
3. **Certificate pinning**: si la app rechaza el proxy, casi seguro hace pinning.
   Rootea el emulador y usa **Frida** con un script anti-pinning
   (`frida-multiple-unpinning`), o **objection** (`objection -g com.breville... explore`
   → `android sslpinning disable`).

## Qué buscar en el tráfico

- **Login / token**: la primera llamada al abrir sesión. Anota el endpoint de
  auth y cómo se refresca el token (probable OAuth/JWT o Firebase Auth).
- **Descubrimiento del electrodoméstico**: un `GET` que lista tus appliances y
  devuelve un `applianceId` / `deviceId`.
- **El comando de precalentar**: pulsa "precalentar" en la app con el proxy
  grabando y localiza el `POST`. Apunta:
  - URL exacta y método.
  - Cuerpo JSON: nombres de campo para temperatura, modo, y el `op`/`command`.
  - Headers de auth (`Authorization: Bearer ...`) y cualquier header propio.
- **Telemetría / estado**: si la app hace polling o abre un WebSocket/MQTT para
  el estado del horno (temperatura actual, "precalentado listo"). Eso alimenta el
  evento `preheat_ready` del hub.

## De la captura al adaptador

Rellena `JouleOvenAdapter.execute()` en `../api/adapters.py`:

```python
def execute(self, command, params=None):
    params = params or {}
    if command == "preheat":
        # Pega aqui la llamada capturada:
        # r = requests.post(
        #     f"{CLOUD_BASE}/appliances/{self._appliance_id}/commands",
        #     headers={"Authorization": f"Bearer {self._token()}"},
        #     json={"op": "preheat",
        #           "targetTemp": params["temp_c"],
        #           "mode": params.get("mode", "bake")},
        #     timeout=10)
        # r.raise_for_status()
        # return {"ok": True, "raw": r.json()}
        ...
```

En cuanto ese método haga la llamada real, **las tools del MCP y las recetas del
hub funcionan sin cambios** — ambas fachadas pasan por el mismo adaptador.

## Validación

1. Con el driver puesto, `python devices/api/server.py` y:
   ```bash
   curl -X POST localhost:5001/api/devices/joule_oven/execute \
        -H 'Content-Type: application/json' \
        -d '{"command":"preheat","params":{"temp_c":180,"mode":"air_fryer"}}'
   ```
2. Confirma en la app Breville+ y en el propio horno que responde.
3. Solo entonces conecta la tool MCP `oven_preheat` a un flujo automático — y
   siempre con `confirm=True` explícito y supervisión física.

## Herramientas de referencia
- `mitmproxy` / `mitmweb` — captura HTTPS.
- `frida` + `frida-tools`, `objection` — bypass de pinning.
- `Charles Proxy` / `Proxyman` — alternativas GUI a mitmproxy.
- Repos de inspiración: la integración `lamarzocco` de Home Assistant y
  `pylamarzocco` (mismo patrón cloud reverseado).
