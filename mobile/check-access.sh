#!/usr/bin/env bash
# Verificación rápida del acceso móvil (correr en la Mac mini).
# Sale con código 1 si detecta algo inseguro.
set -uo pipefail
PORT="${SHACHI_MOBILE_PORT:-8787}"
fail=0
ok()   { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✘\033[0m %s\n' "$*"; fail=1; }

echo "Shachi — verificación de acceso móvil"

# 1. Tailscale conectado
if tailscale status >/dev/null 2>&1; then
  ok "Tailscale conectado: $(tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
else
  bad "Tailscale no está conectado (tailscale up)"
fi

# 2. serve activo y apuntando al gateway
if tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$PORT"; then
  ok "tailscale serve → http://127.0.0.1:$PORT"
else
  bad "tailscale serve no está publicando el gateway"
fi

# 3. Funnel apagado (nada público)
if tailscale funnel status 2>/dev/null | grep -qi "funnel on"; then
  bad "FUNNEL ENCENDIDO — el dashboard está expuesto a internet. Ejecuta: tailscale funnel off"
else
  ok "Funnel apagado"
fi

# 4. Gateway vivo y solo en loopback
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  ok "Gateway responde en 127.0.0.1:$PORT"
else
  bad "Gateway no responde (launchctl list | grep shachi)"
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q '\*:'"$PORT"; then
  bad "Gateway escucha en 0.0.0.0 — debe ser solo 127.0.0.1"
else
  ok "Gateway NO es alcanzable desde la LAN"
fi

# 5. El servidor de trading (5002) tampoco debe estar en 0.0.0.0
if lsof -nP -iTCP:5002 -sTCP:LISTEN 2>/dev/null | grep -q '\*:5002'; then
  bad "El servidor de trading (5002) escucha en todas las interfaces. Cámbialo a host='127.0.0.1'"
else
  ok "Servidor de trading (5002) no expuesto a la LAN"
fi

# 6. Rutas privadas ocultas
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/MEMORY.md")
[[ "$code" == "404" ]] && ok "Archivos privados del repo ocultos (404)" || bad "MEMORY.md accesible vía gateway ($code)"

echo
[[ $fail -eq 0 ]] && echo "TODO OK ✅" || { echo "HAY PROBLEMAS ❌"; exit 1; }
