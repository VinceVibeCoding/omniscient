// Daemon proof (same as the Windows widget, M5): before sending its token, the extension
// checks that whatever answers on the port knows it. GET /health?nonce=N lists
// HMAC-SHA256(key = SHA-256(token), message = N) for every paired client.
import { constantTimeEq, hex } from "./util.js";

const encoder = new TextEncoder();

export async function expectedProof(token: string, nonce: string): Promise<string> {
  const keyBytes = await crypto.subtle.digest("SHA-256", encoder.encode(token));
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(nonce)));
}

export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return hex(bytes);
}

export async function proves(proofs: unknown, token: string, nonce: string): Promise<boolean> {
  if (!Array.isArray(proofs)) return false;
  const expected = await expectedProof(token, nonce);
  return proofs.some((p) => typeof p === "string" && constantTimeEq(p, expected));
}
