// The toolbar popup: pairing (same 6-digit code as the widget) and, for the page in the
// active tab, « Joindre cette page » (ticked by default; unticking holds for this page).
// The questions are asked in the widget, not here.
import { Daemon } from "./lib/daemon.js";
import { isExcluded, setExcluded } from "./lib/page.js";
import { DAEMON_DEFAULT, pickTab, shareableOrigin, validDaemonUrl } from "./lib/util.js";
const $ = (id) => document.getElementById(id);
function status(message, error = false) {
    $("status").textContent = message;
    $("status").classList.toggle("status--err", error);
}
const fail = (err) => status(err instanceof Error ? err.message : String(err), true);
async function stored() {
    const data = await chrome.storage.local.get(["base", "token"]);
    const base = typeof data.base === "string" && validDaemonUrl(data.base) ? data.base : DAEMON_DEFAULT;
    return { base, token: typeof data.token === "string" ? data.token : null };
}
function showPairing(base, why = "") {
    $("main").hidden = true;
    $("pair").hidden = false;
    $("daemon").value = base;
    $("link").className = "link link--off";
    if (why)
        status(why, true);
}
async function pairStart() {
    const base = validDaemonUrl($("daemon").value);
    if (!base)
        return status("Adresse du démon invalide (http://127.0.0.1:<port>).", true);
    await chrome.storage.local.set({ base });
    await new Daemon(base, null).pairStart();
    status("Code affiché sur le bureau Windows : tapez-le ci-dessous.");
}
async function pairFinish() {
    const code = $("pair-code").value.trim();
    if (!/^[0-9]{6}$/.test(code))
        return status("Le code fait 6 chiffres.", true);
    const { base } = await stored();
    const token = await new Daemon(base, null).pairFinish(code);
    await chrome.storage.local.set({ token });
    $("pair-code").value = "";
    status("Extension couplée : le widget voit maintenant vos pages.");
    await start();
}
async function showPage(base) {
    const self = `chrome-extension://${chrome.runtime.id}`;
    const tab = pickTab(await chrome.tabs.query({ active: true, lastFocusedWindow: true }), self) ?? pickTab(await chrome.tabs.query({ active: true }), self);
    const origin = shareableOrigin(tab?.url, base);
    const attach = $("attach");
    if (!tab || !origin) {
        $("page").textContent = "Cette page ne peut pas être jointe (page du navigateur, ou du démon).";
        attach.disabled = true;
        attach.checked = false;
        return;
    }
    $("page").textContent = `${tab.title || origin} — ${origin}`;
    attach.disabled = false;
    attach.checked = !(await isExcluded(tab));
    attach.onchange = () => {
        setExcluded(tab, !attach.checked)
            .then(() => status(attach.checked ? "Le widget peut joindre cette page." : "Cette page reste pour vous (tant que vous y êtes)."))
            .catch(fail);
    };
}
async function start() {
    const { base, token } = await stored();
    if (!token)
        return showPairing(base);
    if (!(await new Daemon(base, token).verify()))
        return showPairing(base, "Ce démon ne reconnaît pas l'extension : recouplez-la.");
    $("link").className = "link link--on";
    $("pair").hidden = true;
    $("main").hidden = false;
    await showPage(base);
}
$("pair-start").addEventListener("click", () => void pairStart().catch(fail));
$("pair-finish").addEventListener("click", () => void pairFinish().catch(fail));
start().catch(fail);
