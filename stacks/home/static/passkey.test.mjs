import test from "node:test";
import assert from "node:assert/strict";
import { b64urlToBuf, bufToB64url, toCreateOptions, toGetOptions } from "./passkey.js";

test("base64url round-trips without padding", () => {
  assert.equal(bufToB64url(b64urlToBuf("AQID_-8")), "AQID_-8");
  assert.deepEqual([...new Uint8Array(b64urlToBuf("AQID_-8"))], [1, 2, 3, 255, 239]);
  assert.equal(bufToB64url(new Uint8Array([1]).buffer), "AQ");          // no "=" padding
  assert.equal(bufToB64url(new Uint8Array([251, 255]).buffer), "-_8");  // URL alphabet, not + /
  assert.equal(bufToB64url(new ArrayBuffer(0)), "");
});

test("options get ArrayBuffers where WebAuthn wants them", () => {
  const c = toCreateOptions({ challenge: "AQID", user: { id: "BAUG", name: "admin" }, excludeCredentials: [{ type: "public-key", id: "Bw" }] });
  assert.ok(c.challenge instanceof ArrayBuffer && c.user.id instanceof ArrayBuffer && c.excludeCredentials[0].id instanceof ArrayBuffer);
  assert.equal(c.user.name, "admin");
  const g = toGetOptions({ challenge: "AQID", rpId: "x", allowCredentials: [] });
  assert.ok(g.challenge instanceof ArrayBuffer);
  assert.deepEqual(g.allowCredentials, []);
  assert.equal(toGetOptions({ challenge: "AQID" }).allowCredentials, undefined);
});
