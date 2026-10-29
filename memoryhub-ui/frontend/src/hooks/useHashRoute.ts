import { useCallback, useEffect, useState } from 'react';

/**
 * Minimal hash router: `#/memories?q=postgres&scope=project`.
 *
 * Hash routing keeps every screen and filter linkable without server-side
 * route handling, so the BFF and the OpenShift route config stay unchanged.
 */
export interface HashRoute {
  path: string;
  params: URLSearchParams;
}

const ROUTE_EVENT = 'memoryhub:route';

export const parseHash = (hash: string = window.location.hash): HashRoute => {
  const raw = hash.replace(/^#/, '') || '/';
  const [pathPart, query = ''] = raw.split('?');
  const path = `/${pathPart.replace(/^\/+|\/+$/g, '')}`;
  return { path, params: new URLSearchParams(query) };
};

export const buildHash = (path: string, params?: URLSearchParams | Record<string, string | undefined>) => {
  const qs = new URLSearchParams();
  if (params instanceof URLSearchParams) {
    params.forEach((value, key) => {
      if (value !== '') qs.append(key, value);
    });
  } else if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') qs.set(key, value);
    });
  }
  const query = qs.toString();
  return `#${path}${query ? `?${query}` : ''}`;
};

export interface NavigateOptions {
  /** Replace the current history entry (filter tweaks) instead of pushing one. */
  replace?: boolean;
}

export const navigate = (
  path: string,
  params?: URLSearchParams | Record<string, string | undefined>,
  options: NavigateOptions = {},
) => {
  const hash = buildHash(path, params);
  if (hash === window.location.hash) return;
  if (options.replace) {
    window.history.replaceState(window.history.state, '', hash);
    // replaceState does not fire hashchange; tell listeners ourselves.
    window.dispatchEvent(new Event(ROUTE_EVENT));
  } else {
    window.location.hash = hash;
  }
};

export const useHashRoute = (): HashRoute => {
  const [route, setRoute] = useState<HashRoute>(() => parseHash());

  const sync = useCallback(() => setRoute(parseHash()), []);

  useEffect(() => {
    window.addEventListener('hashchange', sync);
    window.addEventListener(ROUTE_EVENT, sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener(ROUTE_EVENT, sync);
    };
  }, [sync]);

  return route;
};
