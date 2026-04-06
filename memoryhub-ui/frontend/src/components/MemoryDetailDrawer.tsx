import React, { useEffect, useState } from 'react';
import {
  Content,
  Drawer,
  DrawerContent,
  DrawerPanelContent,
  DrawerHead,
  DrawerActions,
  DrawerCloseButton,
  Title,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Spinner,
  Alert,
  ExpandableSection,
  Label,
  Flex,
  FlexItem,
  Divider,
  Stack,
  StackItem,
} from '@patternfly/react-core';
import type { MemoryDetail, VersionEntry } from '@/types';
import { fetchMemoryDetail, fetchMemoryHistory } from '@/api/client';
import ScopeBadge from './ScopeBadge';
import { formatRelativeTime, formatDate } from '@/utils/time';

const EDGE_TYPE_COLORS: Record<string, 'blue' | 'green' | 'red' | 'orange' | 'grey'> = {
  parent_child: 'grey',
  derived_from: 'blue',
  related_to: 'grey',
  conflicts_with: 'red',
  supersedes: 'orange',
};

interface MemoryDetailDrawerProps {
  isOpen: boolean;
  nodeId: string | null;
  onClose: () => void;
  children?: React.ReactNode;
}

const MemoryDetailDrawer: React.FC<MemoryDetailDrawerProps> = ({ isOpen, nodeId, onClose, children }) => {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [history, setHistory] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  useEffect(() => {
    if (!nodeId || !isOpen) {
      setDetail(null);
      setHistory([]);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    Promise.all([fetchMemoryDetail(nodeId), fetchMemoryHistory(nodeId)])
      .then(([detailData, historyData]) => {
        setDetail(detailData);
        setHistory(historyData);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load memory details');
      })
      .finally(() => setLoading(false));
  }, [nodeId, isOpen]);

  const panelContent = (
    <DrawerPanelContent widths={{ default: 'width_33' }}>
      <DrawerHead>
        <Stack hasGutter>
          {detail && (
            <StackItem>
              <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                <FlexItem>
                  <Title headingLevel="h2" size="lg">
                    {detail.stub}
                  </Title>
                </FlexItem>
                <FlexItem>
                  <ScopeBadge scope={detail.scope} />
                </FlexItem>
                {!detail.is_current && (
                  <FlexItem>
                    <Label color="orange" isCompact>
                      archived
                    </Label>
                  </FlexItem>
                )}
              </Flex>
            </StackItem>
          )}
        </Stack>
        <DrawerActions>
          <DrawerCloseButton onClick={onClose} />
        </DrawerActions>
      </DrawerHead>

      <div style={{ padding: '0 1.5rem 1.5rem' }}>
        {loading && (
          <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '2rem' }}>
            <Spinner size="lg" />
          </Flex>
        )}

        {error && (
          <Alert variant="danger" title="Failed to load memory" isInline>
            {error}
          </Alert>
        )}

        {detail && !loading && (
          <Stack hasGutter>
            <StackItem>
              <Content>
                <h3>Content</h3>
                <p
                  style={{
                    whiteSpace: 'pre-wrap',
                    backgroundColor: 'var(--pf-v6-global--BackgroundColor--200)',
                    padding: '0.75rem',
                    borderRadius: '4px',
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }}
                >
                  {detail.content}
                </p>
              </Content>
            </StackItem>

            <Divider />

            <StackItem>
              <Content><h3>Details</h3></Content>
              <DescriptionList isCompact isHorizontal>
                <DescriptionListGroup>
                  <DescriptionListTerm>Owner</DescriptionListTerm>
                  <DescriptionListDescription>{detail.owner_id}</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Weight</DescriptionListTerm>
                  <DescriptionListDescription>{detail.weight.toFixed(2)}</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Version</DescriptionListTerm>
                  <DescriptionListDescription>{detail.version}</DescriptionListDescription>
                </DescriptionListGroup>
                {detail.branch_type && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Branch Type</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label isCompact color="blue">
                        {detail.branch_type}
                      </Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                {detail.parent_id && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Parent ID</DescriptionListTerm>
                    <DescriptionListDescription>
                      <code style={{ fontSize: '0.75rem' }}>{detail.parent_id}</code>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                <DescriptionListGroup>
                  <DescriptionListTerm>Children</DescriptionListTerm>
                  <DescriptionListDescription>{detail.children_count}</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Created</DescriptionListTerm>
                  <DescriptionListDescription>{formatDate(detail.created_at)}</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Updated</DescriptionListTerm>
                  <DescriptionListDescription>{formatDate(detail.updated_at)}</DescriptionListDescription>
                </DescriptionListGroup>
                {detail.expires_at && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Expires</DescriptionListTerm>
                    <DescriptionListDescription>{formatDate(detail.expires_at)}</DescriptionListDescription>
                  </DescriptionListGroup>
                )}
              </DescriptionList>
            </StackItem>

            {detail.metadata && Object.keys(detail.metadata).length > 0 && (
              <>
                <Divider />
                <StackItem>
                  <Content><h3>Metadata</h3></Content>
                  <DescriptionList isCompact isHorizontal>
                    {Object.entries(detail.metadata).map(([key, value]) => (
                      <DescriptionListGroup key={key}>
                        <DescriptionListTerm>{key}</DescriptionListTerm>
                        <DescriptionListDescription>
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    ))}
                  </DescriptionList>
                </StackItem>
              </>
            )}

            {detail.relationships.length > 0 && (
              <>
                <Divider />
                <StackItem>
                  <Content><h3>Relationships</h3></Content>
                  <Stack hasGutter>
                    {detail.relationships.map((rel) => {
                      const isSource = rel.source === detail.id;
                      const otherId = isSource ? rel.target : rel.source;
                      const direction = isSource ? '→' : '←';
                      const edgeColor = EDGE_TYPE_COLORS[rel.type] ?? 'grey';
                      return (
                        <StackItem key={rel.id}>
                          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                            <FlexItem>
                              <Label color={edgeColor} isCompact>
                                {rel.type}
                              </Label>
                            </FlexItem>
                            <FlexItem>
                              <Content component="small">{direction}</Content>
                            </FlexItem>
                            <FlexItem>
                              <code style={{ fontSize: '0.75rem' }}>{otherId.slice(0, 8)}...</code>
                            </FlexItem>
                          </Flex>
                        </StackItem>
                      );
                    })}
                  </Stack>
                </StackItem>
              </>
            )}

            {history.length > 0 && (
              <>
                <Divider />
                <StackItem>
                  <ExpandableSection
                    toggleText={`Version History (${history.length})`}
                    isExpanded={historyExpanded}
                    onToggle={(_event: React.MouseEvent, isExpanded: boolean) => setHistoryExpanded(isExpanded)}
                  >
                    <Stack hasGutter>
                      {history.map((entry) => (
                        <StackItem key={entry.id}>
                          <Flex
                            alignItems={{ default: 'alignItemsCenter' }}
                            gap={{ default: 'gapSm' }}
                            style={{
                              padding: '0.5rem',
                              backgroundColor: entry.is_current
                                ? 'var(--pf-v6-global--BackgroundColor--200)'
                                : 'transparent',
                              borderRadius: '4px',
                            }}
                          >
                            <FlexItem>
                              <Label isCompact color={entry.is_current ? 'green' : 'grey'}>
                                v{entry.version}
                              </Label>
                            </FlexItem>
                            <FlexItem grow={{ default: 'grow' }}>
                              <Content component="small">{entry.stub}</Content>
                            </FlexItem>
                            <FlexItem>
                              <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                                {formatRelativeTime(entry.created_at)}
                              </Content>
                            </FlexItem>
                          </Flex>
                        </StackItem>
                      ))}
                    </Stack>
                  </ExpandableSection>
                </StackItem>
              </>
            )}
          </Stack>
        )}
      </div>
    </DrawerPanelContent>
  );

  return (
    <Drawer isExpanded={isOpen} position="right" style={{ height: '100%' }}>
      <DrawerContent panelContent={panelContent} style={{ height: '100%' }}>
        {children}
      </DrawerContent>
    </Drawer>
  );
};

export default MemoryDetailDrawer;
