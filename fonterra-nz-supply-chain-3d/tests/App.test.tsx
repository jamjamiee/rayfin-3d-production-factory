import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { App } from '../src/App';
import { makeEmptySnapshot, makeSnapshot } from './fixtures';

vi.mock('../src/FactoryScene', () => ({
  SceneBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
  FactoryScene: ({ motion }: { motion: boolean }) => <div data-testid="scene" data-motion={String(motion)}>Test-only 3D boundary stub</div>,
}));
function serve(snapshot: ReturnType<typeof makeSnapshot>) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(snapshot)))));
}

describe('accessible operational UI', () => {
  it('shows quiet ingested history, selection, portfolio labels and grouped line details', async () => {
    serve(makeSnapshot(new Date().toISOString()));
    render(<App />);
    const table = await screen.findByRole('table');
    expect(screen.getByText('Stream quiet')).toBeInTheDocument();
    expect(screen.getByText(/Dock highlights show last recorded status—not current vehicle movement/)).toBeInTheDocument();
    expect(screen.getByTestId('scene')).toHaveAttribute('data-motion', 'false');
    expect(screen.getByText(/NZ consumer brands were divested to Lactalis on 31 March 2026/)).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: /NZ-TEST-001/ }));
    const details = screen.getByRole('region', { name: 'Details for NZ-TEST-001' });
    expect(details).toHaveFocus();
    expect(within(details).getByText('Milk powder')).toBeInTheDocument();
    expect(within(details).getAllByText('Not recorded')).toHaveLength(2);
    expect(within(details).getByText('12 tubs')).toBeInTheDocument();
    expect(within(details).getByText('Divested to Lactalis · 31 Mar 2026')).toBeInTheDocument();
  });
  it('filters the loaded list and never adjusts full-window metrics', async () => {
    const snapshot = makeSnapshot(new Date().toISOString());
    snapshot.totals.totalOrders = 230;
    serve(snapshot);
    render(<App />);
    await screen.findByRole('table');
    expect(screen.getByText(/Partial list: latest 6 of 230 orders/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Supermarket chain' }), 'New World');
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('230 orders in window')).toBeInTheDocument();
    await userEvent.type(screen.getByRole('searchbox'), 'no such destination');
    expect(screen.getByText('No matching orders')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(7);
  });
  it('lane and dock buttons filter orders and support toggling off', async () => {
    serve(makeSnapshot(new Date().toISOString()));
    render(<App />);
    await screen.findByRole('table');
    const lane = screen.getByRole('button', { name: /L01.*Dairy & milk/ });
    await userEvent.click(lane);
    expect(lane).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3);
    await userEvent.click(lane);
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(7);
    await userEvent.click(screen.getByRole('button', { name: /02 Wellington 1 in transit/ }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
    expect(screen.getByRole('heading', { name: 'Wellington dock' })).toBeInTheDocument();
  });
  it('has a real empty state and does not fabricate motion or events', async () => {
    serve(makeEmptySnapshot(new Date().toISOString()));
    render(<App />);
    expect(await screen.findByText('No orders in this snapshot')).toBeInTheDocument();
    expect(screen.getByTestId('scene')).toHaveAttribute('data-motion', 'false');
    expect(screen.getByText('No recorded events in this response.')).toBeInTheDocument();
  });
  it('keeps all-sold data static even with a recent event', async () => {
    const snapshot = makeSnapshot(new Date().toISOString());
    snapshot.orders.forEach((order) => { order.status = 'Sold'; });
    snapshot.lines.forEach((line) => { line.status = 'Sold'; });
    snapshot.totals.lastEventAt = snapshot.generatedAt;
    snapshot.totals.awaitingDispatch = 0;
    serve(snapshot);
    render(<App />);
    await screen.findByRole('table');
    expect(screen.getByText('Static · no received orders in loaded list')).toBeInTheDocument();
    expect(screen.getByTestId('scene')).toHaveAttribute('data-motion', 'false');
  });
});
