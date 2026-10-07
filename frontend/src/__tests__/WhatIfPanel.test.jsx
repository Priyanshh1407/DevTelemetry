import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

function whatIf(cache, opus) {
    return {
        days: 30, period_days: 30, current_month_usd: 420.5,
        targets: { cache_hit: cache, opus_pct: opus },
        team_targets: { cache_hit: 0.82, opus_pct: 0.15 },
        current: { cache_hit: 0.55, opus_pct: 0.4 },
        cache: { projected_month_usd: 300.25, saving_month_usd: 120.25 },
        model: { projected_month_usd: 380.0, saving_month_usd: 40.5 },
        combined: { projected_month_usd: 270.0, saving_month_usd: 150.5 },
    };
}

afterEach(() => vi.unstubAllGlobals());

describe('What-if savings panel (UPG-06)', { timeout: 30000 }, () => {
    it('starts from the team top-quartile targets and shows each saving', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true, status: 200, json: () => Promise.resolve(whatIf(0.82, 0.15)),
        }));
        const { default: WhatIfPanel } = await import('../components/WhatIfPanel');
        render(<WhatIfPanel userId="u9" />);

        expect(await screen.findByText('$150.50')).toBeInTheDocument();      // combined saving
        expect(screen.getByText('$120.25')).toBeInTheDocument();
        expect(screen.getByText('$40.50')).toBeInTheDocument();
        expect(screen.getByText(/\$420\.50/)).toBeInTheDocument();
        expect(screen.getByLabelText(/Cache hit target/)).toHaveValue('82');
        expect(screen.getByText(/team's top quartile/)).toBeInTheDocument();
        expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(/\/api\/engineer\/u9\/what-if$/);
    });

    it('re-prices when a slider moves (debounced: one request)', async () => {
        vi.stubGlobal('fetch', vi.fn((url) => Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(url.includes('cache_hit=0.9') ? whatIf(0.9, 0.15) : whatIf(0.82, 0.15)),
        })));
        const { default: WhatIfPanel } = await import('../components/WhatIfPanel');
        render(<WhatIfPanel userId="u9" />);
        const slider = await screen.findByLabelText(/Cache hit target/);

        fireEvent.change(slider, { target: { value: '88' } });
        fireEvent.change(slider, { target: { value: '90' } });

        await vi.waitFor(() => expect(vi.mocked(fetch).mock.calls).toHaveLength(2));
        expect(vi.mocked(fetch).mock.calls[1][0]).toMatch(/what-if\?cache_hit=0\.9&opus_pct=0\.15$/);
    });

    it('shows an API error', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false, status: 404, json: () => Promise.resolve({ detail: 'No recent usage for this engineer' }),
        }));
        const { default: WhatIfPanel } = await import('../components/WhatIfPanel');
        render(<WhatIfPanel userId="u9" />);

        expect(await screen.findByText(/No recent usage for this engineer/)).toBeInTheDocument();
    });
});
