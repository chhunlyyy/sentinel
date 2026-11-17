import { describe, expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DecisionPanel } from '../../src/components/DecisionPanel.tsx';

const H2 = '3f9a0c12' + 'ab'.repeat(28);
const LABEL = 'Type the first 8 characters of the sha256 to confirm';

describe('AC-SEC-03z the approve button stays disabled until the prefix matches', () => {
  const rows: [string, 'disabled' | 'enabled', string][] = [
    ['', 'disabled', 'Type the first 8 characters'],
    ['3f9a0c1', 'disabled', 'Type the first 8 characters'],
    ['3f9a0c13', 'disabled', 'Does not match'],
    ['3F9A0C12', 'disabled', 'Does not match'],
    [' 3f9a0c12', 'disabled', 'Does not match'],
    ['3f9a0c12', 'enabled', 'Matches'],
  ];
  test.each(rows)('AC-SEC-03z typed %j is %s', async (typed, state, hint) => {
    const user = userEvent.setup();
    render(<DecisionPanel kind="approval" version={2} sha256={H2} onDecide={vi.fn()} />);
    await user.click(screen.getByRole('radio', { name: 'Approve' }));
    const field = screen.getByLabelText(LABEL);
    expect(field).toHaveValue('');
    expect(field).toHaveAttribute('autocomplete', 'off');
    if (typed) await user.type(field, typed);
    const button = screen.getByRole('button', { name: 'Approve version 2' });
    if (state === 'enabled') expect(button).toBeEnabled();
    else expect(button).toBeDisabled();
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  test('AC-SPA-06i pasting the full hash does not match', async () => {
    const user = userEvent.setup();
    render(<DecisionPanel kind="approval" version={2} sha256={H2} onDecide={vi.fn()} />);
    await user.click(screen.getByRole('radio', { name: 'Approve' }));
    await user.click(screen.getByLabelText(LABEL));
    await user.paste(H2);
    expect(screen.getByRole('button', { name: 'Approve version 2' })).toBeDisabled();
  });
});
