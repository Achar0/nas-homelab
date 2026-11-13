# HTTPS and passkey login (issue #6)

## Intent

Home, Mission Control and Netwatch share one admin login. Today it travels over plain HTTP, so the
password and session cookie cross the home network unencrypted. Browsers also only allow passkeys
(Face ID / Touch ID) on a secure origin. This change serves the three pages over HTTPS under the
NAS's Tailscale MagicDNS name, with a free Tailscale certificate, and adds passkey sign-in next to
the password.

The user usually types the local address (`192.168.1.14`) at home and does not keep Tailscale on.
So the HTTPS name must also work at home without Tailscale.

## Goals

- One address everywhere: `https://<nas-name>.<tailnet>.ts.net:<port>`. At home, AdGuard resolves it
  to `192.168.1.14`. Away from home, Tailscale MagicDNS resolves it to the NAS's tailnet address.
- Old bookmarks keep working: `http://192.168.1.14:3001` (and :8800, :8790) redirect to the HTTPS
  address.
- Passkey sign-in on Home's login page. You add, name and remove passkeys from Home's admin settings.
- The password keeps working (over HTTPS only) and is the recovery path if every passkey is lost.
- Certificates renew on their own.

## Non-goals

- Exposing anything to the internet. Access stays LAN + tailnet.
- HTTPS for the other apps (qBittorrent, AdGuard, Kuma, Dockge, …).
- Taking over ports 80/443. UGOS uses them; changing UGOS config is off limits.
- HTTPS for the TV and IPTV players. They stay on plain HTTP (see "Plain-HTTP exceptions").
- Replacing the password, multiple users, HSTS.

## Anti-goals

- Getting locked out. A bug or a lost phone must never leave the admin pages unreachable; the
  password over HTTPS always works.
- Committing the tailnet name. This repo is public: the name lives in `.env` on the NAS, and docs
  use `<nas-name>.<tailnet>.ts.net`.
- Breaking the TV idle page or the IPTV playlist on the TV.

## Constraints and facts found

- Ports 80 and 443 on the NAS are taken by UGOS (they redirect to :9999 / :9443).
- In the tailnet, HTTPS certificates are not enabled yet (`CertDomains` is null). **User step, once:**
  Tailscale admin console → DNS → enable MagicDNS (if off) and *HTTPS Certificates*.
- The Tailscale container runs `tailscaled` with its socket in `stacks/tailscale/run/`.
- AdGuard is the LAN DNS for every device (the router hands out `192.168.1.14`).
- Home, Mission Control and Netwatch are standard-library Python servers on host networking, ports
  3001 / 8800 / 8790, sharing `auth.py` (three identical copies, checked by `tests/test_auth.py`).
- Netwatch skips the login check for requests from loopback (`LOOPBACK`, `app.py:362`), because Home
  and Mission Control read it over `127.0.0.1`. A reverse proxy on the same host also connects from
  loopback, so this check must change or the proxy becomes a login bypass. Home's
  `/api/internal/layout` (read by Mission Control) has the same loopback check and the same fix.
- Issuing the certificate puts `<nas-name>.<tailnet>.ts.net` in the public Certificate Transparency
  logs. The user accepted this: the name only resolves inside the tailnet or through home DNS.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| **Picked** | **Caddy in front of the three servers.** Caddy gets and renews `*.ts.net` certificates from the tailscaled socket and proxies to the unchanged HTTP servers. | One more container. Old HTTP URLs can redirect, because HTTP and HTTPS are on different ports. |
| Rejected | TLS inside each Python server (`ssl`), cert files from a daily `tailscale cert` job | Stays stdlib, no new container. But one port can't speak both protocols, so old `http://…:3001` bookmarks would fail instead of redirecting. It also needs extra HTTP ports for the TV and certificate reloads in three servers. |
| Rejected | `tailscale serve` | Only answers on the Tailscale interface, so it doesn't work at home without Tailscale. |

| | Passkey signature check | Trade-off |
|---|---|---|
| **Picked** | **`cryptography`, in Home only.** Only Home handles login; Mission Control and Netwatch only check the cookie and stay stdlib. | Home's image gets one pip dependency. |
| Rejected | Pure-Python P-256 verification | Stays stdlib, but hand-written crypto checks are where a small bug lets a forged signature through. |

