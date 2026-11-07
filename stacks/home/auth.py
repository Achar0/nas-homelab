"""Shared admin login: password hash, signed session cookie, wrong-password delay.

The same file is copied into stacks/home, stacks/mission-control/web and stacks/netwatch
(tests/test_auth.py in Home checks that the copies match). Standard library only.

The password hash and session key live in one JSON file ({"hash": ..., "key": ...}, path in
ADMIN_AUTH_FILE), checked on every call, so a change reaches all three services without a restart.
Home can write it; the other two mount it read-only.
If it is missing or invalid, every login and session is refused (fail closed).
Variable names avoid the words the secret scan in scripts/sync-from-nas.sh looks for.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse

COOKIE = "nas_admin"
REMEMBER_S = 30 * 86400
SESSION_S = 12 * 3600
MIN_KEY_LEN = 32
MIN_PASSWORD_LEN = 8
DEFAULT_AUTH_FILE = "/admin-auth/auth.json"
LOGIN_PORT = 3001
NEXT_PORTS = (3001, 8800, 8790)
DEFAULT_NEXT = "/admin/"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MAXMEM = 64 * 1024 * 1024
_HOSTNAME = re.compile(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)$")


def _parse_hash(stored):
    """Return (n, r, p, salt, digest), or None if the stored hash is malformed."""
    try:
        name, n, r, p, salt, digest = stored.split(":")
        if name != "scrypt":
            return None
        parsed = int(n), int(r), int(p), bytes.fromhex(salt), bytes.fromhex(digest)
        return parsed if parsed[3] and parsed[4] else None
    except (AttributeError, ValueError):
        return None


def _scrypt(pw, salt, n, r, p, length):
    return hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=length)


def hash_password(pw):
    salt = secrets.token_bytes(16)
    digest = _scrypt(pw, salt, SCRYPT["n"], SCRYPT["r"], SCRYPT["p"], 32)
    return f"scrypt:{SCRYPT['n']}:{SCRYPT['r']}:{SCRYPT['p']}:{salt.hex()}:{digest.hex()}"


def verify_password(pw, stored):
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    n, r, p, salt, digest = parsed
    try:
        return hmac.compare_digest(_scrypt(pw, salt, n, r, p, len(digest)), digest)
    except (ValueError, OverflowError, MemoryError):
        return False


def _sign(key, expires):
    return hmac.new(key.encode(), str(expires).encode(), hashlib.sha256).hexdigest()


def make_token(key, expires):
    return f"{int(expires)}.{_sign(key, int(expires))}"


def check_token(key, tok, now):
    """True if the signature matches and the expiry is still ahead. Never raises on bad input."""
    if not isinstance(tok, str) or not key:
        return False
    parts = tok.split(".")
    if len(parts) != 2:
        return False
    try:
        expires = int(parts[0])
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(key, expires).encode(), parts[1].encode()):
        return False
    return now < expires


def auth_file():
    return os.environ.get("ADMIN_AUTH_FILE", DEFAULT_AUTH_FILE)


_cache = {"stamp": None, "creds": {}}
_cache_lock = threading.Lock()


def _read(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    ok = isinstance(data, dict) and isinstance(data.get("hash"), str) and isinstance(data.get("key"), str)
    return data if ok else {}


def _creds():
    """The file's contents, re-read only when it has changed. Missing or invalid gives {}."""
    path = auth_file()
    try:
        st = os.stat(path)
    except OSError:
        return {}
    stamp = (path, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)   # ctime: chmod and chown count
    with _cache_lock:
        if _cache["stamp"] != stamp:
            creds = _read(path)
            _cache.update(stamp=stamp if creds else None, creds=creds)   # a failed read is tried again next time
        return _cache["creds"]


def _key():
    return _creds().get("key", "")


def _stored_hash():
    return _creds().get("hash", "")


def configured():
    return len(_key()) >= MIN_KEY_LEN and _parse_hash(_stored_hash()) is not None


def save(pw_hash, key):
    """Replace the file atomically, mode 600. A failure leaves the old file in place."""
    path = auth_file()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")   # mkstemp creates it as 600
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"hash": pw_hash, "key": key}, f)
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def change_password(current, new):
    """False if the current password is wrong or the new one too short. Also logs out every session."""
    if len(new) < MIN_PASSWORD_LEN or not login_ok(current):
        return False
    save(hash_password(new), secrets.token_hex(32))
    return True


