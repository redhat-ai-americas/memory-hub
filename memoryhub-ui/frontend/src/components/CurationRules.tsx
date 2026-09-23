import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Content, DescriptionList, DescriptionListDescription,
  DescriptionListGroup, DescriptionListTerm, Divider, ExpandableSection, Flex,
  Form, FormGroup, FormSelect, FormSelectOption, Label, Modal, ModalBody,
  ModalFooter, ModalHeader, NumberInput, Radio, Spinner, Stack, StackItem,
  Switch, TextArea, TextInput, Title, ToggleGroup, ToggleGroupItem, Toolbar,
  ToolbarContent, ToolbarItem,
} from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { CurationRule, CreateRulePayload, RuleVersionEntry } from '@/types';
import { createRule, deleteRule, fetchRuleHistory, fetchRules, updateRule } from '@/api/client';
import { formatDate } from '@/utils/time';

const ACTION_COLORS: Record<string, 'red' | 'orange' | 'yellow' | 'blue' | 'grey'> = {
  block: 'red', quarantine: 'orange', flag: 'yellow',
  reject_with_pointer: 'red', merge: 'blue', decay_weight: 'grey',
};

const ACTION_OPTIONS = ['block', 'quarantine', 'flag', 'reject_with_pointer', 'merge', 'decay_weight'];
const TRIGGER_OPTIONS = ['on_write', 'on_read', 'periodic', 'on_contradiction_count'];
const LAYER_OPTIONS = ['system', 'organizational', 'user'];

// --- Human-readable rule summary ---

const TRIGGER_TEXT: Record<string, string> = {
  on_write: 'When a memory is written',
  on_read: 'When a memory is read',
  periodic: 'Periodically',
  on_contradiction_count: 'When contradiction count threshold is reached',
};

const TIER_TEXT: Record<string, string> = {
  regex: 'scan using regex patterns',
  embedding: 'compare using embedding similarity',
};

const ACTION_TEXT: Record<string, string> = {
  block: 'block it',
  quarantine: 'quarantine it',
  flag: 'flag it for review',
  reject_with_pointer: 'reject it and point to the existing memory',
  merge: 'merge it with the existing memory',
  decay_weight: 'reduce its weight',
};

function describeRule(rule: CurationRule): string {
  const trigger = TRIGGER_TEXT[rule.trigger] ?? rule.trigger;
  const tier = TIER_TEXT[rule.tier] ?? rule.tier;
  const action = ACTION_TEXT[rule.action] ?? rule.action;
  return `${trigger}, ${tier}. If matched, ${action}.`;
}

const PATTERN_SET_DESCRIPTIONS: Record<string, string> = {
  secrets: 'Scans for AWS access keys, GitHub tokens, API keys (sk-...), private key headers, bearer tokens, and password/secret assignments.',
  pii: 'Scans for Social Security numbers (XXX-XX-XXXX), email addresses, and US phone numbers.',
};

function describeConfig(rule: CurationRule): string | null {
  const config = rule.config;
  if (!config || Object.keys(config).length === 0) return null;

  if (rule.tier === 'regex' && 'pattern_set' in config) {
    return PATTERN_SET_DESCRIPTIONS[config.pattern_set as string] ?? null;
  }
  if (rule.tier === 'embedding' && 'threshold' in config) {
    return `Blocks memories with cosine similarity above ${(config.threshold as number) * 100}% to an existing memory.`;
  }
  if (rule.tier === 'embedding' && 'similarity_range' in config) {
    const range = config.similarity_range as number[];
    return `Flags memories with cosine similarity between ${range[0] * 100}% and ${range[1] * 100}% to an existing memory.`;
  }
  if ('threshold' in config) {
    return `Triggers when count reaches ${config.threshold}.`;
  }
  return null;
}

const EDITOR_IDENTITY = 'dashboard-operator';