## Design

### Addresses

| Page | HTTPS (new) | Old HTTP |
|---|---|---|
| Home | `https://<name>:3443` | `http://192.168.1.14:3001` → redirect |
| Mission Control | `https://<name>:8843` | `http://192.168.1.14:8800` → redirect |
| Netwatch | `https://<name>:8793` | `http://192.168.1.14:8790` → redirect |

`<name>` is the full MagicDNS name. These ports are free on the NAS today. The builder may pick others
if they collide, and must update the README services table either way.

### Caddy stack (`stacks/caddy/`)

- Official `caddy:2` image pinned to a specific version, `network_mode: host`, `restart: unless-stopped`.
- Mounts `../tailscale/run:/var/run/tailscale`, so Caddy's built-in Tailscale integration fetches
  and renews the certificate for the `.ts.net` name. Mounts `./data` for Caddy's own state (not in git).
- `.env` (not in git, `.env.example` committed) holds `NAS_TS_NAME`. The Caddyfile reads it as
  `{$NAS_TS_NAME}`.
- `auto_https disable_redirects`, because Caddy must not try to bind :80.
- Three site blocks (`{$NAS_TS_NAME}:3443`, `:8843`, `:8793`) reverse-proxy to `127.0.0.1:3001`,
  `:8800`, `:8790`. Caddy sets `X-Forwarded-Proto: https` and `X-Forwarded-For`, overwriting any
  values the client sent.
- Add an Uptime Kuma monitor for `https://<name>:3443` (with ntfy), since Caddy being down makes the
  admin pages unreachable through their normal address.

### "Did this come through Caddy?" (shared `auth.py`)

New helper `via_proxy(handler)`: true when `client_address` is loopback **and**
`X-Forwarded-Proto == "https"`. A client on the network can't appear as loopback, so it can't fake
this. There are three kinds of request:

1. **Through Caddy** (`via_proxy`): normal HTTPS handling, login required as today.
2. **Loopback without the header**: the services reading each other (Home ↔ Mission Control ↔
   Netwatch). Served as today. Netwatch's loopback exemption now applies **only** to this case, never
   to requests that came through Caddy.
3. **From the network over plain HTTP**: `301` to the same path and query on the HTTPS address
   (`https://{NAS_TS_NAME}:{https port}`), except the plain-HTTP exceptions below. POSTs and `/api/`
   calls get a `403` JSON error ("use the HTTPS address") instead of a redirect, so a password is
   never accepted over HTTP.

Each service gets `NAS_TS_NAME` and its own HTTPS port from its `.env` / compose environment. If
`NAS_TS_NAME` is unset, it logs a warning at start-up and keeps today's HTTP behaviour (no
redirects). This allows a step-by-step rollout and avoids a lockout if the env is missing.

### Plain-HTTP exceptions (Home)

These stay reachable over plain HTTP from the network, unchanged: `/tv`, `/tv/…` (the page and its
static files), `/api/public/tv` and `/iptv.m3u`. The builder checks what the TV page loads and adds
those paths too; nothing that needs login may be on the list.

### Login changes (`auth.py`, all three copies)

- The cookie gets `Secure`. A cookie set on the `.ts.net` name is shared by all three HTTPS ports
  (cookies ignore ports), as today on the IP.
- `require_login` redirects to `https://{NAS_TS_NAME}:3443/?login=1&next=…` when `NAS_TS_NAME` is set.
- `safe_next` accepts `https` URLs on the `.ts.net` name with the three HTTPS ports. It keeps today's
  HTTP rule only while `NAS_TS_NAME` is unset.

### Passkeys (Home only)

- **Storage:** `admin-auth/passkeys.json`, written atomically with mode 600 the same way as
  `auth.json`, and only by Home. Each entry: credential id, public key (COSE, as stored),
  algorithm, sign count, user-given name, created and last-used dates. A separate file, so that
  `auth.save()` (password change, log out everywhere) never touches passkeys.
- **Relying party:** RP ID = `NAS_TS_NAME`. Allowed origin = `https://{NAS_TS_NAME}:3443`.
  Passkey endpoints only answer through Caddy (`via_proxy`) and only if `NAS_TS_NAME` is set.
