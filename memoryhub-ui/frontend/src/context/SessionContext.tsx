import React, { createContext, useContext, useEffect, useState } from 'react';
import { Alert, Flex, Spinner } from '@patternfly/react-core';
import { fetchMe } from '@/api/client';
import type { DashboardSession } from '@/types';

const SessionContext = createContext<DashboardSession | null>(null);

export const SessionProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [session, setSession] = useState<DashboardSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchMe().then((value) => {
      if (active) setSession(value);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Unable to load dashboard access');
    });
    return () => { active = false; };
  }, []);

  if (error) return <Alert variant="danger" title="Unable to load dashboard access" isInline>{error}</Alert>;
  if (!session) {
    return <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '4rem' }}>
      <Spinner size="xl" aria-label="Loading dashboard access" />
    </Flex>;
  }
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
};

export function useSession(): DashboardSession {
  const session = useContext(SessionContext);
  if (!session) throw new Error('Dashboard components require SessionProvider');
  return session;
}
