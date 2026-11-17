import type { ApiError } from '../api/errors.ts';

/** Shows the actionable text of an API error and its code. Text only; never HTML. */
export function ErrorView({ error }: { error: ApiError }) {
  return (
    <div className="banner danger" data-testid="error-view">
      <span>{error.text}</span>
      {error.code ? (
        <>
          {' '}
          <code>{error.code}</code>
        </>
      ) : null}
    </div>
  );
}