- **Register** (logged in, admin settings): "Add passkey" asks for a name ("iPhone", "MacBook").
  Discoverable credential (`residentKey: required`), `userVerification: required`, attestation
  `none`, algorithms ES256 and RS256. The server checks the challenge, origin, type, RP ID hash and
  UP + UV flags, then stores the key. The attestation object needs a small CBOR reader (maps, byte
  and text strings, ints). Its input only comes from a logged-in admin.
- **Manage:** a list with name, created date and last used date, plus a "Remove" button per passkey.
  It sits next to the password settings.
- **Sign in:** the login page shows "Sign in with passkey" above the password field, with no
  username. It also uses conditional mediation (autofill) where the browser supports it. The server
  checks: the challenge (single use, kept in memory, 2 minutes), the origin, the RP ID hash, the UP +
  UV flags, the signature with `cryptography`, and that the credential id is known. If the sign
  count is non-zero, it must increase; Apple passkeys always send 0, which is accepted. On success
  it issues the same cookie as the password login. The "remember this device" checkbox applies to
  both.
- Failed passkey attempts count against the same `Throttle` as wrong passwords.
- The password, password change and "log out everywhere" all keep working. Logging out everywhere
  ends sessions but keeps the passkeys.
- `Dockerfile`: `pip install --no-cache-dir cryptography==<pinned>`. The comment "Standard library
  only" changes accordingly.

### DNS (AdGuard, user-visible step)

In AdGuard, add a DNS rewrite: `<nas-name>.<tailnet>.ts.net` → `192.168.1.14`. Do it through the
AdGuard UI or API on the NAS; its `conf/` is not in git. The README describes it with the
placeholder name. Devices with Tailscale on use MagicDNS instead, which also works.

**Known risk:** a device that bypasses AdGuard (browser "secure DNS", iCloud Private Relay) won't
resolve the name at home. The README notes this. The fix is on the device (turn off secure DNS for
the home network) or turning Tailscale on.

### Rollout order (keeps everything reachable at each step)

The old code trusted every loopback request, so putting Caddy in front of it would expose Netwatch
without a login. The new code therefore goes first, with HTTPS mode still off.

1. User enables HTTPS certificates in the Tailscale console.
2. Deploy the new Home / Mission Control / Netwatch code with `NAS_TS_NAME` empty (loopback narrowing
   already active, behaviour otherwise unchanged).
3. Deploy Caddy. Check `https://<name>:8793` gives a 302 to the login and `/api/internal/layout` on
   :3443 gives 401.
4. Add the AdGuard rewrite and check from the LAN without Tailscale.
5. Set `NAS_TS_NAME` in the three `.env` files and recreate (redirects on), then passkeys.
6. User adds passkeys on iPhone and Mac and tests sign-in from home and away.

### Tests

- `via_proxy` and the three-way rule, including "loopback with an `X-Forwarded-Proto` header is not
  exempt in Netwatch".
- Redirect targets (path + query kept), the HTTP exception list, 403 for POST / API over HTTP, and
  behaviour when `NAS_TS_NAME` is unset.
- `safe_next` with HTTPS URLs; the `Secure` cookie.
- WebAuthn: build authenticator data and client data in the test, sign with a key generated by
  `cryptography`, then check acceptance and each rejection (wrong origin, RP ID, flags, challenge
  reuse or expiry, bad signature, unknown credential, sign count going backwards).
- The `auth.py` copies stay identical (existing test).

### Docs

README: services table (new ports, Caddy), network diagram, a new "HTTPS and passkeys" section with
the user steps, the Security table row "Admin login" (drop the plain-HTTP warning, describe the
loopback rule), known issues (secure DNS), changelog. Close #6 from the PR.

## Left to the builder

- The exact Caddy and `cryptography` versions, the Caddyfile layout, and the file and function names.
- The login and settings UI details. It follows the existing Home style (calm HIG, no nested boxes).
- Whether passkey code lives in a new `passkeys.py` module (suggested) or in `auth.py`. It must not
  go into the shared `auth.py` copies, because Mission Control and Netwatch don't need it.
