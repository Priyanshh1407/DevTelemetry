import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import Navbar from '../components/Navbar';

function renderNavbar(props) {
  render(<BrowserRouter><Navbar {...props} /></BrowserRouter>);
}

describe('Navbar Component', () => {
  it('renders the DevTelemetry logo, linking home', () => {
    renderNavbar();
    expect(screen.getByText('DevTelemetry').closest('a')).toHaveAttribute('href', '/');
  });

  it('only shows links that go somewhere (Phase 7: no dead mock-up links)', () => {
    renderNavbar();
    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', '/');
    for (const dead of ['Analytics', 'AI Agents', 'Coaching', 'NODES', 'SECURITY', 'Deploy Agent']) {
      expect(screen.queryByText(dead)).not.toBeInTheDocument();
    }
    expect(document.querySelector('img[src*="googleusercontent"]')).toBeNull();
    expect(screen.queryAllByRole('link').every((a) => a.getAttribute('href') !== '#')).toBe(true);
  });

  it('shows the page title it is given', () => {
    renderNavbar();
    expect(screen.getByText('Team Overview')).toBeInTheDocument();
    renderNavbar({ title: 'Engineer detail' });
    expect(screen.getByText('Engineer detail')).toBeInTheDocument();
  });
});
