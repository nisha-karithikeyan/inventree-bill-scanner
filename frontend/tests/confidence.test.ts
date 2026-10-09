import { describe, expect, it } from 'vitest';
import { confidenceColor, confirmBlocker, isBusy, lineConfidence, lineLevel, percent } from '../src/confidence';
import { bill, line } from './fixtures';

describe('line confidence', () => {
  it('uses the weaker of read and match confidence', () => {
    expect(lineConfidence(line({ confidence: 0.6, match_confidence: 0.9 }))).toBe(0.6);
    expect(lineConfidence(line({ part: null }))).toBe(0);
  });

  it('classifies rows for highlighting', () => {
    expect(lineLevel(line(), 0.75)).toBe('high');
    expect(lineLevel(line({ match_confidence: 0.5 }), 0.75)).toBe('low');
    expect(lineLevel(line({ part: null }), 0.75)).toBe('missing');
    expect(lineLevel(line({ part: null, skip: true }), 0.75)).toBe('high');
  });

  it('formats and colours scores', () => {
    expect(percent(0.856)).toBe('86%');
    expect(confidenceColor(0.8, 0.75)).toBe('green');
    expect(confidenceColor(0.5, 0.75)).toBe('yellow');
    expect(confidenceColor(0.2, 0.75)).toBe('red');
  });
});

describe('confirmBlocker', () => {
  it('allows a fully matched bill', () => {
    expect(confirmBlocker(bill())).toBeNull();
  });

  it('explains what is missing', () => {
    expect(confirmBlocker(bill({ supplier: null }))).toMatch(/supplier/);
    expect(confirmBlocker(bill({ lines: [line({ part: null })] }))).toMatch(/1 line/);
    expect(confirmBlocker(bill({ lines: [line({ skip: true })] }))).toMatch(/skipped/);
    expect(confirmBlocker(bill({ status: 'failed' }))).toMatch(/under review/);
  });

  it('ignores unmatched lines that are skipped', () => {
    const lines = [line(), line({ pk: 2, part: null, skip: true })];
    expect(confirmBlocker(bill({ lines }))).toBeNull();
  });

  it('knows which statuses are still busy', () => {
    expect(isBusy(bill({ status: 'retry' }))).toBe(true);
    expect(isBusy(bill({ status: 'review' }))).toBe(false);
  });
});
