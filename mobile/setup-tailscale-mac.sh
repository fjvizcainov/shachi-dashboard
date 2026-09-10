#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Shachi Mobile Access — instalación en la Mac mini (una sola vez)
#
# Qué hace:
#   1. Instala Tailscale (WireGuard) con Homebrew si no está.
#   2. Une la Mac mini a tu tailnet (te abre el navegador para iniciar sesión).
#   3. Instala y arranca el gateway local (mobile/serve.py) como servicio
#      launchd, escuchando SOLO en 127.0.0.1:8787.
#   4. Publica el gateway con `tailscale serve` en HTTPS (certificado
#      automático *.ts.net). Solo dispositivos de TU tailnet pueden llegar.
#   5. Verifica que Funnel (exposición pública) esté APAGADO.
#
# Idempotente: puedes volver a correrlo sin romper nada.
# Lee docs/MOBILE-ACCESS.md antes de tocar cualquier parámetro.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_PORT="${SHACHI_MOBILE_PORT:-8787}"
PLIST_LABEL="com.shachi.mobile-gateway"
PLIST_SRC="$REPO_ROOT/mobile/$PLIST_LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_DIR="$HOME/Library/Logs/shachi"

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "Este script es para macOS (Mac mini). Para Linux ver docs/MOBILE-ACCESS.md."

# ── 1. Tailscale ─────────────────────────────────────────────────────────────
say "1/5 Tailscale"
if ! command -v tailscale >/dev/null 2>&1; then
  command -v brew >/dev/null 2>&1 || die "Homebrew no está instalado: https://brew.sh"
  brew install --cask tailscale
  warn "Abre la app Tailscale (Applications) una vez para que arranque el daemon, luego vuelve a correr este script."
  exit 0
fi
ok "tailscale $(tailscale version | head -1)"

# ── 2. Unirse a la tailnet ──────────────────────────────────────────────────
say "2/5 Conectando la Mac mini a tu tailnet"
if ! tailscale status >/dev/null 2>&1; then
  # --ssh=false: no habilitamos Tailscale SSH aquí; el acceso es solo web.
  # --accept-routes=false: no aceptamos rutas de otros nodos (mínimo privilegio).
  # --advertise-tags: etiqueta que usa la ACL (mobile/tailscale-acl.hujson) para
  #   permitir SOLO el puerto 443 hacia esta máquina.
  tailscale up --ssh=false --accept-routes=false --hostname="shachi-mac" \
               --advertise-tags=tag:shachi-server
fi
TS_FQDN="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
ok "Conectado como $TS_FQDN"

# ── 3. Gateway local como servicio launchd ───────────────────────────────────
say "3/5 Gateway local (127.0.0.1:$GATEWAY_PORT)"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
PYTHON_BIN="$(command -v python3)"
sed -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
    -e "s|__PYTHON__|$PYTHON_BIN|g" \
    -e "s|__PORT__|$GATEWAY_PORT|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DST"
launchctl unload "$PLIST_DST" >/dev/null 2>&1 || true
launchctl load -w "$PLIST_DST"
sleep 1
if curl -fsS "http://127.0.0.1:$GATEWAY_PORT/healthz" >/dev/null; then
  ok "Gateway respondiendo en loopback"
else
  die "El gateway no responde. Revisa $LOG_DIR/gateway.err"
fi

# ── 4. Publicar SOLO dentro de la tailnet (HTTPS) ────────────────────────────
say "4/5 tailscale serve (HTTPS, solo tailnet)"
# Requiere HTTPS/MagicDNS habilitado en https://login.tailscale.com/admin/dns
tailscale serve --bg --https=443 "http://127.0.0.1:$GATEWAY_PORT" >/dev/null
ok "Publicado en https://$TS_FQDN"

# ── 5. Verificación de seguridad ────────────────────────────────────────────
say "5/5 Verificación"
if tailscale funnel status 2>/dev/null | grep -qi "funnel on\|https://.*(Funnel on)"; then
  die "¡FUNNEL ESTÁ ENCENDIDO! Eso expone el dashboard a internet. Apágalo: tailscale funnel off"
fi
ok "Funnel apagado (nada expuesto a internet público)"
if lsof -nP -iTCP:"$GATEWAY_PORT" -sTCP:LISTEN 2>/dev/null | grep -q '\*:'"$GATEWAY_PORT"; then
  die "El gateway escucha en todas las interfaces. Debe ser solo 127.0.0.1."
fi
ok "Gateway ligado únicamente a 127.0.0.1"

cat <<MSG

──────────────────────────────────────────────────────────────
 Listo. En tu celular:
   1. Instala Tailscale (App Store / Play Store) e inicia sesión
      con LA MISMA cuenta que usaste aquí.
   2. Abre:  https://$TS_FQDN
   3. Safari/Chrome → "Agregar a pantalla de inicio" para tener
      el ícono como una app.

 Para verificar en cualquier momento:  mobile/check-access.sh
──────────────────────────────────────────────────────────────
MSG
