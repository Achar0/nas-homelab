"""Passkey (WebAuthn) login for the admin: options, verification and storage.

The relying party is the NAS's Tailscale name (NAS_TS_NAME) and the only accepted origin is
https://{NAS_TS_NAME}:3443, so passkeys only work in HTTPS mode. One user ("admin"); passkeys must be
discoverable and verify the user (biometric or PIN). Attestation is not requested or checked.
Every check failure raises PasskeyError; callers treat it as a refused login.

Uses the cryptography package for signatures; everything else is the standard library.
Passkeys live in passkeys.json next to auth.json, so a password change keeps them.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import tempfile
import threading

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

import auth

ES256, RS256 = -7, -257
CHALLENGE_S = 120
MAX_CHALLENGES = 100
MAX_PASSKEYS = 20
MAX_NAME = 40
MAX_DEPTH = 8
MAX_CLIENT_DATA = 4096   # real clientDataJSON is a few hundred bytes
MIN_RSA_BITS = 2048
TIMEOUT_MS = CHALLENGE_S * 1000
USER_ID = b"admin"
# Authenticator data flags
UP, UV, AT, ED = 0x01, 0x04, 0x40, 0x80


class PasskeyError(ValueError):
    """A refused passkey: the message is a short reason for logs."""


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64url(text):
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (TypeError, ValueError) as e:
        raise PasskeyError("bad base64url") from e


def default_path():
    return os.path.join(os.path.dirname(auth.auth_file()), "passkeys.json")


# --- CBOR (just what WebAuthn needs) ---

def _decode(data, pos, depth):
    """Decode one item at pos; return (value, next position). depth counts enclosing arrays/maps."""
    if pos >= len(data):
        raise PasskeyError("cbor truncated")
    major, ai = data[pos] >> 5, data[pos] & 0x1F
    pos += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if ai not in simple:
            raise PasskeyError("cbor simple value or float not allowed")
        return simple[ai], pos
    if ai < 24:
        n = ai
    elif ai <= 27:
        size = 1 << (ai - 24)   # 1, 2, 4 or 8 bytes
        if pos + size > len(data):
            raise PasskeyError("cbor truncated")
        n = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise PasskeyError("cbor indefinite or reserved length")
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(data):
            raise PasskeyError("cbor truncated")
        raw = bytes(data[pos:pos + n])
        if major == 2:
            return raw, pos + n
        try:
            return raw.decode("utf-8"), pos + n
        except UnicodeDecodeError as e:
            raise PasskeyError("cbor bad utf-8") from e
    if major in (4, 5):
        if depth >= MAX_DEPTH:
            raise PasskeyError("cbor nested too deep")
        if n > len(data) - pos:   # every item takes at least one byte
            raise PasskeyError("cbor truncated")
        if major == 4:
            items = []
            for _ in range(n):
                item, pos = _decode(data, pos, depth + 1)
                items.append(item)
            return items, pos
        result = {}
        for _ in range(n):
            key, pos = _decode(data, pos, depth + 1)
            if not isinstance(key, (int, str, bytes)) or isinstance(key, bool) or key is None:
                raise PasskeyError("cbor map key type")
            if key in result:
                raise PasskeyError("cbor duplicate map key")
            result[key], pos = _decode(data, pos, depth + 1)
        return result, pos
    raise PasskeyError("cbor tags not allowed")   # major 6


def cbor_decode(data):
    """Decode exactly one CBOR item; anything unexpected or left over raises PasskeyError."""
    if not isinstance(data, (bytes, bytearray)):
        raise PasskeyError("cbor input is not bytes")
    value, pos = _decode(bytes(data), 0, 0)
    if pos != len(data):
        raise PasskeyError("cbor trailing bytes")
    return value


# --- Challenges ---

class Challenges:
    """Single-use challenges, valid for 120 s, kept in memory (at most 100, oldest dropped)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}   # challenge -> (kind, created); insertion order = oldest first

    def new(self, kind, now):
        challenge = b64url(secrets.token_bytes(32))
        with self._lock:
            while len(self._pending) >= MAX_CHALLENGES:
                del self._pending[next(iter(self._pending))]
            self._pending[challenge] = (kind, now)
        return challenge

    def take(self, kind, challenge, now):
        """True if the challenge is pending, of this kind and fresh. It is used up either way."""
        if not isinstance(challenge, str):
            return False
        given = challenge.encode()
        with self._lock:
            match = next((c for c in self._pending if hmac.compare_digest(c.encode(), given)), None)
            if match is None:
                return False
            got_kind, created = self._pending.pop(match)
        return got_kind == kind and 0 <= now - created < CHALLENGE_S


