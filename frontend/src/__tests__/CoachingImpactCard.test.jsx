import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

const IMPACT = {
    n_events: 20, n_excluded: 4, n_days: 10,
    naive: { estimate: 5.74, ci_low: 4.1, ci_high: 7.2 },
    pre_post: { estimate: 4.19, ci_low: 2.5, ci_high: 5.9 },
    did: { estimate: 4.13, ci_low: 2.31, ci_high: 5.88 },
    window: { pre: [-13, -7], post: [1, 7] },
    events: [],
};

function mockImpact(body) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(body) }));
}

afterEach(() => vi.unstubAllGlobals());

describe('Coaching impact card (UPG-05)', { timeout: 30000 }, () => {
    it('leads with the difference-in-differences estimate and its interval', async () => {
        mockImpact(IMPACT);
        const { default: CoachingImpactCard } = await import('../components/CoachingImpactCard');
        render(<CoachingImpactCard />);

        expect(await screen.findByText('+4.1')).toBeInTheDocument();
        expect(screen.getByText(/95% CI \+2\.3 to \+5\.9/)).toBeInTheDocument();
        expect(screen.getByText(/Improvement detected/)).toBeInTheDocument();
        expect(screen.getByText(/20 coaching events/)).toBeInTheDocument();
        expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(/\/api\/coaching-impact\?days=120$/);
    });

    it('shows the naive number only with its bias spelled out', async () => {
        mockImpact(IMPACT);
        const { default: CoachingImpactCard } = await import('../components/CoachingImpactCard');
        render(<CoachingImpactCard />);

        expect(await screen.findByText(/\+5\.7/)).toBeInTheDocument();
        expect(screen.getByText(/naive before\/after \(biased by regression to the mean\)/i)).toBeInTheDocument();
    });

    it('says when the interval includes zero', async () => {
        mockImpact({ ...IMPACT, did: { estimate: 0.4, ci_low: -1.2, ci_high: 2.0 } });
        const { default: CoachingImpactCard } = await import('../components/CoachingImpactCard');
        render(<CoachingImpactCard />);

        expect(await screen.findByText(/No clear effect yet/)).toBeInTheDocument();
    });

    it('explains an empty state instead of showing zeros', async () => {
        mockImpact({ ...IMPACT, n_events: 0, n_excluded: 0, did: { estimate: null, ci_low: null, ci_high: null } });
        const { default: CoachingImpactCard } = await import('../components/CoachingImpactCard');
        render(<CoachingImpactCard />);

        expect(await screen.findByText(/No coaching with enough data before and after it yet/)).toBeInTheDocument();
    });
});
