import React, { useEffect, useState } from 'react';
import { Alert, Content, Label, Spinner, Title } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { AccessAssignments } from '@/types';
import { fetchAccessAssignments } from '@/api/client';

/**
 * Read-only list of who has been granted the dashboard Roles (#744).
 * Access is changed with memoryhub-ui/deploy/dashboard-access.sh or `oc`,
 * never from the dashboard.
 */
const DashboardAccess: React.FC = () => {
  const [data, setData] = useState<AccessAssignments | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAccessAssignments()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load access assignments'));
  }, []);

  return (
    <div style={{ marginTop: '2rem' }}>
      <Title headingLevel="h3" size="md">Dashboard access</Title>
      <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', marginTop: '0.25rem' }}>
        {data
          ? data.source === 'openshift-rbac'
            ? <>OpenShift RoleBindings in <code>{data.namespace}</code>. {data.note} Change access with <code>dashboard-access.sh</code>.</>
            : <>Transitional username lists. {data.note}</>
          : 'Who has been granted the dashboard roles.'}
      </Content>
      {error && <Alert variant="warning" title="Access assignments unavailable" isInline>{error}</Alert>}
      {!data && !error && <Spinner size="md" aria-label="Loading access assignments" />}
      {data && (
        <Table aria-label="Dashboard access assignments" variant="compact">
          <Thead>
            <Tr>
              <Th>Role</Th>
              <Th>Kind</Th>
              <Th>Name</Th>
              <Th>Granted by</Th>
              <Th modifier="nowrap">Granted at</Th>
            </Tr>
          </Thead>
          <Tbody>
            {data.assignments.length === 0 ? (
              <Tr><Td colSpan={5}>No assignments.</Td></Tr>
            ) : data.assignments.map((a) => (
              <Tr key={`${a.role}:${a.kind}:${a.name}:${a.binding ?? ''}`}>
                <Td dataLabel="Role"><Label color={a.role === 'admin' ? 'purple' : 'grey'} isCompact>{a.role}</Label></Td>
                <Td dataLabel="Kind">{a.kind}</Td>
                <Td dataLabel="Name"><code>{a.name}</code></Td>
                <Td dataLabel="Granted by">{a.granted_by ?? '—'}</Td>
                <Td dataLabel="Granted at">{a.granted_at ?? '—'}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </div>
  );
};

export default DashboardAccess;