# --- Options for the browser ---

def _origin():
    return f"https://{auth.ts_name()}:{auth.HTTPS_LOGIN_PORT}"


def registration_options(challenge, existing):
    return {
        "challenge": challenge,
        "rp": {"id": auth.ts_name(), "name": "NAS"},
        "user": {"id": b64url(USER_ID), "name": "admin", "displayName": "NAS admin"},
        "pubKeyCredParams": [{"type": "public-key", "alg": ES256}, {"type": "public-key", "alg": RS256}],
        "authenticatorSelection": {"residentKey": "required", "userVerification": "required"},
        "attestation": "none",
        "excludeCredentials": [{"type": "public-key", "id": e["id"]} for e in existing],
        "timeout": TIMEOUT_MS,
    }


def login_options(challenge):
    return {"challenge": challenge, "rpId": auth.ts_name(), "userVerification": "required",
            "timeout": TIMEOUT_MS, "allowCredentials": []}


# --- Verification ---

def _check_client_data(client_data_json, kind, challenge_ok):
    """Check type, challenge and origin of clientDataJSON."""
    if not auth.ts_name():
        raise PasskeyError("passkeys need NAS_TS_NAME")
    if not isinstance(client_data_json, bytes):
        raise PasskeyError("client data is not bytes")
    if len(client_data_json) > MAX_CLIENT_DATA:
        raise PasskeyError("client data too long")
    try:
        data = json.loads(client_data_json)
    except (ValueError, TypeError, RecursionError) as e:   # deep nesting -> RecursionError
        raise PasskeyError("client data is not JSON") from e
    if not isinstance(data, dict):
        raise PasskeyError("client data is not an object")
    if data.get("type") != kind:
        raise PasskeyError("wrong client data type")
    challenge = data.get("challenge")
    if not isinstance(challenge, str) or not challenge_ok(challenge):
        raise PasskeyError("unknown or expired challenge")
    if data.get("origin") != _origin():
        raise PasskeyError("wrong origin")
    if data.get("crossOrigin") not in (None, False):
        raise PasskeyError("cross-origin request")


def _parse_auth_data(auth_data):
    """Check RP ID hash and UP + UV; return (flags, sign_count, rest after the 37-byte header)."""
    if not isinstance(auth_data, bytes) or len(auth_data) < 37:
        raise PasskeyError("authenticator data too short")
    rp_hash = hashlib.sha256(auth.ts_name().encode()).digest()
    if not hmac.compare_digest(auth_data[:32], rp_hash):
        raise PasskeyError("wrong RP ID")
    flags = auth_data[32]
    if not flags & UP:
        raise PasskeyError("user not present")
    if not flags & UV:
        raise PasskeyError("user not verified")
    count = struct.unpack(">I", auth_data[33:37])[0]
    return flags, count, auth_data[37:]


def _check_extensions(flags, rest):
    """Whatever follows must be exactly one extensions map, and only if the ED flag says so."""
    if flags & ED:
        if not isinstance(cbor_decode(rest), dict):
            raise PasskeyError("bad extensions")
    elif rest:
        raise PasskeyError("trailing authenticator data")


def _public_key(cose):
    """A cryptography public key and its alg from a COSE key map: EC2 P-256 (-7) or RSA (-257)."""
    if not isinstance(cose, dict):
        raise PasskeyError("COSE key is not a map")
    kty, alg = cose.get(1), cose.get(3)
    try:
        if kty == 2 and alg == ES256 and cose.get(-1) == 1:
            x, y = cose.get(-2), cose.get(-3)
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
                raise PasskeyError("bad EC2 coordinates")
            nums = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1())
            return nums.public_key(), ES256   # raises ValueError if the point is not on the curve
        if kty == 3 and alg == RS256:
            n, e = cose.get(-1), cose.get(-2)
            if not (isinstance(n, bytes) and isinstance(e, bytes) and n and e):
                raise PasskeyError("bad RSA key")
            key = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
            if key.key_size < MIN_RSA_BITS:
                raise PasskeyError("RSA key too small")
            return key, RS256
    except ValueError as e:
        if isinstance(e, PasskeyError):
            raise
        raise PasskeyError("invalid public key") from e
    raise PasskeyError("unsupported key type")


