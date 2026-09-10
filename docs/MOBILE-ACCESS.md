# Acceso móvil seguro al dashboard Shachi

> **Objetivo:** ver el dashboard de trading desde el celular sin que el sistema
> deje de correr localmente en la Mac mini y sin exponer absolutamente nada a
> internet. Toda la comunicación viaja por un túnel WireGuard cifrado de
> extremo a extremo entre tus dispositivos.

---

## 1. Diagnóstico del estado actual

Hoy el flujo es:

```
Mac mini (trading server :5002) ──sync.py cada 60 s──▶ GitHub (repo público)
                                                              │
                                                              ▼
                                            GitHub Pages / Cloudflare Pages
                                            (index.html + data/*.json)
```

Problemas de seguridad que esto tiene, y que el diseño de abajo resuelve:

| # | Problema | Riesgo |
|---|----------|--------|
| 1 | `login.html` valida usuario y contraseña **en JavaScript** con un hash SHA-256 embebido y guarda la sesión en `sessionStorage`. | Cualquiera puede abrir `data/*.json` directamente, o borrar la redirección. No es autenticación real. |
| 2 | El repo es público y `sync.py` sube `data/`, `trade_history.json`, equity, órdenes… | Tu P&L y posiciones son públicos para siempre en el historial de git. |
| 3 | `api/server.py` en Render usa `CORS(origins="*")`. | Cualquier sitio puede consultar tu API. |

La nota en `_redirects` menciona Cloudflare Access; si está activo mitiga el
punto 1 en el hosting de Cloudflare, pero no en GitHub Pages ni en el repo.

---

## 2. Diseño elegido: Tailscale (WireGuard) + `tailscale serve`

```
        ┌──────────────── tu tailnet (WireGuard, E2E cifrado) ────────────────┐
        │                                                                     │
  📱 Celular                                                         🖥 Mac mini
  Tailscale app ═══════════ túnel WireGuard ═══════════▶  tailscale serve :443 (TLS)
  https://shachi-mac.<tailnet>.ts.net                          │
                                                                ▼
                                                     mobile/serve.py  127.0.0.1:8787
                                                       │  estáticos: index, login, data/
                                                       │  proxy GET /api/*  ─────────▶ trading server 127.0.0.1:5002
                                                       │
                                                       ✘ nada escucha en 0.0.0.0
                                                       ✘ ningún puerto abierto en el router
                                                       ✘ Funnel (público) apagado
```

### Por qué esta opción

| Criterio | Tailscale + serve | WireGuard manual | Cloudflare Tunnel + Access | Port-forward + password |
|---|---|---|---|---|
| Cifrado extremo a extremo | ✅ WireGuard | ✅ WireGuard | ⚠️ TLS termina en Cloudflare (ellos ven el tráfico) | ⚠️ depende de ti |
| Abrir puertos en el router | No | Sí (UDP) o NAT tricks | No | Sí |
| Identidad del dispositivo | ✅ por llave + cuenta (Google/Apple/GitHub) | ✅ por llave | ✅ por cuenta | ❌ |
| Certificado HTTPS automático | ✅ `*.ts.net` | ❌ manual | ✅ | ❌ |
| Datos salen de tu casa a un tercero | No (solo coordinación de llaves) | No | Sí | No |
| Esfuerzo | ~10 min | ~1 h | ~30 min | 5 min (y peligroso) |

**Elegimos Tailscale** porque cumple "100 % local" (los datos nunca pasan por
un servidor ajeno; los servidores de Tailscale solo intercambian llaves
públicas), no requiere abrir nada al exterior y la identidad la da el
dispositivo, no una contraseña que se pueda adivinar.

### Capas de defensa (en orden)

1. **Red:** solo dispositivos de tu tailnet pueden enrutar paquetes a la Mac
   mini. Un atacante en internet ni siquiera ve un puerto abierto.
2. **ACL de Tailscale** (`mobile/tailscale-acl.hujson`): de todo lo que tu
   tailnet podría hacer, solo se permite `→ Mac mini :443`. Nada de SSH, nada
   de `:5002` directo.
3. **TLS** (`tailscale serve`): certificado válido emitido por Let's Encrypt
   para `shachi-mac.<tailnet>.ts.net`, sin advertencias en el celular.
4. **Gateway** (`mobile/serve.py`): escucha solo en `127.0.0.1`, sirve
   únicamente `index.html`, `login.html`, `data/` y hace proxy **solo GET** a
   `/api/*`. Cualquier otra ruta del repo (`MEMORY.md`, `bitcoin/`, `.git/`)
   responde 404. Métodos de escritura → 405.
5. **Aplicación:** el login en JS se mantiene como fricción visual, no como
   seguridad. La seguridad real está en las capas 1–4.

---

## 3. Instalación

### 3.1 En la Mac mini (una sola vez)

```bash
cd ~/shachi-dashboard          # o donde tengas el repo
mobile/setup-tailscale-mac.sh
```

