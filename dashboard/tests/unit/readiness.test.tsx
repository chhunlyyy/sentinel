import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReadinessPanel } from '../../src/components/ReadinessPanel.tsx';

describe('AC-DSH-03b an item that was not checked is never shown as passed', () => {
  const rows: [string, string, string][] = [
    ['build_command', 'not_checked', 'Not checked'],
    ['test_command', 'passed', 'Validated'],
    ['lint_command', 'failed', 'Failed'],
    ['provider', 'unknown', 'Not checked'],
  ];
  test.each(rows)('AC-DSH-03b %s %s', (item, status, label) => {
    render(
      <ReadinessPanel
        readiness={{ state: 'ready_with_warnings', workflow: 'feature', checked_at: '2026-11-14T09:00:00Z', items: [{ id: item, status: status as never, message: 'configured value' }] }}
      />,
    );
    expect(screen.getByText(label, { selector: '[data-testid="item-status"]' })).toBeInTheDocument();
    if (status !== 'passed') expect(screen.queryByText('Validated')).toBeNull();
  });
});
