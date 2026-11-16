// The local Omnigroup daemon, as the extension sees it: pairing, and reporting the page. The token is only ever sent after
// the daemon proved it knows it (proof.ts); every call has a timeout; errors carry the
// daemon's French message.
import { newNonce, proves } from "./proof.js";
const TIMEOUT_MS = 20_000;
export const CLIENT_NAME = "Extension navigateur";
export class DaemonError extends Error {
    status;
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}
async function request(base, method, path, token, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const headers = {};
    if (token)
        headers.Authorization = `Bearer ${token}`;
    if (body !== undefined)
        headers["Content-Type"] = "application/json";
    try {
        const res = await fetch(`${base}${path}`, {
            method,
            headers,
            body: body === undefined ? undefined : JSON.stringify(body),
            signal: controller.signal,
            credentials: "omit",
            cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const message = typeof data.error === "string" ? data.error : `Erreur ${res.status}`;
            throw new DaemonError(message, res.status);
        }
        return data;
    }
    catch (err) {
        if (err instanceof DaemonError)
            throw err;
        throw new DaemonError("Démon Omnigroup injoignable : est-il lancé sur cette machine ?", 0);
    }
    finally {
        clearTimeout(timer);
    }
}
export class Daemon {
    base;
    token;
    constructor(base, token) {
        this.base = base;
        this.token = token;
    }
    /** True when the daemon on the port knows our token (never sends the token itself). */
    async verify() {
        if (!this.token)
            return false;
        const nonce = newNonce();
        const data = (await request(this.base, "GET", `/health?nonce=${nonce}`, null));
        return proves(data.proofs, this.token, nonce);
    }
    pairStart() {
        return request(this.base, "POST", "/pair/start", null, {});
    }
    async pairFinish(code) {
        const data = (await request(this.base, "POST", "/pair/finish", null, { code, client_name: CLIENT_NAME }));
        if (typeof data.token !== "string")
            throw new DaemonError("Réponse de couplage invalide.", 0);
        return data.token;
    }
    call(method, path, body) {
        return request(this.base, method, path, this.token, body);
    }
    /** The page in the browser, or that the person unticked it (PUT /browser/page). */
    async reportPage(body) {
        try {
            return await this.call("PUT", "/browser/page", body);
        }
        catch (err) {
            // A daemon older than this extension refuses the « outline » field: report without it.
            if (err instanceof DaemonError && err.status === 400 && "page" in body && /outline/.test(err.message)) {
                return this.call("PUT", "/browser/page", { page: { ...body.page, outline: undefined } });
            }
            throw err;
        }
    }
}
