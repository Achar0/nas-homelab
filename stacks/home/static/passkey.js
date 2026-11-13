// WebAuthn helpers shared by the login dialog and Account settings.
// The server speaks base64url; the browser API wants ArrayBuffers.

export function b64urlToBuf(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
}

export function bufToB64url(buf) {
  const bin = String.fromCharCode(...new Uint8Array(buf));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const withIds = (list) => list?.map((c) => ({ ...c, id: b64urlToBuf(c.id) }));

export function toCreateOptions(o) {
  const out = { ...o, challenge: b64urlToBuf(o.challenge), user: { ...o.user, id: b64urlToBuf(o.user.id) } };
  if (o.excludeCredentials) out.excludeCredentials = withIds(o.excludeCredentials);
  return out;
}

export function toGetOptions(o) {
  const out = { ...o, challenge: b64urlToBuf(o.challenge) };
  if (o.allowCredentials) out.allowCredentials = withIds(o.allowCredentials);
  return out;
}

export async function passkeysAvailable() {
  return Boolean(window.PublicKeyCredential && window.isSecureContext);
}
