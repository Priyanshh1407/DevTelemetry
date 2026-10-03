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
