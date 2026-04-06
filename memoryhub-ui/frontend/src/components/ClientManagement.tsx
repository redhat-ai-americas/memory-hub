import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Content,
  Flex,
  FlexItem,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
  TextInput,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { ClientResponse, CreateClientPayload } from '@/types';
import { createClient, fetchClients, rotateClientSecret, updateClient } from '@/api/client';
import { formatDate } from '@/utils/time';
import SecretRevealModal from './SecretRevealModal';

const AVAILABLE_SCOPES = ['memory:read', 'memory:write:user', 'memory:write', 'memory:admin'];

const ClientManagement: React.FC = () => {
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create modal state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [formClientId, setFormClientId] = useState('');
  const [formClientName, setFormClientName] = useState('');
  const [formIdentityType, setFormIdentityType] = useState<'user' | 'service'>('user');
  const [formTenantId, setFormTenantId] = useState('');
  const [formScopes, setFormScopes] = useState<Set<string>>(new Set(['memory:read']));
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Secret reveal modal state
  const [secretModal, setSecretModal] = useState<{ clientId: string; secret: string } | null>(null);

  // Action feedback
  const [actionError, setActionError] = useState<string | null>(null);

  const loadClients = useCallback(async () => {
    try {
      const data = await fetchClients();
      setClients(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load clients');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadClients(); }, [loadClients]);

  const resetForm = () => {
    setFormClientId('');
    setFormClientName('');
    setFormIdentityType('user');
    setFormTenantId('');
    setFormScopes(new Set(['memory:read']));
    setCreateError(null);
  };

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      const payload: CreateClientPayload = {
        client_id: formClientId,
        client_name: formClientName,
        identity_type: formIdentityType,
        tenant_id: formTenantId,
        default_scopes: Array.from(formScopes),
      };
      const result = await createClient(payload);
      setCreateModalOpen(false);
      resetForm();
      setSecretModal({ clientId: result.client_id, secret: result.client_secret });
      await loadClients();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create client');
    } finally {
      setCreating(false);
    }
  };

  const handleToggleActive = async (client: ClientResponse) => {
    setActionError(null);
    try {
      await updateClient(client.client_id, { active: !client.active });
      await loadClients();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update client');
    }
  };

  const handleRotateSecret = async (clientId: string) => {
    setActionError(null);
    try {
      const result = await rotateClientSecret(clientId);
      setSecretModal({ clientId: result.client_id, secret: result.client_secret });
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to rotate secret');
    }
  };

  const toggleScope = (scope: string) => {
    setFormScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  };

  if (loading) {
    return (
      <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '4rem' }}>
        <Spinner size="xl" />
      </Flex>
    );
  }

  return (
    <div style={{ padding: '1.5rem' }}>
      {error && (
        <Alert variant="danger" title="Error loading clients" isInline style={{ marginBottom: '1rem' }}>
          {error}
        </Alert>
      )}
      {actionError && (
        <Alert variant="danger" title="Action failed" isInline isPlain style={{ marginBottom: '1rem' }}>
          {actionError}
        </Alert>
      )}

      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <Title headingLevel="h2" size="lg">Client Management</Title>
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignEnd' }}>
            <Button variant="primary" onClick={() => setCreateModalOpen(true)}>
              Create Client
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <Table aria-label="OAuth clients" variant="compact">
        <Thead>
          <Tr>
            <Th>Client ID</Th>
            <Th>Name</Th>
            <Th>Type</Th>
            <Th>Scopes</Th>
            <Th>Tenant</Th>
            <Th>Status</Th>
            <Th>Created</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {clients.length === 0 ? (
            <Tr>
              <Td colSpan={8}>
                <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', textAlign: 'center', padding: '2rem' }}>
                  No clients registered yet. Click &quot;Create Client&quot; to get started.
                </Content>
              </Td>
            </Tr>
          ) : (
            clients.map((c) => (
              <Tr key={c.client_id}>
                <Td dataLabel="Client ID"><code>{c.client_id}</code></Td>
                <Td dataLabel="Name">{c.client_name}</Td>
                <Td dataLabel="Type">
                  <Label color={c.identity_type === 'service' ? 'blue' : 'grey'} isCompact>
                    {c.identity_type}
                  </Label>
                </Td>
                <Td dataLabel="Scopes">
                  <Content component="small">{c.default_scopes.join(', ')}</Content>
                </Td>
                <Td dataLabel="Tenant">{c.tenant_id}</Td>
                <Td dataLabel="Status">
                  <Label color={c.active ? 'green' : 'red'} isCompact>
                    {c.active ? 'Active' : 'Inactive'}
                  </Label>
                </Td>
                <Td dataLabel="Created">{formatDate(c.created_at)}</Td>
                <Td dataLabel="Actions">
                  <Flex gap={{ default: 'gapSm' }}>
                    <FlexItem>
                      <Button variant="secondary" size="sm" onClick={() => handleToggleActive(c)}>
                        {c.active ? 'Deactivate' : 'Activate'}
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <Button variant="warning" size="sm" onClick={() => handleRotateSecret(c.client_id)}>
                        Rotate Secret
                      </Button>
                    </FlexItem>
                  </Flex>
                </Td>
              </Tr>
            ))
          )}
        </Tbody>
      </Table>

      {/* Create Client Modal */}
      <Modal
        isOpen={createModalOpen}
        onClose={() => { setCreateModalOpen(false); resetForm(); }}
        variant="medium"
        aria-label="Create client"
      >
        <ModalHeader title="Create OAuth Client" />
        <ModalBody>
          {createError && (
            <Alert variant="danger" isInline isPlain title={createError} style={{ marginBottom: '1rem' }} />
          )}
          <Form>
            <FormGroup label="Client ID" isRequired fieldId="client-id">
              <TextInput id="client-id" value={formClientId} onChange={(_e, val) => setFormClientId(val)} placeholder="e.g. prod-curator-agent" />
            </FormGroup>
            <FormGroup label="Client Name" isRequired fieldId="client-name">
              <TextInput id="client-name" value={formClientName} onChange={(_e, val) => setFormClientName(val)} placeholder="e.g. Production Curator" />
            </FormGroup>
            <FormGroup label="Identity Type" fieldId="identity-type">
              <FormSelect id="identity-type" value={formIdentityType} onChange={(_e, val) => setFormIdentityType(val as 'user' | 'service')}>
                <FormSelectOption value="user" label="User" />
                <FormSelectOption value="service" label="Service" />
              </FormSelect>
            </FormGroup>
            <FormGroup label="Tenant ID" isRequired fieldId="tenant-id">
              <TextInput id="tenant-id" value={formTenantId} onChange={(_e, val) => setFormTenantId(val)} placeholder="e.g. default" />
            </FormGroup>
            <FormGroup label="Scopes" fieldId="scopes">
              {AVAILABLE_SCOPES.map((scope) => (
                <Checkbox
                  key={scope}
                  id={`scope-${scope}`}
                  label={scope}
                  isChecked={formScopes.has(scope)}
                  onChange={() => toggleScope(scope)}
                  style={{ marginBottom: '0.25rem' }}
                />
              ))}
            </FormGroup>
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button
            variant="primary"
            onClick={handleCreate}
            isDisabled={creating || !formClientId || !formClientName || !formTenantId}
            isLoading={creating}
          >
            Create
          </Button>
          <Button variant="link" onClick={() => { setCreateModalOpen(false); resetForm(); }}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Secret Reveal Modal */}
      {secretModal && (
        <SecretRevealModal
          isOpen
          clientId={secretModal.clientId}
          clientSecret={secretModal.secret}
          onClose={() => setSecretModal(null)}
        />
      )}
    </div>
  );
};

export default ClientManagement;
