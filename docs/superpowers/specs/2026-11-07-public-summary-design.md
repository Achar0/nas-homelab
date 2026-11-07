# Public summary page and admin login

Covers GitHub issue #1 and the core of #2. Settings (#3) and HTTPS/passkeys (#6) stay separate.

## Why

The NAS landing page on `:3001` shows the owner's dashboard to anyone on the network: dock, alerts, connection details, and buttons that change state. Family and guests only need the core information, and they must not be able to get into the owner's page. Hiding links is not enough: the pages and their data calls have to refuse anyone who isn't logged in.

## Goals

- Everyone at `:3001` gets a calm, plain-language summary: is everything OK, news, downloads.
- Family can reach their own UGOS space from that page, using their own UGOS account.
- The owner's page moves to `:3001/admin`, behind one admin password.
- Logging in once at `:3001` also opens Mission Control (`:8800`) and Netwatch (`:8790`). Without a login, those two give no pages and no data.

## Non-goals

- Settings (#3), HTTPS or Face ID (#6), and per-person accounts on the guest page.
- Putting third-party apps behind this login. They stay on their own ports with their own logins. Glances is the one change here: it has no login today, so it gets its own password (see "What is locked").
- Making the ports invisible. `:8800` and `:8790` still answer on the network, they just refuse without a login.

## Anti-goals (a failure even if it works)

- A guest gets admin data by calling an API directly, even though the page looks locked.
- Technical or security details reach guests: IP addresses, intrusion alerts, container names, raw torrent names.
- The guest page says "All services are online" when it could not actually check.
- A missing or broken auth setting leaves anything open.
- Any password, hash or secret ends up in this public repo.

## Guest page (`:3001`)

Based on screen 1 of `docs/mockups/public-admin.html`, which the owner approved, with two additions: the UGOS button and downloads in progress. Update that mockup to match. Same Apple-style look as Home. Check with `scripts/shoot.sh` at 1920×1080, 1800×1125 and 400 px.

**Top to bottom:**

1. **Header:** greeting and date on the left. On the right, a prominent **Open UGOS** button with the UGOS logo, and a quiet **Admin** button.
2. **Status row:** one status card, then *Internet* (speed) and *Free storage*.
3. **News:** the existing two-card carousel with topic tabs (All, Tech, Markets, Discoveries) and arrows/swipe. No *Opened* tab. Opening a story from this page records nothing.
4. **Downloads:** what has arrived, and what is downloading with progress and time left. Recognised episodes (those matching the show/episode patterns in `arrivals.py`) appear by name. Everything else is only counted, as "1 other download", with no name (owner's decision). The admin page keeps the full list.

**Not on this page:** dock, rail, alert cards, takeover, connection details, anything that changes state.

**UGOS button:** a link to `https://<address the page was opened with>:9443`, in a new tab. The icon is the favicon served by the NAS at `https://192.168.1.14:9443/desktop/favicon.ico` (32×32), saved as `stacks/home/static/icons/ugos.png`. UGOS uses a self-signed certificate, so browsers show a warning until #6. Limiting what family can do is UGOS's job: their accounts should be non-admin.

### Status card

Text is plain language, never technical. The owner chose one summary line over a list of services.

| Situation | Line |
|---|---|
| All checks read successfully, nothing wrong | **Everything's running** / All services are online |
| A monitored service is down | **\<Plain name\> is down** |
| RAID degraded, drive failing or running hot, or space low | **Storage needs attention** |
| A container keeps restarting | **Something isn't working right now** (no container names) *(my call)* |
| Latest speed test well below normal | **Internet is slow right now** |
| Several of these at once | The most serious line, then "and N more" |
| A source could not be read | **Status unavailable** (never "all online") |

- Netwatch and intrusion conditions never affect this card. *(My call, so guests never see security events.)*
- Uptime Kuma, Prometheus and the docker proxy are all required sources: if any can't be read, the card says **Status unavailable**. *(My call, because Kuma alone may miss a crash-looping container.)* The "Episode not downloaded" rule is ignored, as it never fires today.
- The card reflects live conditions, so an alert the owner has dismissed still counts while the problem lasts. *(My call.)*

## Login

- **Sheet:** tapping Admin opens the password sheet over the guest page (screen 2 of the mockup): password, "Remember this device for 30 days", Log in.
- **Already logged in:** opening `:3001` goes straight to `/admin`, following the issue's "everyone except the admin". *(My call.)*
- **Log out:** a small link on the admin page, which clears the cookie. *(My call: #3's "log out everywhere" stays there, and changing the secret below does the same today.)*
- **Coming from `:8800` or `:8790`:** without a login, a page request redirects to the login at `:3001` on the same hostname, and returns to where it came from afterwards. Only return addresses on the same hostname and on ports 3001, 8800 or 8790 are accepted, so the redirect can't be abused.

### How the login works

Standard library only, as in the rest of these stacks.

- **One shared settings file on the NAS:** `/volume1/docker/admin-auth.env`, holding `ADMIN_PASSWORD_HASH` and `SESSION_SECRET`. Each of the three services loads it with `env_file`. It's separate from the stacks' `.env` files because `mc-web` must not receive the collector's service logins. It must not be committed: check `.gitignore` and `scripts/sync-from-nas.sh`.
- **Password hash:** scrypt (`hashlib`). A small script in `scripts/` asks for the password and prints the hash. The owner runs it and fills in the file, so the password never appears in chat, logs or git.
- **Session cookie:** a signed token holding an expiry time (HMAC with `SESSION_SECRET`, compared in constant time). Each service checks it without keeping sessions, so no shared database is needed. `HttpOnly`, `SameSite=Strict`, `Path=/`. No `Secure` flag, since this is plain HTTP until #6.
- **Lifetime:** 30 days with "remember" ticked. Otherwise a browser-session cookie whose token expires after 12 hours. *(My call.)* Changing `SESSION_SECRET` logs everyone out.
- **Wrong passwords:** after 5 failures from one address, wait 30 seconds, doubling up to 15 minutes. Kept in memory. *(My call.)*
- **Hostnames:** cookies are per hostname, not per port, so one login covers all three ports. `192.168.1.14` and the Tailscale name each need their own login. Don't set a `Domain`.
- **Fail closed:** if the hash or secret is missing or invalid, every login is refused and locked routes stay locked, and the service logs why. The guest page keeps working.
- **Shared code:** the three stacks have separate build contexts. How they share the small check (for example one `auth.py` copied into each, with a test that the copies match) is left to the builder.

## What is locked

For anyone not logged in: page requests redirect to login, and `/api/*` requests get 401.

**Home (`:3001`):**

| Route | Guest | Admin |
|---|---|---|
| `/`, guest page files, shared icons and carousel | yes | redirected to `/admin` for `/` |
| New guest summary endpoint (status, speed, free storage) | yes | yes |
| `GET /api/news` for real topics | yes, without feed error details | yes |
| `GET /api/news?topic=opened` | no | yes |
| `GET /api/arrivals` (full list) | no | yes |
| Guest downloads data (recognised episodes, plus a count of the rest) | yes | yes |
| `/admin` and its page files | no | yes |
| `GET /api/attention`, including `?demo=` | no | yes |
| `/api/prom/*` | no | yes |
| `POST /api/attention/*`, `POST /api/news/*/open` | no | yes |

The guest summary reads speed and storage on the server using fixed queries. It never passes a query through from the browser.

**Rule for Home's static files:** the current page's files must not be reachable from the public path. Move them under `/admin`, so guests can't simply open the old `index.html` or `app.js`.

**Mission Control (`:8800`):** every path, including static files, `/vendor/`, `/api/prom/*` and `/api/netwatch`.

**Netwatch (`:8790`):** every path, including `/vendor/` and `/api/state`. **Exception:** requests from `127.0.0.1` skip the check, because Home and `mc-web` read `/api/state` over loopback. No reverse proxy runs in front, so the source address can be trusted. Verify nothing else depends on this port from elsewhere (Uptime Kuma monitors, the old Homepage config).

**Glances (`:61208`):** today it has no login and serves the full process list to anyone on the network. Turn on Glances' own password (owner's decision), so its dock link keeps working behind its own login. It's a third-party app, so it doesn't use the shared login, and the password stays out of git. First check that nothing still running reads its API; the README says it feeds the dashboard, and the old Homepage is the known reader.

## Deployment

- Follow `CLAUDE.md`: edit `stacks/`, copy to the NAS, apply, run `scripts/sync-from-nas.sh`, commit.
- Update `README.md`: services table, security section, changelog, and Home's description.
- Update Uptime Kuma monitors if the redirects or 401s make them report a service as down.
- Ntfy pushes and the attention loop carry on as they are.

## How to know it works

- Automated tests in each stack's existing `tests/` for: token signing and expiry, tampering, fail-closed, return-address checks, wrong-password delay, and the route table above.
- From a logged-out browser or `curl` against the NAS: every locked route refuses, including Glances' API, and the guest endpoints contain no IP addresses, alert text or raw torrent names. Test the downloads filter with a made-up release name such as `Some.Movie.2024.1080p.x265-GRP`, which must only be counted.
- Logged in at `:3001`: `/admin`, `:8800` and `:8790` open without asking again, and all their live data still loads (including the globe and alert actions).
- Home's alerts still receive Netwatch data, and Mission Control's globe still works, after Netwatch is locked.
- The guest status card shows each row of the table above (use a demo mode that is never stored or pushed).

## Left to the builder

File layout and names, the endpoint's name and shape, how code is shared between stacks, the plain-name mapping for services, and how the "and N more" line reads.