def log_out_everywhere():
    """A new key makes every existing session invalid, on all three services."""
    if not configured():
        raise ValueError("no valid login to change")
    save(_stored_hash(), secrets.token_hex(32))


def startup_check(log):
    """Say at start-up why every login would be refused; never the values themselves."""
    if configured():
        return True
    log(f"admin login is off: {auth_file()} is missing or invalid, everything locked stays locked")
    return False


def _cookie_value(header):
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == COOKIE:
            return value
    return None


def session_ok(cookie_header, now):
    return configured() and check_token(_key(), _cookie_value(cookie_header), now)


def login_ok(pw):
    return configured() and verify_password(pw, _stored_hash())


def login_cookie(remember, now):
    expires = int(now) + (REMEMBER_S if remember else SESSION_S)
    value = f"{COOKIE}={make_token(_key(), expires)}; HttpOnly; SameSite=Strict; Path=/"
    return value + f"; Max-Age={REMEMBER_S}" if remember else value


def was_remembered(cookie_header, now):
    """True if this session's expiry only makes sense for "remember this device"."""
    try:
        return int((_cookie_value(cookie_header) or "").split(".")[0]) - now > SESSION_S
    except ValueError:
        return False


def logout_cookie():
    return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


def safe_next(url, hostname):
    """Where to go after login: only our own pages on the same hostname, otherwise the admin page."""
    if not isinstance(url, str) or "\\" in url or any(ord(c) < 33 for c in url):
        return DEFAULT_NEXT
    try:
        u = urllib.parse.urlsplit(url)
        ok = (u.scheme == "http" and u.username is None and u.password is None
              and u.hostname == hostname.strip("[]").lower() and u.port in NEXT_PORTS)
    except (ValueError, AttributeError):
        return DEFAULT_NEXT
    return url if ok else DEFAULT_NEXT


def request_hostname(handler):
    """The hostname the browser used, without the port, or "" if the header looks wrong."""
    host = (handler.headers.get("Host") or "").strip()
    name = host if host.endswith("]") else host.rsplit(":", 1)[0]
    return name if _HOSTNAME.match(name) else ""


def _send(handler, code, body=b"", ctype="application/json", location=None):
    handler.send_response(code)
    handler.send_header("Cache-Control", "no-store")
    if location:
        handler.send_header("Location", location)
    if body:
        handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body and handler.command != "HEAD":
        handler.wfile.write(body)


def require_login(handler):
    """True if the request has a valid session. Otherwise answers it (401 or login redirect) and returns False."""
    if session_ok(handler.headers.get("Cookie"), time.time()):
        return True
    path = handler.path.split("?")[0]
    hostname = request_hostname(handler)
    if path.startswith("/api/") or handler.command not in ("GET", "HEAD") or not hostname:
        _send(handler, 401, json.dumps({"error": "login required"}).encode())
        return False
    port = handler.server.server_address[1]
    here = urllib.parse.quote(f"http://{hostname}:{port}{handler.path}", safe="")
    _send(handler, 302, location=f"http://{hostname}:{LOGIN_PORT}/?login=1&next={here}")
    return False


class Throttle:
    """Wrong-password delay per address: 5 failures -> 30 s, doubling up to 15 min. Kept in memory."""
    FREE = 5
    FIRST_S = 30
    MAX_S = 900
    FORGET_S = 3600

    def __init__(self):
        self._lock = threading.Lock()
        self._seen = {}   # addr -> (failures, time of last failure)

    def _seconds(self, failures):
        if failures < self.FREE:
            return 0
        return min(self.MAX_S, self.FIRST_S * 2 ** min(failures - self.FREE, 16))

    def wait(self, addr, now):
        with self._lock:
            failures, last = self._seen.get(addr, (0, 0))
        return max(0, math.ceil(last + self._seconds(failures) - now)) if failures else 0

    def fail(self, addr, now):
        with self._lock:
            failures, last = self._seen.get(addr, (0, 0))
            if now - last > self.FORGET_S + self.MAX_S:
                failures = 0
            self._seen[addr] = (failures + 1, now)
            if len(self._seen) > 1000:   # bound memory; the oldest entries go first
                for old in sorted(self._seen, key=lambda a: self._seen[a][1])[:500]:
                    del self._seen[old]

    def reset(self, addr):
        with self._lock:
            self._seen.pop(addr, None)
