import { describe, expect, test, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DecisionPanel } from '../../src/components/DecisionPanel.tsx';

const H2 = '3f9a0c12' + 'ab'.repeat(28);

describe('DecisionPanel', () => {
  test('one-click approve sends decision approve with no confirmation', async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<DecisionPanel kind="approval" version={2} sha256={H2} onDecide={onDecide} />);

    const approveBtn = screen.getByRole('button', { name: 'Approve version 2' });
    expect(approveBtn).toBeEnabled();
    await user.click(approveBtn);
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith({ decision: 'approve', comment: null });
  });

  test('request changes requires text and sends comment to specifier', async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<DecisionPanel kind="approval" gate="specification" version={2} sha256={H2} onDecide={onDecide} />);

    const reqBtn = screen.getByRole('button', { name: 'Request changes' });
    await user.click(reqBtn);

    const textarea = screen.getByLabelText('What needs to change');
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveFocus();
    expect(textarea).toHaveAttribute('placeholder', 'Add a scenario for inactive parent departments');
    expect(screen.getByText('The specifier gets this text and writes a new version.')).toBeInTheDocument();

    const sendBtn = screen.getByRole('button', { name: 'Send back to the agent' });
    expect(sendBtn).toBeDisabled();

    await user.type(textarea, '   ');
    expect(sendBtn).toBeDisabled();

    await user.type(textarea, 'Add inactive parent departments rule');
    expect(sendBtn).toBeEnabled();

    await user.click(sendBtn);
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith({ decision: 'changes', comment: 'Add inactive parent departments rule' });
  });

  test('request changes hint refers to scenario writer when gate is gherkin', async () => {
    const user = userEvent.setup();
    render(<DecisionPanel kind="approval" gate="gherkin" version={1} sha256={H2} onDecide={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Request changes' }));
    expect(screen.getByText('The scenario writer gets this text and writes a new version.')).toBeInTheDocument();
  });

  test('cancelling request changes restores buttons and moves focus back', async () => {
    const user = userEvent.setup();
    render(<DecisionPanel kind="approval" version={2} sha256={H2} onDecide={vi.fn()} />);

    const reqBtn = screen.getByRole('button', { name: 'Request changes' });
    await user.click(reqBtn);
    expect(screen.getByLabelText('What needs to change')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('What needs to change')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Request changes' })).toHaveFocus();
    });
  });

  test('reject opens ConfirmDialog with required reason', async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<DecisionPanel kind="approval" subject="leave-balance" version={2} sha256={H2} onDecide={onDecide} />);

    const rejectBtn = screen.getByRole('button', { name: 'Reject run…' });
    await user.click(rejectBtn);

    expect(screen.getByText('Rejecting cancels run leave-balance. This cannot be undone.')).toBeInTheDocument();
    const reasonInput = screen.getByLabelText('Reason');
    expect(reasonInput).toBeInTheDocument();

    const confirmBtn = screen.getByRole('button', { name: 'Reject run' });
    expect(confirmBtn).toBeDisabled();

    await user.type(reasonInput, 'Cancelled by user');
    expect(confirmBtn).toBeEnabled();

    await user.click(confirmBtn);
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith({ decision: 'reject', comment: 'Cancelled by user' });
  });

  test('acceptance mode provides one-click accept and reject with reason', async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<DecisionPanel kind="acceptance" subject="leave-form" sha256={H2} onDecide={onDecide} />);

    const acceptBtn = screen.getByRole('button', { name: 'Accept' });
    expect(acceptBtn).toBeEnabled();
    await user.click(acceptBtn);
    expect(onDecide).toHaveBeenCalledWith({ decision: 'accept', comment: null });

    const rejectBtn = screen.getByRole('button', { name: 'Reject…' });
    await user.click(rejectBtn);
    expect(screen.getByText('Rejecting the acceptance of run leave-form. This cannot be undone.')).toBeInTheDocument();
    expect(screen.getByLabelText('Reason')).toBeInTheDocument();
  });

  test('disabled and pending states disable buttons', () => {
    const { rerender } = render(<DecisionPanel kind="approval" version={2} sha256={H2} disabled onDecide={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Approve version 2' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject run…' })).toBeDisabled();

    rerender(<DecisionPanel kind="approval" version={2} sha256={H2} pending onDecide={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Sending' })).toBeDisabled();
  });
});
