import { useEffect, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';

export interface Route {
  path: string;
  query: URLSearchParams;
}

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '') || '/';
  const q = raw.indexOf('?');
  const path = q < 0 ? raw : raw.slice(0, q);
  return { path: path.startsWith('/') ? path : `/${path}`, query: new URLSearchParams(q < 0 ? '' : raw.slice(q + 1)) };
}

export function useRoute(): Route {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return parseHash(hash);
}

export function navigate(to: string) {
  window.location.hash = to;
}

export function href(to: string): string {
  return `#${to}`;
}

export function segments(path: string): string[] {
  return path.split('/').filter(Boolean).map((s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  });
}

export const enc = encodeURIComponent;

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
  current?: boolean;
  children: ReactNode;
}

export function Link({ to, current, children, ...rest }: LinkProps) {
  return (
    <a href={href(to)} aria-current={current ? 'page' : undefined} {...rest}>
      {children}
    </a>
  );
}