El script:

1. Instala Tailscale con Homebrew si falta (te pedirá abrir la app una vez).
2. Ejecuta `tailscale up` con SSH deshabilitado y la etiqueta
   `tag:shachi-server`. Se abre el navegador para que inicies sesión.
3. Instala `mobile/serve.py` como LaunchAgent (`com.shachi.mobile-gateway`)
   para que arranque solo al iniciar sesión y se reinicie si muere.
4. Publica el gateway con `tailscale serve --https=443`.
5. Comprueba que Funnel esté apagado y que nada escuche en `0.0.0.0`.

Al terminar imprime la URL, del estilo `https://shachi-mac.tail1234.ts.net`.

> **Requisito previo:** en <https://login.tailscale.com/admin/dns> activa
> **MagicDNS** y **HTTPS Certificates**. Sin eso `tailscale serve` no puede
> emitir el certificado.

### 3.2 ACL (recomendado, 2 minutos)

1. Abre <https://login.tailscale.com/admin/acls>.
2. Pega el contenido de `mobile/tailscale-acl.hujson`.
3. Guarda. A partir de ahí solo `:443` de la Mac mini es alcanzable.

### 3.3 En el celular

1. Instala **Tailscale** desde App Store / Play Store.
2. Inicia sesión con **la misma cuenta** que usaste en la Mac mini.
3. Abre la URL que te dio el script. Aparece el login de Shachi.
4. Safari → Compartir → **Agregar a pantalla de inicio**. El dashboard ya
   incluye `manifest.webmanifest`, así que se abre a pantalla completa como
   una app.

Cuando el celular está fuera de casa (4G/5G) el túnel sigue funcionando: WireGuard
atraviesa NAT sin abrir puertos. Si el celular no tiene Tailscale encendido, la
URL simplemente no resuelve.

### 3.4 Verificar

```bash
mobile/check-access.sh
```

Revisa túnel, `serve`, Funnel apagado, bind en loopback del gateway y del
servidor de trading, y que los archivos privados respondan 404.

---

## 4. Cosas que **no** hay que hacer

- **No** ejecutar `tailscale funnel`. Eso publica el dashboard en internet.
  El script y `check-access.sh` fallan si lo detectan.
- **No** cambiar `serve.py` a `0.0.0.0`. Entonces cualquier dispositivo de tu
  Wi-Fi vería el dashboard sin pasar por Tailscale.
- **No** abrir el puerto 5002 ni 8787 en el router.
- **No** compartir la Mac mini con "Tailscale node sharing" a cuentas ajenas.

---

## 5. Recomendaciones adicionales (fuera del alcance de este cambio)

1. **Dejar de publicar snapshots en el repo público.** Con el túnel ya no hace
   falta GitHub Pages. Opciones: hacer el repo privado, o correr `sync.py`
   solo para escribir `data/` local sin `git push`. El historial de git ya
   contiene P&L; si quieres borrarlo hace falta reescribir historia.
2. **Servidor de trading en loopback.** Si el proceso de `:5002` usa
   `host='0.0.0.0'` (como `api/server.py`), cámbialo a `127.0.0.1`.
   `check-access.sh` te avisa.
3. **Bloqueo por dispositivo.** En Tailscale Admin → Machines puedes exigir
   re-autenticación cada 30–90 días (Key expiry) y ver qué dispositivos están
   dentro. Si pierdes el celular: un clic en "Remove" y deja de tener acceso.
4. **Biometría.** Activa Face ID / huella para abrir la app Tailscale
   (Ajustes de la app) y así un celular desbloqueado no basta.

---

## 6. Alternativas si Tailscale no te convence

- **WireGuard puro (`wg-quick`)**: mismo cifrado, cero terceros, pero tienes
  que abrir un puerto UDP en el router, gestionar llaves a mano y no hay TLS
  automático. Vale la pena solo si no quieres depender del plano de control
  de Tailscale. Headscale (control server auto-hospedado) es el punto medio.
- **Cloudflare Tunnel + Access**: cómodo y sin puertos, pero Cloudflare
  descifra el tráfico. Tiene sentido si quieres compartir el dashboard con más
  gente vía correo/SSO; para uso personal es más superficie de la necesaria.

---

## 7. Archivos de este cambio

| Archivo | Rol |
|---|---|
| `mobile/serve.py` | Gateway loopback-only: estáticos + proxy GET `/api/*` |
| `mobile/setup-tailscale-mac.sh` | Instalación idempotente en la Mac mini |
| `mobile/com.shachi.mobile-gateway.plist` | LaunchAgent para mantener el gateway vivo |
| `mobile/tailscale-acl.hujson` | Política mínimo-privilegio para la tailnet |
| `mobile/check-access.sh` | Verificación de seguridad en un comando |
| `manifest.webmanifest` | Permite instalar el dashboard como app en el celular |
