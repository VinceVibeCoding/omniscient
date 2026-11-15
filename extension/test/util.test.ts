import assert from "node:assert/strict";
import { test } from "node:test";
import { expectedProof, newNonce, proves } from "../src/lib/proof.js";
import { clip, constantTimeEq, originOf, pickTab, pushCapped, shareableOrigin, stripQuery, validDaemonUrl } from "../src/lib/util.js";

test("only http(s) pages have an origin we may read", () => {
  assert.equal(originOf("https://shop.example/cart?x=1"), "https://shop.example");
  assert.equal(originOf("http://localhost:3000/a"), "http://localhost:3000");
  for (const bad of [undefined, "", "chrome://settings", "file:///C:/x", "javascript:alert(1)", "edge://newtab", "not a url"]) {
    assert.equal(originOf(bad), null, String(bad));
  }
});

test("pages on the daemon's own address are never shared", () => {
  assert.equal(shareableOrigin("http://127.0.0.1:3000/"), null);
  assert.equal(shareableOrigin("http://[::1]:3000/"), null);
  assert.equal(shareableOrigin("http://localhost:3000/a"), "http://localhost:3000");
  assert.equal(shareableOrigin("https://shop.example/x"), "https://shop.example");
});

test("the panel never takes itself for the page", () => {
  const self = "chrome-extension://abc";
  assert.deepEqual(pickTab([{ url: `${self}/panel.html` }, { url: "https://a.example/" }], self), { url: "https://a.example/" });
  assert.deepEqual(pickTab([{}], self), {});
  assert.equal(pickTab([{ url: `${self}/panel.html` }], self), null);
});

test("query strings and fragments are dropped", () => {
  assert.equal(stripQuery("https://api.example/v1/pay?token=zzz#f"), "https://api.example/v1/pay");
  assert.equal(stripQuery("::"), "");
});

test("lists and texts are capped", () => {
  assert.deepEqual(pushCapped([1, 2, 3], 4, 3), [2, 3, 4]);
  assert.equal(clip("abcdef", 3), "abc");
});

test("the daemon address is the machine itself only", () => {
  assert.equal(validDaemonUrl("http://127.0.0.1:7341/"), "http://127.0.0.1:7341");
  assert.equal(validDaemonUrl("http://localhost:9000"), "http://localhost:9000");
  for (const bad of ["https://127.0.0.1:7341", "http://evil.example:7341", "http://user:pw@127.0.0.1:7341", "http://127.0.0.1:7341/x", "http://127.0.0.1:7341?a=1", "nope"]) {
    assert.equal(validDaemonUrl(bad), null, bad);
  }
});

test("the proof matches the Python daemon and the Rust widget", async () => {
  const token = "abcDEF0123456789_-xyz-widget-token";
  const nonce = "00112233445566778899aabbccddeeff";
  const daemon = "fbbe1881b498da5847cd78833b9926d3d6402fec86a03fa16a84b45e47af523b";
  assert.equal(await expectedProof(token, nonce), daemon);
  assert.equal(await proves(["nope", daemon], token, nonce), true);
  assert.equal(await proves(["nope"], token, nonce), false);
  assert.equal(await proves(null, token, nonce), false);
});

test("nonces are fresh 32-character hex", () => {
  const [a, b] = [newNonce(), newNonce()];
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.notEqual(a, b);
  assert.equal(constantTimeEq("abc", "abc"), true);
  assert.equal(constantTimeEq("abc", "abd"), false);
});
