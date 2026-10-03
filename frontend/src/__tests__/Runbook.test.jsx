import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';

async function renderRunbook() {
    // Import after stubbing the env so the API base is read from VITE_API_URL.
    const { default: Runbook } = await import('../pages/Runbook');
    render(
        <MemoryRouter initialEntries={['/runbook/moderate/eng-01']}>
            <Routes>
                <Route path="/runbook/:severity/:userId" element={<Runbook />} />
            </Routes>
        </MemoryRouter>
    );
}

beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_API_URL', 'https://api.example.test');
});

afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
});

// The first dynamic import of the page (recharts, lucide) takes ~10s under jsdom.
describe('Runbook page', { timeout: 30000 }, () => {
    it('requests tasks from the configured API base, not localhost (BUG-01)', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true, status: 200,
            json: () => Promise.resolve({ tasks: [{ title: 'Use caching', desc: 'Cache your CLAUDE.md' }], source: 'ai' }),
        });
        vi.stubGlobal('fetch', fetchMock);

        await renderRunbook();

        expect(await screen.findByText('Cache your CLAUDE.md')).toBeInTheDocument();
        expect(fetchMock.mock.calls[0][0]).toBe('https://api.example.test/api/runbook-tasks/moderate/eng-01');
    });

    it('shows an error instead of an empty runbook when the request fails', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

        await renderRunbook();

        expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load/i);
    });
});