def verify_registration(client_data_json, attestation_object, challenge_ok):
    """Check a new passkey; return {"id", "public_key" (COSE, base64url), "alg", "sign_count"}."""
    _check_client_data(client_data_json, "webauthn.create", challenge_ok)
    att = cbor_decode(attestation_object)
    if not (isinstance(att, dict) and isinstance(att.get("fmt"), str) and isinstance(att.get("attStmt"), dict)
            and isinstance(att.get("authData"), bytes)):
        raise PasskeyError("bad attestation object")
    # The attestation statement itself is not checked: we asked for "none".
    flags, count, rest = _parse_auth_data(att["authData"])
    if not flags & AT or len(rest) < 18:
        raise PasskeyError("no attested credential data")
    id_len = struct.unpack(">H", rest[16:18])[0]
    cred_id = rest[18:18 + id_len]
    if not 1 <= id_len <= 1023 or len(cred_id) != id_len:
        raise PasskeyError("bad credential id")
    key_start = 18 + id_len
    cose, key_end = _decode(rest, key_start, 0)
    _, alg = _public_key(cose)
    _check_extensions(flags, rest[key_end:])
    return {"id": b64url(cred_id), "public_key": b64url(rest[key_start:key_end]), "alg": alg, "sign_count": count}


def verify_login(cred_id, client_data_json, authenticator_data, signature, stored, challenge_ok):
    """Check a login assertion against the stored passkey; return the new sign count."""
    _check_client_data(client_data_json, "webauthn.get", challenge_ok)
    if stored is None:
        raise PasskeyError("unknown passkey")
    if stored.get("id") != cred_id:
        raise PasskeyError("credential id mismatch")
    flags, count, rest = _parse_auth_data(authenticator_data)
    if flags & AT:
        raise PasskeyError("unexpected attested data in login")
    _check_extensions(flags, rest)
    key, alg = _public_key(cbor_decode(_unb64url(stored.get("public_key", ""))))
    if alg != stored.get("alg"):
        raise PasskeyError("stored alg mismatch")
    if not isinstance(signature, bytes):
        raise PasskeyError("bad signature")
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    try:
        if alg == ES256:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as e:
        raise PasskeyError("bad signature") from e
    # A counter that does not go up suggests a cloned authenticator. Passkeys that always send 0
    # (Apple, Google) are fine; going back to 0 after a non-zero count is not.
    old = stored.get("sign_count", 0)
    if (count or old) and count <= old:
        raise PasskeyError("sign count did not increase")
    return count


# --- Storage ---

class Store:
    """The passkeys in a JSON file ({"passkeys": [...]}), written atomically with mode 600.

    A missing or invalid file counts as empty.
    """

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        items = data.get("passkeys") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [p for p in items if isinstance(p, dict) and isinstance(p.get("id"), str)]

    def _save(self, items):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".part")   # created as 600
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"passkeys": items}, f)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def all(self):
        with self._lock:
            return self._load()

    def get(self, cred_id):
        return next((p for p in self.all() if p["id"] == cred_id), None)

    def add(self, entry, name, now):
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= MAX_NAME or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise PasskeyError("name must be 1-40 characters")
        with self._lock:
            items = self._load()
            if len(items) >= MAX_PASSKEYS:
                raise PasskeyError(f"at most {MAX_PASSKEYS} passkeys")
            if any(p["id"] == entry["id"] for p in items):
                raise PasskeyError("passkey already added")
            items.append(dict(entry, name=name, created=now, last_used=None))
            self._save(items)

    def remove(self, cred_id):
        with self._lock:
            items = self._load()
            kept = [p for p in items if p["id"] != cred_id]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True

    def touch(self, cred_id, sign_count, now):
        """Record a login: the new sign count and when."""
        with self._lock:
            items = self._load()
            for p in items:
                if p["id"] == cred_id:
                    p.update(sign_count=sign_count, last_used=now)
                    self._save(items)
                    return
