import { describe, expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ModelControl } from '../../src/screens/Agents.tsx';
import type { Provider } from '../../src/api/orchestration.ts';

const prov = (over: Partial<Provider> = {}): Provider => ({
  id: 'claude',
  label: 'Claude Code',
  command: 'claude',
  installed: true,
  path: '/bin/claude',
  capabilities: { model_select: true, resume: true, json_output: true },
  models: [{ id: 'opus', label: 'Opus' }],
  ...over,
});

describe('ModelControl', () => {
  test('lists default, models and Custom', async () => {
    const onChange = vi.fn();
    render(<ModelControl roleName="qa" provider={prov()} row={{ runner: 'claude', model: '' }} onChange={onChange} />);
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Provider default', 'Opus', 'Custom...']);
    await userEvent.selectOptions(screen.getByLabelText('Model for qa'), 'opus');
    expect(onChange).toHaveBeenCalledWith('opus', false);
  });
  test('an unknown saved model selects Custom and shows its labelled input', () => {
    render(<ModelControl roleName="qa" provider={prov()} row={{ runner: 'claude', model: 'zzz' }} onChange={() => undefined} />);
    expect(screen.getByLabelText('Model for qa')).toHaveValue('__custom__');
    expect(screen.getByLabelText('Custom model id for qa')).toHaveValue('zzz');
    expect(screen.getByText('Custom model id')).toBeInTheDocument();
  });
  test('a provider without model option is disabled with a hint', () => {
    render(<ModelControl roleName="qa" provider={prov({ capabilities: { model_select: false, resume: false, json_output: false }, models: [] })} row={{ runner: 'claude', model: '' }} onChange={() => undefined} />);
    expect(screen.getByLabelText('Model for qa')).toBeDisabled();
    expect(screen.getByText(/no model option/)).toBeInTheDocument();
  });
});
