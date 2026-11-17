import { describe, expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateTaskForm } from '../../src/components/CreateTaskForm.tsx';

async function validForm() {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<CreateTaskForm repos={['backend', 'frontend']} onSubmit={onSubmit} />);
  await user.type(screen.getByLabelText('Slug'), 'leave-report');
  await user.type(screen.getByLabelText('Request'), 'Report leave per team');
  await user.selectOptions(screen.getByLabelText('Type'), 'feature');
  return { user, onSubmit };
}

describe('AC-TSK-01n the form checks fields before sending', () => {
  const msg = 'Use lower-case letters, digits and single hyphens';
  const rows: [string, string, string, string][] = [
    ['slug', 'Bad Slug', msg, 'Slug'],
    ['slug', 'a..b', msg, 'Slug'],
    ['slug', '', 'Required', 'Slug'],
    ['request', '   ', 'Required', 'Request'],
    ['type', '', 'Required', 'Type'],
  ];
  test.each(rows)('AC-TSK-01n field %s value %j', async (field, value, message, label) => {
    const { user } = await validForm();
    expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled();
    const el = screen.getByLabelText(label);
    if (field === 'type') await user.selectOptions(el, '');
    else {
      await user.clear(el);
      if (value) await user.type(el, value);
      else await user.type(el, 'x{backspace}');
    }
    expect(el).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create task' })).toBeDisabled();
  });

  test('AC-TSK-01n a valid form submits the Phase F body only', async () => {
    const { user, onSubmit } = await validForm();
    await user.click(screen.getByRole('button', { name: 'Create task' }));
    expect(onSubmit).toHaveBeenCalledWith({ slug: 'leave-report', request: 'Report leave per team', type: 'feature', priority: 'normal' });
  });
});
