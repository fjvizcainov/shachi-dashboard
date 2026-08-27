# Device Hub — Investigación de APIs por dispositivo

Estado real (a agosto 2026, según conocimiento disponible — verificar antes de implementar) de qué se puede
integrar de cada dispositivo que queremos conectar, y por qué vía.

Leyenda de viabilidad:
- 🟢 **API oficial** — documentada y soportada por el fabricante
- 🔵 **API partner** — oficial pero requiere aprobación/programa de desarrolladores
- 🟡 **API no oficial** — reverseada por la comunidad; funciona pero puede romperse sin aviso
- 🔴 **Sin API** — sin vía directa conocida; solo trucos (enchufes inteligentes, atajos, OCR de app, etc.)

---

## ☕ Café

### La Marzocco Linea Mini R (2023) — 🟡 API no oficial (muy usable)
- La máquina se conecta al cloud de La Marzocco (app **La Marzocco Home**).
- La comunidad reverseó la API cloud: librería Python [`pylamarzocco`](https://github.com/zweckj/pylamarzocco),
  que es la base de la **integración oficial de Home Assistant** (`lamarzocco`).
- Qué se puede hacer: encender/apagar, leer y fijar temperatura de calderas, programar encendido,
  detectar estado de extracción/preparación, modo eco.
- **Veredicto:** integración realista hoy mismo. Es el mejor "trigger" del ecosistema café.

### Mahlkönig X54 (grinder) — 🔴 Sin API
- El X54 tiene WiFi y app propia, pero **no hay API pública** ni un esfuerzo de reverse engineering
  maduro publicado por la comunidad.
- **Plan B para "Grind by Sync":**
  1. **Enchufe inteligente con medición de energía** (p. ej. Shelly Plug S): el hub enciende el enchufe
     cuando La Marzocco está lista; con la tolva cargada y el temporizador de dosis del grinder,
     la molienda arranca al recibir corriente (verificar comportamiento al restaurar energía).
  2. Detección de "molienda terminada" por caída de consumo eléctrico del enchufe.
  3. Largo plazo: sniffear el tráfico BLE/WiFi de la app del X54 (proyecto de reverse engineering propio).
- **Veredicto:** el sync café es viable, pero el lado grinder va por enchufe inteligente, no por API.

---

## 🍲 Cocina

### Thermomix TM6 — 🔴 Sin API de dispositivo
- Vorwerk no expone control del equipo. El TM6 solo habla con **Cookidoo**.
- Existen wrappers **no oficiales de Cookidoo** (recetas, lista de compra, planificador) — útiles para
  contexto ("qué receta está cocinando"), no para controlar el equipo.
- **Veredicto:** integración de solo-lectura vía Cookidoo como máximo. El "handoff" a otro equipo se
  dispara por paso de receta conocido + temporizador, no por señal del TM6.

### Breville Joule Oven Air Fryer Pro — 🔴 Sin API (hoy)
- Controlado por la app **Breville+**; sin API pública.
- Antecedente prometedor: el **Joule sous-vide original** (ChefSteps) fue reverseado con éxito
  (gRPC/Firebase), así que la casa tiene historial de protocolos abordables — pero para el horno
  aún no hay librería comunitaria fiable.
- **Plan B:** precalentado manual disparado por notificación del hub (push al móvil con deep-link a la app),
  o proyecto propio de sniffing del tráfico de Breville+.
- **Veredicto:** por ahora el hub puede *avisar* ("la Thermomix va por el paso 4 → precalienta el horno"),
  no ejecutar.

---

## 🏋️ Fitness / Salud

### Tonal — 🟡 API no oficial (solo lectura)
- Sin API pública. La comunidad reverseó su **API GraphQL** interna (lectura de entrenamientos,
  volumen, PRs). También exporta a **Apple Health**.
- **Veredicto:** buen "trigger" de solo lectura (entrenamiento completado, PR nuevo).

### Peloton — 🟡 API no oficial (madura)
- La API REST no oficial (`api.onepeloton.com`) está **muy documentada** por la comunidad y la usan
  decenas de proyectos: historial de clases, métricas (output, cadencia, HR), logros.
- **Veredicto:** integración de lectura sólida y estable en la práctica.

### Garmin (reloj) — 🔵 API partner / 🟡 no oficial
- **Vía oficial:** Garmin Connect Developer Program (**Health API**, **Activity API**, Training API) —
  requiere solicitud y aprobación como empresa/desarrollador.
- **Vía no oficial:** librería Python [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
  (login de usuario) — HR, sueño, body battery, actividades, y hasta **crear entrenamientos** en Connect.
- **Veredicto:** el mejor dispositivo del lote. Sirve de *trigger* (despertar, actividad sincronizada,
  HR alta) y de *destino* (consolidar entrenamientos de Tonal + Peloton en Connect).

### Alternativa transversal: agregadores de wearables
- **Terra API** / **Spike API**: agregan Garmin, Peloton, Fitbit, Oura, etc. bajo una sola API oficial
  (de pago). Evitan mantener N integraciones no oficiales para la parte fitness.

---

## 🏗️ Recomendación de arquitectura

```
┌──────────────────────────────────────────────────────┐
│         Device Hub SPA (devices/index.html)          │
│      catálogo + recetas trigger→acción + log         │
└──────────────────────┬───────────────────────────────┘
                       │ REST
┌──────────────────────▼───────────────────────────────┐
│        Hub API (devices/api/server.py, Flask)        │
│   motor de reglas + un ADAPTADOR por dispositivo     │
└───┬──────────┬───────────┬──────────┬────────────────┘
    ▼          ▼           ▼          ▼
 pylamarzocco  peloton   garmin    Home Assistant
 (café)        (no ofic.) connect  (enchufes, resto)
```

1. **Patrón adaptador**: cada dispositivo implementa la misma interfaz
   (`get_status`, `events`, `execute`). Los que no tienen API quedan como stubs honestos.
2. **Home Assistant como músculo local**: ya tiene integración oficial de La Marzocco y comunidad para
   Garmin/Peloton, y resuelve los enchufes inteligentes del plan B del grinder. El hub puede hablar con
   HA por su API REST/WebSocket en lugar de reimplementar cada driver.
3. **Empezar por el caso ganador**: "Café al despertar" (Garmin → La Marzocco) y "Grind by Sync"
   (La Marzocco → enchufe del grinder) son 100 % viables hoy. Los de cocina quedan como notificaciones
   hasta que exista una vía técnica.

## ⚠️ Riesgos
- Las APIs no oficiales pueden romperse con cualquier update del fabricante (cuentas, tokens, endpoints).
- Algunos fabricantes prohíben el acceso automatizado en sus ToS; usar cuentas propias y rate limits
  conservadores.
- Credenciales: siempre en variables de entorno del servidor (como ya hace `api/server.py` con Alpaca),
  nunca en el front estático.
