import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Content,
  Flex,
  Label,
  Spinner,
  Title,
} from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { UserEntry } from '@/types';
import { fetchUsers } from '@/api/client';
import { formatRelativeTime } from '@/utils/time';

interface UsersAgentsProps {
  onNavigateToGraph?: (ownerId: string) => void;
}

const UsersAgents: React.FC<UsersAgentsProps> = ({ onNavigateToGraph }) => {
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchUsers()
      .then((data) => {
        data.sort((a, b) => b.memory_count - a.memory_count);
        setUsers(data);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load users');
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '4rem' }}>
        <Spinner size="xl" />
      </Flex>
    );
  }

  return (
    <div style={{ padding: '1.5rem', overflow: 'auto', height: '100%' }}>
      {error && (
        <Alert variant="danger" title="Error loading users" isInline style={{ marginBottom: '1rem' }}>
          {error}
        </Alert>
      )}

      <div style={{ marginBottom: '1rem' }}>
        <Title headingLevel="h2" size="lg">Users &amp; Agents</Title>
        <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', marginTop: '0.25rem' }}>
          Registered OAuth clients and memory owners. Click &quot;View Memories&quot; to see an owner&apos;s memories in the graph.
        </Content>
      </div>

      <div style={{ overflowX: 'auto' }}>
      <Table aria-label="Users and agents" variant="compact">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Type</Th>
            <Th>Owner ID</Th>
            <Th modifier="nowrap">Memories</Th>
            <Th modifier="nowrap">Last Active</Th>
            <Th />
          </Tr>
        </Thead>
        <Tbody>
          {users.length === 0 ? (
            <Tr>
              <Td colSpan={6}>
                <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', textAlign: 'center', padding: '2rem' }}>
                  No users or agents found.
                </Content>
              </Td>
            </Tr>
          ) : (
            users.map((u) => (
              <Tr
                key={u.owner_id}
                isClickable={!!onNavigateToGraph}
                onRowClick={() => onNavigateToGraph?.(u.owner_id)}
                style={{ cursor: onNavigateToGraph ? 'pointer' : 'default' }}
              >
                <Td dataLabel="Name">{u.name}</Td>
                <Td dataLabel="Type">
                  <Label
                    color={u.identity_type === 'service' ? 'blue' : u.identity_type === 'user' ? 'grey' : 'orange'}
                    isCompact
                  >
                    {u.identity_type}
                  </Label>
                </Td>
                <Td dataLabel="Owner ID"><code>{u.owner_id}</code></Td>
                <Td dataLabel="Memories">{u.memory_count.toLocaleString()}</Td>
                <Td dataLabel="Last Active">
                  {u.last_active ? formatRelativeTime(u.last_active) : 'Never'}
                </Td>
                <Td dataLabel="Action">
                  {onNavigateToGraph && (
                    <Button
                      variant="link"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onNavigateToGraph(u.owner_id);
                      }}
                    >
                      View Memories
                    </Button>
                  )}
                </Td>
              </Tr>
            ))
          )}
        </Tbody>
      </Table>
      </div>
    </div>
  );
};

export default UsersAgents;
