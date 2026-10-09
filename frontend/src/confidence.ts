import type { Bill, BillLine, BillStatus } from './types';

export type Level = 'high' | 'low' | 'missing';

/** The weaker of the extraction and match confidence decides the row colour. */
export function lineConfidence(line: BillLine): number {
  if (!line.part) return 0;
  return Math.min(line.confidence, line.match_confidence);
}

export function lineLevel(line: BillLine, threshold: number): Level {
  if (line.skip) return 'high';
  if (!line.part) return 'missing';
  return lineConfidence(line) < threshold ? 'low' : 'high';
}

export const LEVEL_BACKGROUND: Record<Level, string | undefined> = {
  high: undefined,
  low: 'var(--mantine-color-yellow-light)',
  missing: 'var(--mantine-color-red-light)'
};

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function confidenceColor(value: number, threshold: number): string {
  if (value >= threshold) return 'green';
  if (value >= threshold / 2) return 'yellow';
  return 'red';
}

export const STATUS_COLOR: Record<BillStatus, string> = {
  pending: 'gray',
  processing: 'blue',
  retry: 'orange',
  failed: 'red',
  review: 'yellow',
  completed: 'green'
};

const BUSY: BillStatus[] = ['pending', 'processing', 'retry'];

export function isBusy(bill: Bill): boolean {
  return BUSY.includes(bill.status);
}

/** Why the bill cannot be confirmed yet, or null when it can. */
export function confirmBlocker(bill: Bill): string | null {
  if (bill.status !== 'review') return 'Only bills under review can be received.';
  if (!bill.supplier) return 'Choose the supplier first.';
  const active = bill.lines.filter((line) => !line.skip);
  if (active.length === 0) return 'Every line is skipped.';
  const unmatched = active.filter((line) => !line.part).length;
  if (unmatched > 0) return `${unmatched} line(s) have no part. Pick a part or skip them.`;
  return null;
}