const CurationRules: React.FC = () => {
  const [rules, setRules] = useState<CurationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Toolbar filters
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [enabledFilter, setEnabledFilter] = useState<string>('all');

  // Create modal state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formTier, setFormTier] = useState<'regex' | 'embedding'>('regex');
  const [formAction, setFormAction] = useState('block');
  const [formTrigger, setFormTrigger] = useState('on_write');
  const [formScopeFilter, setFormScopeFilter] = useState('');
  const [formLayer, setFormLayer] = useState('system');
  const [formPriority, setFormPriority] = useState(100);
  const [formConfig, setFormConfig] = useState('{}');

  // Detail / edit modal state
  const [selectedRule, setSelectedRule] = useState<CurationRule | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Edit form fields (pre-populated from selectedRule when entering edit mode)
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editTier, setEditTier] = useState<'regex' | 'embedding'>('regex');
  const [editAction, setEditAction] = useState('block');
  const [editTrigger, setEditTrigger] = useState('on_write');
  const [editScopeFilter, setEditScopeFilter] = useState('');
  const [editLayer, setEditLayer] = useState('system');
  const [editPriority, setEditPriority] = useState(100);
  const [editConfig, setEditConfig] = useState('{}');
  const [editEnabled, setEditEnabled] = useState(true);
  const [editOverride, setEditOverride] = useState(false);

  // Version history state
  const [historyOpen, setHistoryOpen] = useState(false);
  const [ruleHistory, setRuleHistory] = useState<RuleVersionEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<CurationRule | null>(null);

  const loadRules = useCallback(async () => {
    try {
      const params: { tier?: string; enabled?: boolean } = {};
      if (tierFilter !== 'all') params.tier = tierFilter;
      if (enabledFilter === 'enabled') params.enabled = true;
      else if (enabledFilter === 'disabled') params.enabled = false;
      const data = await fetchRules(params);
      setRules(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load rules');
    } finally {
      setLoading(false);
    }
  }, [tierFilter, enabledFilter]);

  useEffect(() => { loadRules(); }, [loadRules]);

  const resetForm = () => {
    setFormName('');
    setFormDescription('');
    setFormTier('regex');
    setFormAction('block');
    setFormTrigger('on_write');
    setFormScopeFilter('');
    setFormLayer('system');
    setFormPriority(100);
    setFormConfig('{}');
    setCreateError(null);
  };

  const openDetailModal = (rule: CurationRule) => {
    setSelectedRule(rule);
    setEditMode(false);
    setSaveError(null);
    setHistoryOpen(false);
    setRuleHistory([]);
    setHistoryError(null);
  };

  const enterEditMode = (rule: CurationRule) => {
    setEditName(rule.name);
    setEditDescription(rule.description ?? '');
    setEditTier(rule.tier);
    setEditAction(rule.action);
    setEditTrigger(rule.trigger);
    setEditScopeFilter(rule.scope_filter ?? '');
    setEditLayer(rule.layer);
    setEditPriority(rule.priority);
    setEditConfig(JSON.stringify(rule.config, null, 2));
    setEditEnabled(rule.enabled);
    setEditOverride(rule.override);
    setSaveError(null);
    setEditMode(true);
  };

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(null);
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = JSON.parse(formConfig);
    } catch {
      setCreateError('Config must be valid JSON');
      setCreating(false);
      return;
    }
    try {
      const payload: CreateRulePayload = {
        name: formName,
        description: formDescription || undefined,
        tier: formTier,
        action: formAction,
        trigger: formTrigger,
        scope_filter: formScopeFilter || undefined,
        layer: formLayer,
        priority: formPriority,
        config: parsedConfig,
      };
      await createRule(payload);
      setCreateModalOpen(false);
      resetForm();
      await loadRules();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create rule');
    } finally {
      setCreating(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!selectedRule) return;
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = JSON.parse(editConfig);
    } catch {
      setSaveError('Config must be valid JSON');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateRule(selectedRule.id, {
        name: editName,
        description: editDescription !== '' ? editDescription : null,
        tier: editTier,
        action: editAction,
        trigger: editTrigger,
        scope_filter: editScopeFilter !== '' ? editScopeFilter : null,
        layer: editLayer,
        priority: editPriority,
        config: parsedConfig,
        enabled: editEnabled,
        override: editOverride,
        edited_by: EDITOR_IDENTITY,
      });
      setSelectedRule(updated);
      setEditMode(false);
      setHistoryOpen(false);
      setRuleHistory([]);
      await loadRules();
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save rule');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (rule: CurationRule) => {
    setActionError(null);
    try {
      const updated = await updateRule(rule.id, { enabled: !rule.enabled, edited_by: EDITOR_IDENTITY });
      if (selectedRule?.id === rule.id) {
        setSelectedRule(updated);
        setRuleHistory([]);
      }
      await loadRules();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to toggle rule');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await deleteRule(deleteTarget.id);
      setDeleteTarget(null);
      await loadRules();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete rule');
      setDeleteTarget(null);
    }
  };

  const handleHistoryToggle = async (isExpanded: boolean) => {
    setHistoryOpen(isExpanded);
    if (isExpanded && selectedRule && ruleHistory.length === 0) {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const history = await fetchRuleHistory(selectedRule.id);
        setRuleHistory(history);
      } catch (err: unknown) {
        setHistoryError(err instanceof Error ? err.message : 'Failed to load history');
      } finally {
        setHistoryLoading(false);
      }
    }
  };

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
        <Alert variant="danger" title="Error loading rules" isInline style={{ marginBottom: '1rem' }}>
          {error}
        </Alert>
      )}
      {actionError && (
        <Alert variant="danger" title="Action failed" isInline isPlain style={{ marginBottom: '1rem' }}>
          {actionError}
        </Alert>
      )}

      <div style={{ marginBottom: '1rem' }}>
        <Title headingLevel="h2" size="lg">Curation Rules</Title>
        <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', marginTop: '0.25rem' }}>
          Server-side guardrails that run automatically when memories are written or read. Agents cannot see or bypass these rules.
        </Content>
      </div>

      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <ToggleGroup aria-label="Tier filter">
              <ToggleGroupItem text="All" buttonId="tier-all" isSelected={tierFilter === 'all'} onChange={() => setTierFilter('all')} />
              <ToggleGroupItem text="Regex" buttonId="tier-regex" isSelected={tierFilter === 'regex'} onChange={() => setTierFilter('regex')} />
              <ToggleGroupItem text="Embedding" buttonId="tier-embed" isSelected={tierFilter === 'embedding'} onChange={() => setTierFilter('embedding')} />
            </ToggleGroup>
          </ToolbarItem>
          <ToolbarItem>
            <ToggleGroup aria-label="Enabled filter">
              <ToggleGroupItem text="All" buttonId="en-all" isSelected={enabledFilter === 'all'} onChange={() => setEnabledFilter('all')} />
              <ToggleGroupItem text="Enabled" buttonId="en-yes" isSelected={enabledFilter === 'enabled'} onChange={() => setEnabledFilter('enabled')} />
              <ToggleGroupItem text="Disabled" buttonId="en-no" isSelected={enabledFilter === 'disabled'} onChange={() => setEnabledFilter('disabled')} />
            </ToggleGroup>
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignEnd' }}>
            <Button variant="primary" onClick={() => setCreateModalOpen(true)}>
              Create Rule
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <div style={{ overflowX: 'auto' }}>
        <Table aria-label="Curation rules" variant="compact">
          <Thead>
            <Tr>
              <Th>Name</Th>
              <Th>Tier</Th>
              <Th>Action</Th>
              <Th>Layer</Th>
              <Th>Priority</Th>
              <Th>Enabled</Th>
              <Th>Actions</Th>
            </Tr>
          </Thead>
          <Tbody>
            {rules.length === 0 ? (
              <Tr>
                <Td colSpan={7}>
                  <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', textAlign: 'center', padding: '2rem' }}>
                    No curation rules found. Click &quot;Create Rule&quot; to add one.
                  </Content>
                </Td>
              </Tr>
            ) : (
              rules.map((rule) => (
                <Tr key={rule.id}>
                  <Td dataLabel="Name">
                    <Button variant="link" isInline onClick={() => openDetailModal(rule)}>
                      {rule.name}
                    </Button>
                  </Td>
                  <Td dataLabel="Tier">
                    <Label color={rule.tier === 'regex' ? 'blue' : 'purple'} isCompact>
                      {rule.tier}
                    </Label>
                  </Td>
                  <Td dataLabel="Action">
                    <Label color={ACTION_COLORS[rule.action] ?? 'grey'} isCompact>
                      {rule.action}
                    </Label>
                  </Td>
                  <Td dataLabel="Layer">{rule.layer}</Td>
                  <Td dataLabel="Priority">{rule.priority}</Td>
                  <Td dataLabel="Enabled">
                    <Switch
                      id={`toggle-${rule.id}`}
                      isChecked={rule.enabled}
                      onChange={() => handleToggleEnabled(rule)}
                      aria-label={`Toggle ${rule.name}`}
                    />
                  </Td>
                  <Td dataLabel="Actions">
                    <Button variant="link" isDanger onClick={() => setDeleteTarget(rule)}>
                      Delete
                    </Button>
                  </Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </div>

      {/* Create Rule Modal */}
      <Modal
        isOpen={createModalOpen}
        onClose={() => { setCreateModalOpen(false); resetForm(); }}
        variant="medium"
        aria-label="Create curation rule"
      >
        <ModalHeader title="Create Curation Rule" />
        <ModalBody>
          {createError && (
            <Alert variant="danger" isInline isPlain title={createError} style={{ marginBottom: '1rem' }} />
          )}
          <Form>
            <FormGroup label="Name" isRequired fieldId="rule-name">
              <TextInput id="rule-name" value={formName} onChange={(_e, val) => setFormName(val)} placeholder="e.g. block-pii-content" />
            </FormGroup>
            <FormGroup label="Description" fieldId="rule-desc">
              <TextInput id="rule-desc" value={formDescription} onChange={(_e, val) => setFormDescription(val)} placeholder="Optional description" />
            </FormGroup>
            <FormGroup label="Tier" isRequired fieldId="rule-tier">
              <Radio id="tier-regex" name="tier" label="Regex" value="regex" isChecked={formTier === 'regex'} onChange={() => setFormTier('regex')} />
              <Radio id="tier-embedding" name="tier" label="Embedding" value="embedding" isChecked={formTier === 'embedding'} onChange={() => setFormTier('embedding')} />
            </FormGroup>
            <FormGroup label="Action" isRequired fieldId="rule-action">
              <FormSelect id="rule-action" value={formAction} onChange={(_e, val) => setFormAction(val)}>
                {ACTION_OPTIONS.map((a) => <FormSelectOption key={a} value={a} label={a} />)}
              </FormSelect>
            </FormGroup>
            <FormGroup label="Trigger" fieldId="rule-trigger">
              <FormSelect id="rule-trigger" value={formTrigger} onChange={(_e, val) => setFormTrigger(val)}>
                {TRIGGER_OPTIONS.map((t) => <FormSelectOption key={t} value={t} label={t} />)}
              </FormSelect>
            </FormGroup>
            <FormGroup label="Scope Filter" fieldId="rule-scope">
              <TextInput id="rule-scope" value={formScopeFilter} onChange={(_e, val) => setFormScopeFilter(val)} placeholder="e.g. user" />
            </FormGroup>
            <FormGroup label="Layer" fieldId="rule-layer">
              <FormSelect id="rule-layer" value={formLayer} onChange={(_e, val) => setFormLayer(val)}>
                {LAYER_OPTIONS.map((l) => <FormSelectOption key={l} value={l} label={l} />)}
              </FormSelect>
            </FormGroup>
            <FormGroup label="Priority" fieldId="rule-priority">
              <NumberInput
                id="rule-priority"
                value={formPriority}
                onMinus={() => setFormPriority((p) => Math.max(0, p - 1))}
                onPlus={() => setFormPriority((p) => p + 1)}
                onChange={(e) => {
                  const val = Number((e.target as HTMLInputElement).value);
                  if (!isNaN(val)) setFormPriority(val);
                }}
                min={0}
              />
            </FormGroup>
            <FormGroup label="Config (JSON)" fieldId="rule-config">
              <TextArea id="rule-config" value={formConfig} onChange={(_e, val) => setFormConfig(val)} rows={3} placeholder='{"pattern": ".*"}' />
            </FormGroup>
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button
            variant="primary"
            onClick={handleCreate}
            isDisabled={creating || !formName}
            isLoading={creating}
          >
            Create
          </Button>
          <Button variant="link" onClick={() => { setCreateModalOpen(false); resetForm(); }}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Rule Detail / Edit Modal */}
      <Modal
        isOpen={selectedRule !== null}
        onClose={() => { setSelectedRule(null); setEditMode(false); }}
        variant="medium"
        aria-label="Rule details"
      >
        <ModalHeader title={selectedRule?.name ?? 'Rule Details'} />
        {selectedRule && (
          <ModalBody>
            {editMode ? (
              /* Edit Form */
              <Stack hasGutter>
                {saveError && (
                  <StackItem>
                    <Alert variant="danger" isInline isPlain title={saveError} />
                  </StackItem>
                )}
                <StackItem>
                  <Form>
                    <FormGroup label="Name" isRequired fieldId="edit-rule-name">
                      <TextInput id="edit-rule-name" value={editName} onChange={(_e, val) => setEditName(val)} />
                    </FormGroup>
                    <FormGroup label="Description" fieldId="edit-rule-desc">
                      <TextInput id="edit-rule-desc" value={editDescription} onChange={(_e, val) => setEditDescription(val)} placeholder="Optional description" />
                    </FormGroup>
                    <FormGroup label="Tier" isRequired fieldId="edit-rule-tier">
                      <Radio id="edit-tier-regex" name="edit-tier" label="Regex" value="regex" isChecked={editTier === 'regex'} onChange={() => setEditTier('regex')} />
                      <Radio id="edit-tier-embedding" name="edit-tier" label="Embedding" value="embedding" isChecked={editTier === 'embedding'} onChange={() => setEditTier('embedding')} />
                    </FormGroup>
                    <FormGroup label="Action" isRequired fieldId="edit-rule-action">
                      <FormSelect id="edit-rule-action" value={editAction} onChange={(_e, val) => setEditAction(val)}>
                        {ACTION_OPTIONS.map((a) => <FormSelectOption key={a} value={a} label={a} />)}
                      </FormSelect>
                    </FormGroup>
                    <FormGroup label="Trigger" fieldId="edit-rule-trigger">
                      <FormSelect id="edit-rule-trigger" value={editTrigger} onChange={(_e, val) => setEditTrigger(val)}>
                        {TRIGGER_OPTIONS.map((t) => <FormSelectOption key={t} value={t} label={t} />)}
                      </FormSelect>
                    </FormGroup>
                    <FormGroup label="Scope Filter" fieldId="edit-rule-scope">
                      <TextInput id="edit-rule-scope" value={editScopeFilter} onChange={(_e, val) => setEditScopeFilter(val)} placeholder="e.g. user" />
                    </FormGroup>
                    <FormGroup label="Layer" fieldId="edit-rule-layer">
                      <FormSelect id="edit-rule-layer" value={editLayer} onChange={(_e, val) => setEditLayer(val)}>
                        {LAYER_OPTIONS.map((l) => <FormSelectOption key={l} value={l} label={l} />)}
                      </FormSelect>
                    </FormGroup>
                    <FormGroup label="Priority" fieldId="edit-rule-priority">
                      <NumberInput
                        id="edit-rule-priority"
                        value={editPriority}
                        onMinus={() => setEditPriority((p) => Math.max(0, p - 1))}
                        onPlus={() => setEditPriority((p) => p + 1)}
                        onChange={(e) => {
                          const val = Number((e.target as HTMLInputElement).value);
                          if (!isNaN(val)) setEditPriority(val);
                        }}
                        min={0}
                      />
                    </FormGroup>
                    <FormGroup label="Config (JSON)" fieldId="edit-rule-config">
                      <TextArea id="edit-rule-config" value={editConfig} onChange={(_e, val) => setEditConfig(val)} rows={4} />
                    </FormGroup>
                    <FormGroup label="Enabled" fieldId="edit-rule-enabled">
                      <Switch
                        id="edit-rule-enabled"
                        isChecked={editEnabled}
                        onChange={(_e, checked) => setEditEnabled(checked)}
                        label="Enabled"
                        labelOff="Disabled"
                      />
                    </FormGroup>
                    <FormGroup label="Override" fieldId="edit-rule-override">
                      <Switch
                        id="edit-rule-override"
                        isChecked={editOverride}
                        onChange={(_e, checked) => setEditOverride(checked)}
                        label="Can override higher-layer rules"
                        labelOff="Cannot override"
                      />
                    </FormGroup>
                  </Form>
                </StackItem>
              </Stack>
            ) : (
              /* Read-only Detail View */
              <Stack hasGutter>
                {/* What this rule does — auto-generated summary */}
                <StackItem>
                  <Content component="p" style={{
                    backgroundColor: 'var(--pf-v6-global--BackgroundColor--200)',
                    padding: '0.75rem 1rem',
                    borderRadius: '4px',
                    borderLeft: '3px solid var(--pf-v6-global--primary-color--100)',
                    fontStyle: 'italic',
                  }}>
                    {describeRule(selectedRule)}
                  </Content>
                </StackItem>

                {/* Description */}
                {selectedRule.description && (
                  <StackItem>
                    <DescriptionList isCompact isHorizontal>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Description</DescriptionListTerm>
                        <DescriptionListDescription>{selectedRule.description}</DescriptionListDescription>
                      </DescriptionListGroup>
                    </DescriptionList>
                  </StackItem>
                )}

                <Divider />

                {/* Behavior */}
                <StackItem>
                  <Content><h4>Behavior</h4></Content>
                  <DescriptionList isCompact isHorizontal>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Trigger</DescriptionListTerm>
                      <DescriptionListDescription>{selectedRule.trigger}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Tier</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color={selectedRule.tier === 'regex' ? 'blue' : 'purple'} isCompact>
                          {selectedRule.tier}
                        </Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Action</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color={ACTION_COLORS[selectedRule.action] ?? 'grey'} isCompact>
                          {selectedRule.action}
                        </Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </StackItem>

                {/* Config */}
                <StackItem>
                  <Content><h4>Config</h4></Content>
                  {describeConfig(selectedRule) && (
                    <Content component="p" style={{ marginBottom: '0.5rem', color: 'var(--pf-v6-global--Color--200)' }}>
                      {describeConfig(selectedRule)}
                    </Content>
                  )}
                  <pre style={{
                    backgroundColor: 'var(--pf-v6-global--BackgroundColor--200)',
                    padding: '0.75rem',
                    borderRadius: '4px',
                    fontSize: '0.875rem',
                    overflow: 'auto',
                    maxHeight: '200px',
                    margin: 0,
                  }}>
                    {JSON.stringify(selectedRule.config, null, 2)}
                  </pre>
                </StackItem>

                <Divider />

                {/* Scope */}
                <StackItem>
                  <Content><h4>Scope</h4></Content>
                  <DescriptionList isCompact isHorizontal>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Layer</DescriptionListTerm>
                      <DescriptionListDescription>{selectedRule.layer}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Scope Filter</DescriptionListTerm>
                      <DescriptionListDescription>{selectedRule.scope_filter ?? 'All scopes'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Owner</DescriptionListTerm>
                      <DescriptionListDescription>{selectedRule.owner_id ?? 'None (system)'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Override</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color={selectedRule.override ? 'orange' : 'grey'} isCompact>
                          {selectedRule.override ? 'Yes' : 'No'}
                        </Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </StackItem>

                <Divider />

                {/* Status */}
                <StackItem>
                  <Content><h4>Status</h4></Content>
                  <DescriptionList isCompact isHorizontal>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Enabled</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color={selectedRule.enabled ? 'green' : 'red'} isCompact>
                          {selectedRule.enabled ? 'Enabled' : 'Disabled'}
                        </Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Priority</DescriptionListTerm>
                      <DescriptionListDescription>{selectedRule.priority}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Version</DescriptionListTerm>
                      <DescriptionListDescription>v{selectedRule.version}</DescriptionListDescription>
                    </DescriptionListGroup>
                    {selectedRule.edited_by && (
                      <DescriptionListGroup>
                        <DescriptionListTerm>Last edited by</DescriptionListTerm>
                        <DescriptionListDescription>{selectedRule.edited_by}</DescriptionListDescription>
                      </DescriptionListGroup>
                    )}
                    <DescriptionListGroup>
                      <DescriptionListTerm>Created</DescriptionListTerm>
                      <DescriptionListDescription>{formatDate(selectedRule.created_at)}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Updated</DescriptionListTerm>
                      <DescriptionListDescription>{formatDate(selectedRule.updated_at)}</DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </StackItem>

                <Divider />

                {/* Version History */}
                <StackItem>
                  <ExpandableSection
                    toggleText={historyOpen ? 'Hide version history' : 'Show version history'}
                    onToggle={(_e, isExp) => handleHistoryToggle(isExp)}
                    isExpanded={historyOpen}
                  >
                    {historyLoading && <Spinner size="md" />}
                    {historyError && (
                      <Alert variant="warning" isInline isPlain title={historyError} />
                    )}
                    {!historyLoading && !historyError && ruleHistory.length > 0 && (
                      <Table aria-label="Version history" variant="compact" style={{ marginTop: '0.5rem' }}>
                        <Thead>
                          <Tr>
                            <Th>Version</Th>
                            <Th>Name</Th>
                            <Th>Edited by</Th>
                            <Th>Date</Th>
                            <Th>Status</Th>
                          </Tr>
                        </Thead>
                        <Tbody>
                          {ruleHistory.map((entry) => (
                            <Tr key={entry.id}>
                              <Td>v{entry.version}</Td>
                              <Td>{entry.name}</Td>
                              <Td>{entry.edited_by ?? '—'}</Td>
                              <Td>{formatDate(entry.created_at)}</Td>
                              <Td>
                                {entry.is_current ? (
                                  <Label color="green" isCompact>Current</Label>
                                ) : (
                                  <Label color="grey" isCompact>Superseded</Label>
                                )}
                              </Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    )}
                    {!historyLoading && !historyError && ruleHistory.length === 0 && historyOpen && (
                      <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                        No history available.
                      </Content>
                    )}
                  </ExpandableSection>
                </StackItem>
              </Stack>
            )}
          </ModalBody>
        )}
        <ModalFooter>
          {editMode ? (
            <>
              <Button
                variant="primary"
                onClick={handleSaveEdit}
                isDisabled={saving || !editName}
                isLoading={saving}
              >
                Save
              </Button>
              <Button variant="link" onClick={() => { setEditMode(false); setSaveError(null); }}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={() => selectedRule && enterEditMode(selectedRule)}>
                Edit
              </Button>
              <Button variant="link" onClick={() => { setSelectedRule(null); setEditMode(false); }}>
                Close
              </Button>
            </>
          )}
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        variant="small"
        aria-label="Confirm delete"
      >
        <ModalHeader title="Delete Rule" />
        <ModalBody>
          Are you sure you want to delete rule <strong>{deleteTarget?.name}</strong>? This action cannot be undone.
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={handleDelete}>Delete</Button>
          <Button variant="link" onClick={() => setDeleteTarget(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default CurationRules;
