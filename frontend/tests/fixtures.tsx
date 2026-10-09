import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import React from 'react';
import { vi } from 'vitest';
import type { Bill, BillLine, PluginContext } from '../src/types';

export function line(overrides: Partial<BillLine> = {}): BillLine {
  return {
    pk: 1,
    line_number: 1,
    description: 'M3 screw',
    sku: 'ACM-M3',
    quantity: '100.00000',
    unit_price: '0.050000',
    confidence: 0.95,
    part: 7,
    part_detail: { pk: 7, name: 'Screw M3', IPN: 'SCR-3', description: '', thumbnail: null },
    supplier_part: 3,
    match_method: 'supplier_sku',
    match_confidence: 1,
    skip: false,
    ...overrides
  };
}

export function bill(overrides: Partial<Bill> = {}): Bill {
  return {
    pk: 1,
    file_url: '/media/bill_scanner/x/bill.png',
    file_name: 'bill.png',
    status: 'review',
    status_label: 'Ready for review',
    attempts: 1,
    error: '',
    supplier_name: 'Acme',
    bill_number: 'INV-1',
    bill_date: '2026-09-30',
    currency: 'USD',
    supplier: 2,
    supplier_detail: { pk: 2, name: 'Acme Ltd' },
    supplier_confidence: 1,
    purchase_order: null,
    created_by: 'admin',
    created: '2026-10-01T10:00:00Z',
    lines: [line()],
    ...overrides
  };
}

// Like axios, the fake answers with loosely typed data; callers pick the type.
type FakeResponse = Promise<{ data: any }>;

export function fakeApi(bills: Bill[] = [bill()]) {
  return {
    get: vi.fn(async (url: string, _config?: unknown): FakeResponse => {
      if (url.endsWith('/bills/')) return { data: bills };
      const match = url.match(/bills\/(\d+)\/$/);
      if (match) return { data: bills.find((b) => b.pk === Number(match[1])) };
      return { data: { results: [] } };
    }),
    post: vi.fn(async (_url: string, _data?: unknown, _config?: unknown): FakeResponse => ({ data: bills[0] })),
    patch: vi.fn(async (_url: string, _data?: unknown): FakeResponse => ({ data: bills[0] })),
    delete: vi.fn(async (_url: string): Promise<unknown> => ({}))
  };
}

export function pluginContext(api = fakeApi(), overrides = {}): PluginContext {
  return {
    api,
    context: {
      api: '/plugin/bill-scanner/api',
      low_confidence: 0.75,
      max_upload_mb: 15,
      has_api_key: true,
      can_edit: true,
      can_confirm: true,
      ...overrides
    }
  };
}

export function renderWithMantine(node: React.ReactElement) {
  return render(<MantineProvider>{node}</MantineProvider>);
}
