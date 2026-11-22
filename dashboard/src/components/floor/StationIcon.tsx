import type { ReactElement, CSSProperties } from 'react';

export type StationIconKey =
  | 'intake'
  | 'triage'
  | 'spec'
  | 'gate'
  | 'gherkin'
  | 'build'
  | 'verify'
  | 'report'
  | 'knowledge';

export function getStationIconKey(stationId: string, kind?: string): StationIconKey {
  if (kind === 'gate') return 'gate';
  if (stationId.startsWith('build')) return 'build';
  return stationId as StationIconKey;
}

export interface StationIconProps {
  name: StationIconKey;
  className?: string;
  style?: CSSProperties;
}

export function StationIcon({ name, className, style }: StationIconProps): ReactElement {
  let content: ReactElement;

  switch (name) {
    case 'intake':
      content = (
        <>
          <path d="M5 5h14l2 8v6H3v-6z" fill="#fff" fillOpacity={0.18} />
          <path d="M3 13h5l2 3h4l2-3h5" fill="#fff" fillOpacity={0.45} />
          <path d="M12 3.5v6M9.5 7l2.5 2.5L14.5 7" />
        </>
      );
      break;
    case 'triage':
      content = (
        <>
          <path d="M4 18a8 8 0 1 1 16 0z" fill="#fff" fillOpacity={0.18} />
          <path d="M4 18a8 8 0 0 1 4-6.9" strokeWidth={2.6} strokeOpacity={0.6} />
          <path d="M12 18l4.2-6.2" />
          <circle cx={12} cy={18} r={1.6} fill="#fff" />
        </>
      );
      break;
    case 'spec':
      content = (
        <>
          <path d="M7 3h7l4 4v14H7z" fill="#fff" fillOpacity={0.18} />
          <path d="M14 3v4h4" fill="#fff" fillOpacity={0.45} />
          <path d="M9.5 11.5h6M9.5 14.5h6M9.5 17.5h3.5" />
        </>
      );
      break;
    case 'gate':
      content = (
        <>
          <circle cx={10} cy={8} r={3.6} fill="#fff" fillOpacity={0.3} />
          <path d="M3.5 20c.8-3.6 3.4-5.5 6.5-5.5 1.3 0 2.5.3 3.5.9" fill="#fff" fillOpacity={0.18} />
          <circle cx={18} cy={17.5} r={3.6} fill="#fff" fillOpacity={0.9} stroke="none" />
          <path d="M16.4 17.6l1.1 1.1 2.1-2.2" stroke="#B8651B" strokeWidth={1.5} />
        </>
      );
      break;
    case 'gherkin':
      content = (
        <>
          <rect x={3} y={4} width={18} height={16} rx={3} fill="#fff" fillOpacity={0.16} />
          <path d="M11 9h6.5M11 15h6.5" />
          <path d="M6.3 9l1.2 1.2L9.6 8M6.3 15l1.2 1.2 2.1-2.2" />
        </>
      );
      break;
    case 'build':
      content = (
        <>
          <rect x={3} y={4} width={18} height={16} rx={3} fill="#fff" fillOpacity={0.16} />
          <path d="M3 8h18" strokeOpacity={0.7} />
          <circle cx={5.6} cy={6} r={0.6} fill="#fff" />
          <circle cx={7.6} cy={6} r={0.6} fill="#fff" />
          <path d="M9.5 11.5L7 14l2.5 2.5M14.5 11.5L17 14l-2.5 2.5M12.8 10.8l-1.6 6.4" />
        </>
      );
      break;
    case 'verify':
      content = (
        <>
          <path d="M12 3l7 3v6c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6z" fill="#fff" fillOpacity={0.2} />
          <path d="M8.6 12.2l2.3 2.3 4.5-4.6" strokeWidth={2} />
        </>
      );
      break;
    case 'report':
      content = (
        <>
          <rect x={4} y={3} width={16} height={18} rx={2.5} fill="#fff" fillOpacity={0.16} />
          <rect x={7} y={13} width={2.4} height={5} rx={0.8} fill="#fff" stroke="none" />
          <rect x={10.8} y={9} width={2.4} height={9} rx={0.8} fill="#fff" fillOpacity={0.75} stroke="none" />
          <rect x={14.6} y={11} width={2.4} height={7} rx={0.8} fill="#fff" fillOpacity={0.5} stroke="none" />
          <path d="M7 6.5h6" />
        </>
      );
      break;
    case 'knowledge':
      content = (
        <>
          <path d="M3.5 5.5C3.5 4.7 4.2 4 5 4h6v16H5c-.8 0-1.5-.7-1.5-1.5z" fill="#fff" fillOpacity={0.22} />
          <path d="M20.5 5.5c0-.8-.7-1.5-1.5-1.5h-6v16h6c.8 0 1.5-.7 1.5-1.5z" fill="#fff" fillOpacity={0.12} />
          <path d="M6 8h3M6 11h3M15 8h3" />
          <path d="M17.5 12.5l.7 1.4 1.5.2-1.1 1 .3 1.5-1.4-.7-1.4.7.3-1.5-1.1-1 1.5-.2z" fill="#fff" strokeWidth={1} />
        </>
      );
      break;
    default:
      content = <circle cx={12} cy={12} r={8} fill="#fff" fillOpacity={0.2} />;
  }

  return (
    <svg
      aria-hidden="true"
      data-station-icon={name}
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="#fff"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={{
        position: 'relative',
        filter: 'drop-shadow(0 1px 1.5px rgba(0,0,0,.35))',
        flexShrink: 0,
        ...style,
      }}
    >
      {content}
    </svg>
  );
}
