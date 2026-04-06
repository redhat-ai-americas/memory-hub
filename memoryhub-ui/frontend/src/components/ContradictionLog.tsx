import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Content,
  EmptyState,
  EmptyStateBody,
  Flex,
  FlexItem,
  Label,
  Spinner,
  Title,
  ToggleGroup,
  ToggleGroupItem,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { CheckCircleIcon } from '@patternfly/react-icons';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { ContradictionReport, ContradictionStats } from '@/types';
import {
  fetchContradictions,
  fetchContradictionStats,
  updateContradiction,
} from '@/api/client';
import { formatDate } from '@/utils/time';

interface ContradictionLogProps {
  onNavigateToMemory?: (memoryId: string) => void;
}

type ResolutionFilter = 'all' | 'unresolved' | 'resolved';
type ConfidenceFilter = 'all' | 'high' | 'medium' | 'low';

function confidenceColor(c: number): 'green' | 'yellow' | 'red' {
  if (c > 0.8) return 'red';
  if (c >= 0.5) return 'yellow';
  return 'green';
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '...' : text;
}

const ContradictionLog: React.FC<ContradictionLogProps> = ({ onNavigateToMemory }) => {
  const [reports, setReports] = useState<ContradictionReport[]>([]);
  const [stats, setStats] = useState<ContradictionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(false);

  const [resolutionFilter, setResolutionFilter] = useState<ResolutionFilter>('all');
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>('all');

  const loadData = useCallback(async () => {
    try {
      const params: Parameters<typeof fetchContradictions>[0] = {};
      if (resolutionFilter === 'unresolved') params.resolved = false;
      if (resolutionFilter === 'resolved') params.resolved = true;
      if (confidenceFilter === 'high') params.min_confidence = 0.8;
      if (confidenceFilter === 'medium') { params.min_confidence = 0.5; params.max_confidence = 0.8; }
      if (confidenceFilter === 'low') params.max_confidence = 0.5;

      const [data, statsData] = await Promise.all([
        fetchContradictions(Object.keys(params).length > 0 ? params : undefined),
        fetchContradictionStats(),
      ]);
      setReports(data);
      setStats(statsData);
      setIsEmpty(statsData.total === 0);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load contradictions');
    } finally {
      setLoading(false);
    }
  }, [resolutionFilter, confidenceFilter]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleToggleResolved = async (report: ContradictionReport) => {
    setActionError(null);
    try {
      await updateContradiction(report.id, !report.resolved);
      await loadData();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update contradiction');
    }
  };

  if (loading) {
    return (
      <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '4rem' }}>
        <Spinner size="xl" />
      </Flex>
    );
  }

  if (isEmpty) {
    return (
      <div style={{ padding: '1.5rem' }}>
        <EmptyState
          headingLevel="h2"
          icon={CheckCircleIcon}
          titleText="No contradictions reported"
          status="success"
        >
          <EmptyStateBody>
            When agents observe behavior that conflicts with stored memories,
            contradiction reports will appear here.
          </EmptyStateBody>
        </EmptyState>
      </div>
    );
  }

  return (
    <div style={{ padding: '1.5rem', overflow: 'auto', height: '100%' }}>
      {error && (
        <Alert variant="danger" title="Error loading contradictions" isInline style={{ marginBottom: '1rem' }}>
          {error}
        </Alert>
      )}
      {actionError && (
        <Alert variant="danger" title="Action failed" isInline isPlain style={{ marginBottom: '1rem' }}>
          {actionError}
        </Alert>
      )}

      {stats && <StatsBar stats={stats} />}

      <div style={{ marginBottom: '1rem' }}>
        <Title headingLevel="h2" size="lg">Contradiction Log</Title>
        <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', marginTop: '0.25rem' }}>
          Reports from agents that observed behavior conflicting with a stored memory. High contradiction counts may trigger memory revision.
        </Content>
      </div>

      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <ToggleGroup aria-label="Resolution filter">
              {(['all', 'unresolved', 'resolved'] as const).map((v) => (
                <ToggleGroupItem
                  key={v}
                  text={v.charAt(0).toUpperCase() + v.slice(1)}
                  buttonId={`res-${v}`}
                  isSelected={resolutionFilter === v}
                  onChange={() => setResolutionFilter(v)}
                />
              ))}
            </ToggleGroup>
          </ToolbarItem>
          <ToolbarItem>
            <ToggleGroup aria-label="Confidence filter">
              <ToggleGroupItem text="All" buttonId="conf-all" isSelected={confidenceFilter === 'all'} onChange={() => setConfidenceFilter('all')} />
              <ToggleGroupItem text="High >0.8" buttonId="conf-high" isSelected={confidenceFilter === 'high'} onChange={() => setConfidenceFilter('high')} />
              <ToggleGroupItem text="Medium" buttonId="conf-med" isSelected={confidenceFilter === 'medium'} onChange={() => setConfidenceFilter('medium')} />
              <ToggleGroupItem text="Low <0.5" buttonId="conf-low" isSelected={confidenceFilter === 'low'} onChange={() => setConfidenceFilter('low')} />
            </ToggleGroup>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <div style={{ overflowX: 'auto' }}>
        <Table aria-label="Contradiction reports" variant="compact">
          <Thead>
            <Tr>
              <Th>Memory ID</Th>
              <Th>Observed Behavior</Th>
              <Th>Confidence</Th>
              <Th>Reporter</Th>
              <Th>Created</Th>
              <Th>Status</Th>
              <Th>Action</Th>
            </Tr>
          </Thead>
          <Tbody>
            {reports.length === 0 ? (
              <Tr>
                <Td colSpan={7} style={{ textAlign: 'center', padding: '2rem', color: 'var(--pf-v6-global--Color--200)' }}>
                  No contradictions match the current filters.
                </Td>
              </Tr>
            ) : (
              reports.map((r) => (
                <Tr key={r.id}>
                  <Td dataLabel="Memory ID">
                    {onNavigateToMemory ? (
                      <Button variant="link" isInline onClick={() => onNavigateToMemory(r.memory_id)}>
                        <code>{r.memory_id.slice(0, 8)}</code>
                      </Button>
                    ) : (
                      <code>{r.memory_id.slice(0, 8)}</code>
                    )}
                  </Td>
                  <Td dataLabel="Observed Behavior" title={r.observed_behavior}>
                    {truncate(r.observed_behavior, 80)}
                  </Td>
                  <Td dataLabel="Confidence">
                    <Label color={confidenceColor(r.confidence)} isCompact>
                      {r.confidence.toFixed(2)}
                    </Label>
                  </Td>
                  <Td dataLabel="Reporter">{r.reporter}</Td>
                  <Td dataLabel="Created">{formatDate(r.created_at)}</Td>
                  <Td dataLabel="Status">
                    <Label color={r.resolved ? 'green' : 'orange'} isCompact>
                      {r.resolved ? 'Resolved' : 'Unresolved'}
                    </Label>
                  </Td>
                  <Td dataLabel="Action">
                    {r.resolved ? (
                      <Button variant="link" size="sm" onClick={() => handleToggleResolved(r)}>
                        Unresolve
                      </Button>
                    ) : (
                      <Button variant="secondary" size="sm" onClick={() => handleToggleResolved(r)}>
                        Resolve
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

const StatsBar: React.FC<{ stats: ContradictionStats }> = ({ stats }) => (
  <Flex gap={{ default: 'gapMd' }} style={{ marginBottom: '1rem' }}>
    <FlexItem>
      <Label isCompact>Total: {stats.total}</Label>
    </FlexItem>
    <FlexItem>
      <Label color={stats.unresolved > 0 ? 'red' : 'grey'} isCompact>
        Unresolved: {stats.unresolved}
      </Label>
    </FlexItem>
    <FlexItem>
      <Label color="red" isCompact>High: {stats.high_confidence}</Label>
    </FlexItem>
    <FlexItem>
      <Label color="yellow" isCompact>Medium: {stats.medium_confidence}</Label>
    </FlexItem>
  </Flex>
);

export default ContradictionLog;
