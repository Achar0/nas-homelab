# Admin Settings and container names

Covers GitHub issue #3, plus two owner requests made while designing it: new services appear in Settings automatically, and containers are renamed to `name-port`.

Items marked *(my call)* were not decided by the owner. Everything else was.

## Why

Changing a preference today means editing a file over SSH (for example `stacks/home/feeds.json`) or changing code (the alert thresholds in `attention.py`, the docks in two JS files). The owner wants to do this from a page, and wants a new service on the NAS to show up there without being told about it.

## Goals

- A Settings page behind the admin login with five sections: News feeds, Alert rules, Services & dock, Apps, Account.
- A container that appears on the NAS shows up in Settings by itself.
- Containers carry their port in their name, so `docker ps` and Dockge read `autobangumi-7892`.

## Non-goals

- Re-implementing any app's own settings. Apps only links to them.
- Adding Mission Control cards for new services. A card needs code specific to that app.
- Renaming containers from the page, or renaming new containers automatically. Home keeps its read-only view of Docker.
- Per-person accounts, HTTPS, passkeys (#6).

## Anti-goals (a failure even if it works)

- A broken or missing settings file silences alerts or wipes the owner's choices.
- A Docker read failure marks every service "not running" or treats them all as new.
- A background helper appears on the dock without the owner switching it on.
- A logged-out request reads or changes any setting, directly or through Mission Control or Netwatch.
- The password, its hash, the session secret or the owner's settings file reach this public repo.
- The owner is locked out with no way back in.

## Order of work

The two parts ship as separate pull requests, renames first, so the first scan in Settings already sees the new names.

## Part 1: rename containers

Change `container_name` in each stack, using the format `name-port`, and recreate.

| Now | New |
|---|---|
| `home` | `home-3001` |
| `netwatch` | `netwatch-8790` |
| `dockge` | `dockge-5001` |
| `adguardhome` | `adguardhome-8080` |
| `autobangumi` | `autobangumi-7892` |
| `speedtest-tracker` | `speedtest-tracker-8765` |
| `uptime-kuma` | `uptime-kuma-3002` |
| `glances` | `glances-61208` |
| `mc-web` | `mc-web-8800` |
| `mc-prometheus` | `mc-prometheus-9090` |
| `mc-collector` | `mc-collector-9101` |
| `mc-node-exporter` | `mc-node-exporter-9100` |
| `mc-smartctl-exporter` | `mc-smartctl-exporter-9633` |
| `dockerproxy` | `dockerproxy-2375` |
| `minecraft_server` | `minecraft_server-25565` (not running; applies next time it starts) |

**Unchanged:** `tailscale` (no port), `qbittorrent-app-1` and `firefox-app-1` (managed by UGOS in its system app folder; the owner agreed to leave them), and the retired `homepage`.

**AdGuard uses web port 8080**, the one in the README, not its DNS port. *(my call)*

**What depends on the names:**

- `stacks/mission-control/web/static/metrics.js` queries `mc_container_*{name="…"}` for the AdGuard and Speedtest cards. Update both. Their CPU and memory graphs start fresh; the owner has been told. The old series stays in Prometheus.
- Uptime Kuma: already checked, all five monitors are `http`, so none depends on a container name.
- Search the README and scripts for the old names and update them. Test fixtures can keep the old names: they are only sample data.

**Applying:** recreating AdGuard interrupts DNS for the whole house for a few seconds. Do it last, and say so before doing it.

## Part 2: Settings

### Page

- `:3001/admin/settings`, linked from the header of the admin page. Locked by the existing admin-file rule, and every new API needs the login.
- Same style as Home, two panes as in screen 3 of `docs/mockups/public-admin.html`. `docs/mockups/settings-prototype.html` is the prototype the owner clicked through and approved in outline.
- Phones: the section list becomes a row across the top. Reordering must work by touch and keyboard, not only by mouse drag. *(my call)*
- Check with `scripts/shoot.sh` at 1920×1080, 1800×1125 and 400 px.
- Every change saves as soon as it's made, with no Save button. Password change is the exception. *(my call)*
- **File location:** `scripts/sync-from-nas.sh` only copies files up to three levels deep, so `home/static/admin/settings/index.html` would be missed. Keep the files directly in `static/admin/` or widen the script.

### Where settings live

- `DATA_DIR/settings.json` in Home's data folder, written atomically under a lock. It is never committed. *(my call)*
- Built-in defaults equal today's behaviour, so nothing changes until the owner changes it. The first run imports `feeds.json`, which stays in the repo as the starting list only.
- **If the file is unreadable or invalid:** keep it (rename it aside, don't overwrite it), run on the defaults, log it, and show a notice on the Settings page. Alerts keep working. *(my call)*
- Values are validated on the server, whatever the page sends.

### News feeds

- List with on/off switch, name, topic and language, plus Remove with a confirmation step.
- **Add:** URL + topic (Tech, Markets, Discoveries) + language (EN, IT).
  - Only `http` and `https`; duplicates refused.
  - The NAS test-fetches it using the existing size and time limits. If it doesn't parse as a feed, show a plain error and don't add it. Never echo the fetched content back. *(my call)*
  - The name comes from the feed's own title. *(my call)*
- A feed that is off is hidden from both Home and the guest page.
- Changes refresh the news straight away rather than at the next 15-minute cycle. The news archive is not touched. *(my call)*

### Alert rules

| Setting | Default (today) | Allowed *(my call)* |
|---|---|---|
| Free space low, below | 15% | 5–50% |
| Service down, urgent after | 2 min | 1–60 min |
| Possible intrusion, urgent after | 3 min | 1–60 min |
| Drive running hot, above | 50 °C | 40–70 °C |
| Slow internet, below this share of usual speed | 50% | 10–90% |
| Phone notifications | on | on/off |

- `attention.py` stays pure: thresholds are passed in. The guest status card goes through the same rules, so it follows the same numbers.
- **Phone notifications:** three things send to the same ntfy topic: Home, Netwatch and Uptime Kuma. The switch controls Home and Netwatch. Uptime Kuma has its own notification settings, so the row says so and links to it. *(my call)*
- When the switch is off, alerts and the takeover still appear on Home, the takeover's "A notification was sent to your phone" line is hidden, and problems that started while it was off are not sent later when it's switched back on. *(my call)*

### Services & dock

Three lists, each with show/hide and reorder:

- **Dock**, one list shared by Home and Mission Control. Each page leaves out its own entry, as the two docks do today. Starts with today's apps in today's order; Firefox is added, switched off. *(my call)*
- **Home rail:** CPU, Memory, Temperature, Free space; then qBittorrent, AdGuard, Speedtest. Reordered within those two groups, since the layout has both. *(my call)*
- **Mission Control cards:** qBittorrent, AdGuard, Speedtest, Tailscale, Connections.

**Row text:** the friendly name, with the container name beneath it (`autobangumi-7892`). For the two UGOS apps, whose names can't carry a port, the description shows the port instead: `:8888` for qBittorrent, `:5888` for Firefox (owner's request).

**Links** are stored as port and scheme, never a hostname, so they keep working from both the LAN address and Tailscale, as they do today.

**Mission Control reads this through its own server,** which asks Home over loopback, the same exception Netwatch already uses for `/api/state`. Netwatch reads the notification switch the same way. If Home can't be reached, each falls back to its built-in defaults; Netwatch keeps sending, as today. *(my call)*

### New services

- Home already lists containers through the read-only docker proxy every 30 seconds. Use that same pass, including stopped containers.
- **First scan:** everything present becomes known, without any "new" rows. Containers that aren't dock apps, such as exporters and the docker proxy, stay out of the lists.
- **After that:** a new container appears under a "New" heading in Services & dock, switched off, with a plain icon and a name taken from the container. The owner can rename it (only the label shown, not the Docker name), or dismiss it with **Ignore**. Ignored containers stay ignored.
- **Finding the port**, in order: *(my call on the order)*
  1. One published port: use it. Ports bound to `127.0.0.1` don't count, and duplicates from IPv4 and IPv6 count once.
  2. Several published ports: the row asks the owner to pick one.
  3. None, as with host-network containers: use the number at the end of a `name-port` name if there is one, otherwise the row asks the owner to type it.
- A switched-on service needs a port. Without one it can't go on the dock.
- **Containers that disappear:** marked "not running" and kept until the owner removes the row.
- **If Docker can't be read:** change nothing. Only a successful read can add a service or mark one as gone.

### Apps

A link per service with a known address, plus UGOS. Where an app has a known settings URL use it, otherwise open the app. Shown whether or not the app is on the dock. No settings are copied here.

### Account

**Moving the login to a file.** Today the hash and secret are environment variables, fixed at container start. To allow changes without a restart:

- New shared folder `/volume1/docker/admin-auth/` holding one file, mode 600. Mount the **folder**, not the file, because an atomic replace wouldn't reach a container with the single file mounted. Writable in Home, read-only in `mc-web` and Netwatch. All three run as the same user (`1000:10`).
- `auth.py` reads it instead of the environment, without re-reading it on every request when it hasn't changed, and stays identical across the three stacks.
- **Fail closed:** a present but invalid file refuses every login. It does not fall back to anything else.
- **Migration:** a one-time step on the NAS copies the existing values across, so the current password keeps working and nobody has to retype it. Remove `admin-auth.env` from the compose files afterwards.
- `scripts/set-admin-password.py` writes the new format and remains the way back in over SSH if the password is forgotten. Update the README command.
- Add the folder to `.gitignore`. `scripts/sync-from-nas.sh` must not copy it.

**Change password:** current password + new password twice, at least 8 characters as in the script. Uses the same wrong-password delay and one-at-a-time lock as login. It logs out every other device and keeps this one logged in. *(my call)*

**Log out everywhere:** changes the session secret and logs out every device including this one, after a confirmation step. It takes effect on all three services without a restart.

## Deployment

- Follow `CLAUDE.md`: edit `stacks/`, copy to the NAS, apply, run `scripts/sync-from-nas.sh`, commit.
- Update `README.md`: services table, container names, Admin login section, alert rules, changelog.
- Update `docs/mockups/public-admin.html` to match, as the last feature did.

## How to know it works

**Part 1**

- `docker ps` shows the new names, all healthy, and all Kuma monitors stay up.
- Mission Control's AdGuard and Speedtest cards show live CPU and memory, and Home's restart rule still reads every container.

**Part 2**

- Tests in each stack's `tests/` for: settings validation and out-of-range values, a corrupt settings file, thresholds reaching both `attention.py` and the guest status, the new-service rules (first scan, each port case, Ignore, disappearing, and a failed Docker read changing nothing), and password change and log-out-everywhere across the shared file.
- Logged out, with `curl` against the NAS: every new route refuses, on Home and on the new Mission Control route.
- Add a real feed, and a URL that isn't a feed. Turn one off and confirm it leaves both Home and the guest page.
- Change a threshold so a demo condition fires, and confirm the admin alert and guest card both follow. Restore it.
- Start a throwaway container with a published port: it appears under "New" within a minute, stays off the dock until switched on, then links correctly from both the LAN address and Tailscale. Remove it and confirm "not running".
- Change the password: the old one fails on all three ports, the other logged-in browser is logged out, and this one isn't. Log out everywhere logs out both. Then confirm `scripts/set-admin-password.py` still gets back in.
- Restart Home, Mission Control and Netwatch: settings persist and login still works.
- `git status` and the secret scan show no settings file, hash or secret.

## Left to the builder

File layout, the API's names and shapes, the shape of `settings.json`, how the Home server wakes the news worker, the known settings URLs for each app, and what a Home rail link does when its Mission Control card is hidden.
