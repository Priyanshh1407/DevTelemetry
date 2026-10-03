// Single place for backend calls. Every page must go through here so the API base
// comes from VITE_API_URL (a hardcoded localhost URL broke the Runbook in production)
// and HTTP errors are never mistaken for success.
export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
    constructor(status, detail) {
        const message = typeof detail === "string" ? detail : detail?.message;
        super(message || `Request failed (${status})`);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
    }
}

async function request(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, options);
    let body = null;
    try {
        body = await res.json();
    } catch {
        // Non-JSON body (e.g. a proxy error page); handled by the status check below.
    }
    if (!res.ok) {
        throw new ApiError(res.status, body?.detail ?? null);
    }
    return body;
}

export function getJSON(path) {
    return request(path);
}

export function postJSON(path, payload, headers = {}) {
    return request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: payload === undefined ? undefined : JSON.stringify(payload),
    });
}

// ── Admin actions (SEC-01) ──────────────────────────────────────────────────
// The admin token is never built into the bundle (anything in a Vite build is public).
// The admin types it once; it lives in sessionStorage, which is cleared when the tab closes.
const ADMIN_TOKEN_KEY = "devtelemetry.adminToken";

function readAdminToken() {
    try {
        return sessionStorage.getItem(ADMIN_TOKEN_KEY);
    } catch {
        return null; // storage blocked (private mode, sandboxed iframe)
    }
}

function storeAdminToken(token) {
    try {
        if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
        else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    } catch {
        // storage blocked: the admin will just be asked again next time
    }
}

export async function adminPost(path, payload, askForToken = (msg) => window.prompt(msg)) {
    const token = readAdminToken() || askForToken("Admin token required for this action:");
    if (!token) {
        throw new ApiError(401, "Admin token required.");
    }
    try {
        const body = await postJSON(path, payload, { "X-Admin-Token": token });
        storeAdminToken(token);
        return body;
    } catch (e) {
        // 401 = wrong token, 503 = admin disabled on the server: don't keep it.
        // Any other API error (429, 502, ...) happened after the token was accepted.
        if (e instanceof ApiError) storeAdminToken([401, 503].includes(e.status) ? null : token);
        throw e;
    }
}
