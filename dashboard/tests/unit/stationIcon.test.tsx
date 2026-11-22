import { describe, expect, test, vi } from 'vitest';
import { render } from '@testing-library/react';
import { StationIcon, type StationIconKey } from '../../src/components/floor/StationIcon.tsx';
import { NeuronButton } from '../../src/components/floor/NeuronButton.tsx';
import { STATIONS } from '../../src/components/floor/layout.ts';

describe('StationIcon component', () => {
  const iconKeys: StationIconKey[] = [
    'intake', 'triage', 'spec', 'gate', 'gherkin', 'build', 'verify', 'report', 'knowledge',
  ];

  test.each(iconKeys)('renders svg with aria-hidden for %s', (key) => {
    const { container } = render(<StationIcon name={key} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    expect(svg?.getAttribute('data-station-icon')).toBe(key);
    expect(svg?.getAttribute('viewBox')).toBe('0 0 24 24');
    expect(svg?.getAttribute('width')).toBe('32');
    expect(svg?.getAttribute('height')).toBe('32');
  });
});

describe('NeuronButton component', () => {
  const triageStation = STATIONS.find((s) => s.id === 'triage')!;
  const gateSpecStation = STATIONS.find((s) => s.id === 'gate_spec')!;
  const intakeStation = STATIONS.find((s) => s.id === 'intake')!;

  test('renders working state with .spin ring and working dot', () => {
    const { container } = render(
      <NeuronButton
        station={triageStation}
        state="working"
        taskDots={[]}
        sub="agy · gemini-3.8-flash"
        selected={false}
        onClick={vi.fn()}
      />
    );
    const btn = container.querySelector('button');
    expect(btn).not.toBeNull();
    expect(btn?.getAttribute('aria-label')).toBe('Triage: Working');

    const spinRing = container.querySelector('.spin');
    expect(spinRing).not.toBeNull();
    expect(spinRing?.getAttribute('aria-hidden')).toBe('true');

    const workingDot = container.querySelector('[data-badge="working"]');
    expect(workingDot).not.toBeNull();
  });

  test('renders waiting gate with .breathe ring and "!" badge', () => {
    const { container } = render(
      <NeuronButton
        station={gateSpecStation}
        state="waiting"
        taskDots={[]}
        sub="you"
        selected={false}
        onClick={vi.fn()}
      />
    );
    const btn = container.querySelector('button');
    expect(btn?.getAttribute('aria-label')).toBe('You approve spec: Needs you');

    const breatheRing = container.querySelector('.breathe');
    expect(breatheRing).not.toBeNull();

    const waitingBadge = container.querySelector('[data-badge="waiting"]');
    expect(waitingBadge).not.toBeNull();
    expect(waitingBadge?.textContent).toBe('!');
  });

  test('renders done station with check badge and saturated filter', () => {
    const { container } = render(
      <NeuronButton
        station={intakeStation}
        state="done"
        taskDots={[]}
        sub="engine"
        selected={false}
        onClick={vi.fn()}
      />
    );
    const btn = container.querySelector('button');
    expect(btn?.getAttribute('aria-label')).toBe('Intake: Done');

    const doneBadge = container.querySelector('[data-badge="done"]');
    expect(doneBadge).not.toBeNull();
    expect(doneBadge?.querySelector('svg')).not.toBeNull();
  });

  test('renders build lane number badge top-left', () => {
    const laneStation = {
      ...STATIONS.find((s) => s.id === 'build')!,
      id: 'build-1',
      name: 'Filter by dept',
      glyph: 'B2',
      laneIdx: 1,
    };
    const { container } = render(
      <NeuronButton
        station={laneStation}
        state="working"
        taskDots={[]}
        sub="claude · sonnet-4.6"
        selected={true}
        onClick={vi.fn()}
      />
    );
    const laneNum = container.querySelector('.floor-lane-num');
    expect(laneNum).not.toBeNull();
    expect(laneNum?.textContent).toBe('2');
  });

  test('renders paused station with paused badge and ring', () => {
    const { container } = render(
      <NeuronButton
        station={triageStation}
        state="paused"
        taskDots={[]}
        sub="agy · gemini-3.8-flash"
        selected={false}
        onClick={vi.fn()}
      />
    );
    const pausedBadge = container.querySelector('[data-badge="paused"]');
    expect(pausedBadge).not.toBeNull();
  });
});
