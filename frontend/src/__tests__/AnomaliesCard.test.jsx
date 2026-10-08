import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, afterEach } from 'vitest';

const ANOMALIES = {
    days: 14,
    anomalies: [
        { user_id: 'u3', name: 'Ada Lovelace', date: '2026-03-30', cost_usd: 61.5, baseline_median_usd: 12.25,
          excess_usd: 49.25, z: 21.3, driver: 'volume', driver_label: 'more tokens (e.g. a runaway agent loop)' },
        { user_id: 'u5', name: 'Bo Chen', date: '2026-03-27', cost_usd: 30.1, baseline_median_usd: 14.0,
          excess_usd: 16.1, z: 6.2, driver: 'cache', driver_label: 'caching broke (more uncached input)' },
    ],
};

function mock(body) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(body) }));
}

async function renderCard() {
    const { default: AnomaliesCard } = await import('../components/AnomaliesCard');
    render(<MemoryRouter><AnomaliesCard /></MemoryRouter>);
}

afterEach(() => vi.unstubAllGlobals());

describe('Spend anomalies card (UPG-07)', { timeout: 30000 }, () => {
    it('lists each anomaly against that engineer\'s usual cost, with the likely cause', async () => {
        mock(ANOMALIES);
        await renderCard();

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
        expect(screen.getByText(/\$61\.50/)).toBeInTheDocument();
        expect(screen.getByText(/usually \$12\.25/)).toBeInTheDocument();
        expect(screen.getByText(/runaway agent loop/)).toBeInTheDocument();
        expect(screen.getByText(/caching broke/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Ada Lovelace/ })).toHaveAttribute('href', '/engineer/u3');
        expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(/\/api\/anomalies\?days=14$/);
    });

    it('says when there is nothing unusual', async () => {
        mock({ days: 14, anomalies: [] });
        await renderCard();

        expect(await screen.findByText(/No unusual spend in the last 14 days/)).toBeInTheDocument();
    });
});
