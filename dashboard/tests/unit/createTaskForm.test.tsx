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

  test('Save as draft stores draft into localStorage and restores it across renders', async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const onRequestChange = vi.fn();
    const { unmount } = render(
      <CreateTaskForm
        pid="test-proj"
        repos={['backend', 'frontend']}
        onSubmit={onSubmit}
        onRequestChange={onRequestChange}
      />
    );
    await user.type(screen.getByLabelText('Slug'), 'draft-task');
    await user.type(screen.getByLabelText('Request'), 'Draft request details');
    await user.selectOptions(screen.getByLabelText('Type'), 'bug');
    expect(onRequestChange).toHaveBeenCalledWith('Draft request details');

    await user.click(screen.getByRole('button', { name: 'Save as draft' }));
    expect(screen.getByText('Draft saved')).toBeInTheDocument();

    const stored = JSON.parse(window.localStorage.getItem('sentinel_task_draft_test-proj') || '{}');
    expect(stored.slug).toBe('draft-task');
    expect(stored.request).toBe('Draft request details');
    expect(stored.type).toBe('bug');

    unmount();

    render(
      <CreateTaskForm
        pid="test-proj"
        repos={['backend', 'frontend']}
        onSubmit={onSubmit}
      />
    );
    expect(screen.getByLabelText('Slug')).toHaveValue('draft-task');
    expect(screen.getByLabelText('Request')).toHaveValue('Draft request details');
    expect(screen.getByLabelText('Type')).toHaveValue('bug');
  });

  test('submitting the form clears the project draft from localStorage', async () => {
    window.localStorage.setItem(
      'sentinel_task_draft_test-proj',
      JSON.stringify({ slug: 'draft-task', request: 'Draft request', type: 'feature' })
    );
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <CreateTaskForm
        pid="test-proj"
        repos={['backend', 'frontend']}
        onSubmit={onSubmit}
      />
    );
    expect(screen.getByLabelText('Slug')).toHaveValue('draft-task');
    await user.click(screen.getByRole('button', { name: 'Create task' }));
    expect(onSubmit).toHaveBeenCalled();
    expect(window.localStorage.getItem('sentinel_task_draft_test-proj')).toBeNull();
  });

  test('localStorage errors are handled gracefully without crashing', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <CreateTaskForm
        pid="test-proj"
        repos={['backend', 'frontend']}
        onSubmit={onSubmit}
      />
    );
    await user.type(screen.getByLabelText('Slug'), 'fail-draft');
    await user.click(screen.getByRole('button', { name: 'Save as draft' }));
    expect(screen.getByLabelText('Slug')).toHaveValue('fail-draft');
    setItemSpy.mockRestore();
  });
});
