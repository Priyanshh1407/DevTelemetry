import { describe, it, expect, vi, afterEach } from 'vitest';
import { API_BASE, ApiError, getJSON, postJSON } from '../api';

function mockFetch(status, body) {
    const fetchMock = vi.fn().mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(body),
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
    it('returns the parsed body on success', async () => {
        const fetchMock = mockFetch(200, [{ name: 'a' }]);
        await expect(getJSON('/api/leaderboard')).resolves.toEqual([{ name: 'a' }]);
        expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/leaderboard`, {});
    });

    it('throws ApiError with the FastAPI detail string on failure', async () => {
        mockFetch(404, { detail: 'Engineer not found' });
        const error = await getJSON('/api/x').catch((e) => e);
        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(404);
        expect(error.message).toBe('Engineer not found');
    });

    it('uses detail.message when detail is an object', async () => {
        mockFetch(502, { detail: { message: '2 alerts failed', summary: {} } });
        const error = await postJSON('/api/trigger-alerts').catch((e) => e);
        expect(error.message).toBe('2 alerts failed');
        expect(error.detail.summary).toEqual({});
    });

    it('does not report success for a non-JSON error response', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false, status: 500, json: () => Promise.reject(new SyntaxError('bad json')),
        }));
        await expect(getJSON('/api/x')).rejects.toThrow('Request failed (500)');
    });

    it('sends JSON bodies and extra headers on POST', async () => {
        const fetchMock = mockFetch(200, { status: 'success' });
        await postJSON('/api/settings', { frequency: 'Daily' }, { 'X-Test': '1' });
        const [, options] = fetchMock.mock.calls[0];
        expect(options.method).toBe('POST');
        expect(options.headers).toEqual({ 'Content-Type': 'application/json', 'X-Test': '1' });
        expect(JSON.parse(options.body)).toEqual({ frequency: 'Daily' });
    });
});

describe('adminPost (SEC-01)', () => {
    afterEach(() => sessionStorage.clear());

    it('asks for the token once, sends it, and remembers it for the session', async () => {
        const { adminPost } = await import('../api');
        const fetchMock = mockFetch(200, { status: 'success' });
        const ask = vi.fn().mockReturnValue('secret-token');

        await adminPost('/api/trigger-alerts', undefined, ask);
        await adminPost('/api/trigger-alerts', undefined, ask);

        expect(ask).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[1][1].headers['X-Admin-Token']).toBe('secret-token');
    });

    it('forgets a rejected token so the next attempt asks again', async () => {
        const { adminPost } = await import('../api');
        mockFetch(401, { detail: 'Missing or invalid admin token.' });
        const ask = vi.fn().mockReturnValue('wrong');

        await expect(adminPost('/api/settings', {}, ask)).rejects.toThrow('Missing or invalid admin token.');
        await expect(adminPost('/api/settings', {}, ask)).rejects.toThrow();

        expect(ask).toHaveBeenCalledTimes(2);
    });

    it('does not call the API when no token is entered', async () => {
        const { adminPost } = await import('../api');
        const fetchMock = mockFetch(200, {});

        await expect(adminPost('/api/settings', {}, () => null)).rejects.toThrow('Admin token required');
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('validation errors (VAL-01)', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('turns a FastAPI 422 detail list into a readable message', async () => {
        mockFetch(422, { detail: [
            { loc: ['body', 'time'], msg: "String should match pattern '^([01]\d|2[0-3]):[0-5]\d$'" },
            { loc: ['body', 'day'], msg: 'Input should be a weekday' },
        ] });
        const error = await getJSON('/api/settings').catch((e) => e);
        expect(error.message).toBe("time: String should match pattern '^([01]\d|2[0-3]):[0-5]\d$'; day: Input should be a weekday");
    });
});
