import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi, afterEach } from 'vitest';

const DETAILS = {
    name: 'Ada Lovelace', email: 'ada@example.com', current_rank: 9, current_severity: 'critical',
    latest: { efficiency_score: 41.2, estimated_cost_usd: 18.4, cache_ratio: 0.52,
              opus_pct: 0.4, sonnet_pct: 0.4, haiku_pct: 0.2 },
    history: [
        { date: '2026-03-30', efficiency_score: 44.0, estimated_cost_usd: 17.0, input_tokens: 9e6, output_tokens: 1e5,
          cache_read_tokens: 4e6, cache_write_tokens: 3e5, opus_pct: 0.4, sonnet_pct: 0.4, haiku_pct: 0.2,
          session_count: 5, compact_uses: 1, git_commits: 4, cache_ratio: 0.44 },
        { date: '2026-03-31', efficiency_score: 41.2, estimated_cost_usd: 18.4, input_tokens: 1e7, output_tokens: 1e5,
          cache_read_tokens: 5.2e6, cache_write_tokens: 3e5, opus_pct: 0.4, sonnet_pct: 0.4, haiku_pct: 0.2,
          session_count: 6, compact_uses: 1, git_commits: 5, cache_ratio: 0.52 },
    ],
    averages: { avg_score: 42.6, avg_cost: 17.7, avg_cache_ratio: 0.48, avg_sessions: 5.5,
                total_commits: 9, avg_compact_ratio: 0.18 },
    patterns: [
        { label: 'Model Usage', insight: 'Uses Opus for 40.0% of requests — above team target of <15%' },
        { label: 'Cache Efficiency', insight: '48.0% cache hit ratio — room to improve prompt caching and reuse' },
        { label: 'Session Discipline', insight: 'Uses /compact 18.0% of sessions — recommend using /compact more often' },
    ],
};

async function renderDetail() {
    const { default: EngineerDetail } = await import('../pages/EngineerDetail');
    render(
        <MemoryRouter initialEntries={['/engineer/u9']}>
            <Routes><Route path="/engineer/:userId" element={<EngineerDetail />} /></Routes>
        </MemoryRouter>
    );
}

afterEach(() => vi.unstubAllGlobals());

describe('EngineerDetail page (TEST-01b)', { timeout: 30000 }, () => {
    it('renders the engineer and the insights computed by the API', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200, json: () => Promise.resolve(DETAILS),
        }));

        await renderDetail();

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
        expect(screen.getByText(/above team target/)).toBeInTheDocument();
        expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(/\/api\/engineer\/u9\/details$/);
    });

    it('shows the API\'s 404 message for an unknown engineer', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false, status: 404, json: () => Promise.resolve({ detail: 'Engineer not found' }),
        }));

        await renderDetail();

        expect(await screen.findByText('Engineer not found')).toBeInTheDocument();
    });
});

describe('EngineerDetail for someone not on today\'s leaderboard (BUG-08)', { timeout: 30000 }, () => {
    it('says "Not ranked today" instead of inventing a rank', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200,
            json: () => Promise.resolve({ ...DETAILS, current_rank: null, current_severity: null }),
        }));

        await renderDetail();

        expect(await screen.findByText(/Not ranked today/)).toBeInTheDocument();
        expect(screen.queryByText(/Rank #/)).not.toBeInTheDocument();
        expect(screen.getByText(/no data today/i)).toBeInTheDocument();
    });
});

describe('EngineerDetail score breakdown (UPG-03)', { timeout: 30000 }, () => {
    it('shows points per area and marks the weakest one', async () => {
        const breakdown = { cache: 12.0, model_mix: 11.7, discipline: 13.93, total: 37.63 };
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200,
            json: () => Promise.resolve({ ...DETAILS, latest: { ...DETAILS.latest, score_breakdown: breakdown } }),
        }));

        await renderDetail();

        const panel = await screen.findByRole('region', { name: /score breakdown/i });
        expect(panel).toHaveTextContent('12.0 / 40');
        expect(panel).toHaveTextContent('11.7 / 30');
        expect(panel).toHaveTextContent('13.9 / 30');
        // cache lost 28 points, the most: it is the area to work on
        expect(screen.getByText(/biggest opportunity: prompt caching/i)).toBeInTheDocument();
    });

    it('renders without a breakdown (older API responses)', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200, json: () => Promise.resolve(DETAILS),
        }));

        await renderDetail();

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: /score breakdown/i })).not.toBeInTheDocument();
    });
});

describe('EngineerDetail shows no placeholder assets (Phase 7)', { timeout: 30000 }, () => {
    it('uses initials instead of a made-up avatar URL, and titles the page', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200, json: () => Promise.resolve(DETAILS),
        }));

        await renderDetail();

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
        expect(screen.getByText('AL')).toBeInTheDocument();
        expect(document.querySelector('img[src*="googleusercontent"]')).toBeNull();
        expect(screen.getByText('Engineer detail')).toBeInTheDocument();
    });
});
