import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, afterEach } from 'vitest';

const LEADERBOARD = [
    // Rank 1 but getting worse: the old code always showed the top 3 as "up".
    { user_id: 'a', name: 'Ada', efficiency_score: 80.0, estimated_cost_usd: 12.5, input_tokens: 9e6,
      output_tokens: 1e5, score_change_7d: -2.46, recent_activity: [8e6, 9e6] },
    { user_id: 'b', name: 'Bo', efficiency_score: 70.0, estimated_cost_usd: 10.0, input_tokens: 4e6,
      output_tokens: 1e5, score_change_7d: null, recent_activity: [4e6] },
    { user_id: 'c', name: 'Cy', efficiency_score: 60.0, estimated_cost_usd: 8.0, input_tokens: 2e6,
      output_tokens: 1e5, score_change_7d: 0, recent_activity: [2e6] },
    // Rank 4 and improving: the old code always showed rank 4+ as "down".
    { user_id: 'd', name: 'Dee', efficiency_score: 50.0, estimated_cost_usd: 6.0, input_tokens: 1e6,
      output_tokens: 1e5, score_change_7d: 4.1, recent_activity: [1e6] },
];

function mockApi() {
    vi.stubGlobal('fetch', vi.fn((url) => {
        const body = url.endsWith('/api/leaderboard') ? LEADERBOARD
            : url.endsWith('/api/trends') ? [{ date: '2026-03-31', avg_score: 65, total_cost: 36.5 }]
            : { frequency: 'Weekly', day: 'Friday', time: '17:00' };
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }));
}

afterEach(() => vi.unstubAllGlobals());

describe('Dashboard leaderboard trends (BUG-07)', { timeout: 30000 }, () => {
    it('shows each engineer\'s real 7-day score change, not one derived from rank', async () => {
        mockApi();
        const { default: Dashboard } = await import('../pages/Dashboard');
        render(<MemoryRouter><Dashboard /></MemoryRouter>);

        const declining = await screen.findByText('-2.5');
        const improving = screen.getByText('+4.1');

        expect(declining.className).toContain('text-rose-500');
        expect(improving.className).toContain('text-emerald-500');
        expect(screen.getByText('0.0').className).not.toMatch(/emerald|rose/);
    });
});

describe('Dashboard alert schedule timezone (ARCH-02)', { timeout: 30000 }, () => {
    it('shows the saved timezone and saves in the browser timezone', async () => {
        const { fireEvent } = await import('@testing-library/react');
        const posts = [];
        vi.stubGlobal('fetch', vi.fn((url, options = {}) => {
            if (options.method === 'POST') {
                posts.push(JSON.parse(options.body));
                return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'success' }) });
            }
            const body = url.endsWith('/api/leaderboard') ? LEADERBOARD
                : url.endsWith('/api/trends') ? [{ date: '2026-03-31', avg_score: 65, total_cost: 36.5 }]
                : { frequency: 'Weekly', day: 'Friday', time: '17:00', timezone: 'Pacific/Auckland' };
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
        }));
        vi.stubGlobal('prompt', () => 'admin-token');

        const { default: Dashboard } = await import('../pages/Dashboard');
        render(<MemoryRouter><Dashboard /></MemoryRouter>);

        expect(await screen.findByText('Pacific/Auckland')).toBeInTheDocument();
        fireEvent.click(screen.getByText('SAVE SYNC'));
        await vi.waitFor(() => expect(posts).toHaveLength(1));

        expect(posts[0].timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    });
});
