import { fireEvent, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BillScannerPanel, renderBillScannerPanel } from '../src/BillScanner';
import { LineTable } from '../src/components/LineTable';
import { bill, fakeApi, line, pluginContext, renderWithMantine } from './fixtures';

describe('LineTable', () => {
  const lines = [
    line(),
    line({ pk: 2, line_number: 2, description: 'LED', match_confidence: 0.5, match_method: 'name' }),
    line({ pk: 3, line_number: 3, description: 'Mystery', part: null, part_detail: null })
  ];

  it('highlights low-confidence and unmatched lines', () => {
    renderWithMantine(
      <LineTable lines={lines} threshold={0.75} editable searchParts={async () => []} onChange={vi.fn()} />
    );
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows.map((row) => row.getAttribute('data-level'))).toEqual(['high', 'low', 'missing']);
    expect(screen.getByText('No part')).toBeInTheDocument();
    expect(screen.getByText('Name 50%')).toBeInTheDocument();
  });

  it('sends skip and quantity edits', () => {
    const onChange = vi.fn();
    renderWithMantine(
      <LineTable lines={lines} threshold={0.75} editable searchParts={async () => []} onChange={onChange} />
    );
    fireEvent.click(screen.getByLabelText('Skip line 3'));
    expect(onChange).toHaveBeenCalledWith(lines[2], { skip: true });

    const quantity = screen.getByLabelText('Quantity line 1');
    fireEvent.change(quantity, { target: { value: '120' } });
    fireEvent.blur(quantity);
    expect(onChange).toHaveBeenCalledWith(lines[0], { quantity: '120' });
  });

  it('is read-only when not editable', () => {
    renderWithMantine(
      <LineTable lines={lines} threshold={0.75} editable={false} searchParts={async () => []} onChange={vi.fn()} />
    );
    expect(screen.getByLabelText('Skip line 1')).toBeDisabled();
  });
});

describe('BillScannerPanel', () => {
  it('lists bills and opens one for review', async () => {
    renderWithMantine(<BillScannerPanel context={pluginContext()} />);
    const row = await screen.findByText('INV-1');
    fireEvent.click(row);
    expect(await screen.findByText('Create order and receive')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open original' })).toHaveAttribute(
      'href',
      '/media/bill_scanner/x/bill.png'
    );
  });

  it('blocks confirmation while a line has no part', async () => {
    const api = fakeApi([bill({ lines: [line({ part: null, part_detail: null })] })]);
    renderWithMantine(<BillScannerPanel context={pluginContext(api)} />);
    fireEvent.click(await screen.findByText('INV-1'));
    const button = (await screen.findByText('Create order and receive')).closest('button');
    expect(button).toBeDisabled();
    expect(screen.getByText(/1 line\(s\) have no part/)).toBeInTheDocument();
  });

  it('hides the confirm action without permission and warns about a missing key', async () => {
    const context = pluginContext(fakeApi(), { can_confirm: false, has_api_key: false });
    renderWithMantine(<BillScannerPanel context={context} />);
    fireEvent.click(await screen.findByText('INV-1'));
    await waitFor(() => expect(screen.queryByText('Create order and receive')).toBeNull());
    expect(screen.getByText('Gemini API key missing')).toBeInTheDocument();
  });

  it('exposes a one-argument entry point for InvenTree', () => {
    expect(renderBillScannerPanel.length).toBe(1);
  });
});
