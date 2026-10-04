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

const GUIDE = {
    tasks: [{ title: 'Run /compact more', desc: 'You used /compact in 14.3% of sessions.' },
            { title: 'Reuse cache', desc: 'Only 57.7% of prompt tokens came from cache.' }],
    source: 'ai', headline: 'Context management is costing you the most points.', cached: true,
};
const DETAILS = {
    name: 'Ada Lovelace', email: 'ada@example.com', current_rank: 10, current_severity: 'critical',
    latest: { efficiency_score: 42.66, estimated_cost_usd: 6.51,
              score_breakdown: { cache: 23.07, model_mix: 15.3, discipline: 4.29, total: 42.66 } },
    history: [], averages: {}, patterns: [],
};

function routeFetch(guide, details = DETAILS) {
    return vi.fn((url) => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(url.includes('/runbook-tasks/') ? guide : details),
    }));
}

describe('Runbook shows real data only (Phase 7)', { timeout: 30000 }, () => {
    it('shows the engineer, their numbers, the headline and the guide', async () => {
        vi.stubGlobal('fetch', routeFetch(GUIDE));

        await renderRunbook();

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
        expect(screen.getByText('Context management is costing you the most points.')).toBeInTheDocument();
        expect(screen.getByText('Run /compact more')).toBeInTheDocument();
        expect(screen.getByText('42.66')).toBeInTheDocument();
        expect(screen.getByText('$6.51')).toBeInTheDocument();
        expect(screen.getByText(/rank #10/i)).toBeInTheDocument();
        expect(screen.getByText(/context management/i, { selector: '[data-testid="weakest"]' })).toBeInTheDocument();
        expect(screen.getByText(/ai-generated/i)).toBeInTheDocument();
    });

    it('says plainly when the guide is the rule-based fallback', async () => {
        vi.stubGlobal('fetch', routeFetch({ ...GUIDE, source: 'rate_limited', headline: null, cached: false }));

        await renderRunbook();

        expect(await screen.findByText(/rule-based guide/i)).toBeInTheDocument();
    });

    it('contains none of the old made-up content', async () => {
        vi.stubGlobal('fetch', routeFetch(GUIDE));

        await renderRunbook();
        await screen.findByText('Ada Lovelace');

        const page = document.body.textContent;
        for (const invented of ['MTTR', 'Stakeholder', '1,420', '2m 44s', 'automatically downgrade', 'Marcus', 'New Incident']) {
            expect(page).not.toContain(invented);
        }
        expect(document.querySelector('img[src*="googleusercontent"]')).toBeNull();
    });

    it('still shows the guide when the engineer details fail to load', async () => {
        vi.stubGlobal('fetch', vi.fn((url) => url.includes('/runbook-tasks/')
            ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(GUIDE) })
            : Promise.reject(new TypeError('Failed to fetch'))));

        await renderRunbook();

        expect(await screen.findByText('Run /compact more')).toBeInTheDocument();
    });
});
