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
  Button,
  Card,
  CardBody,
  CardTitle,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Tooltip,
} from '@patternfly/react-core';
import { ArrowRightIcon, OutlinedQuestionCircleIcon, TrashIcon } from '@patternfly/react-icons';
import type { MemoryDetail, VersionEntry } from '@/types';
import { fetchMemoryDetail, fetchMemoryHistory, deleteMemory } from '@/api/client';
import ScopeBadge from './ScopeBadge';
import { formatRelativeTime, formatDate } from '@/utils/time';

const EDGE_TYPE_COLORS: Record<string, 'blue' | 'green' | 'red' | 'orange' | 'grey'> = {
  parent_child: 'grey',
  derived_from: 'blue',
  related_to: 'grey',
  conflicts_with: 'red',
  supersedes: 'orange',
};

const EDGE_TYPE_DESCRIPTIONS: Record<string, string> = {
  parent_child: 'Parent → Child: This memory is a branch (rationale, provenance, etc.) of its parent.',
  derived_from: 'Derived From: This memory was created based on information from the other.',
  related_to: 'Related To: These memories cover related topics.',
  conflicts_with: 'Conflicts With: These memories contain contradictory information.',
  supersedes: 'Supersedes: The newer memory replaces or updates the older one.',
};

export interface EdgeInfo {
  sourceId: string;
  targetId: string;
  type: string;
}

interface MemoryDetailDrawerProps {
  isOpen: boolean;
  nodeId: string | null;
  edgeInfo: EdgeInfo | null;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  onDelete?: () => void;
  children?: React.ReactNode;
}

const MemoryDetailDrawer: React.FC<MemoryDetailDrawerProps> = ({
  isOpen, nodeId, edgeInfo, onClose, onSelectNode, onDelete, children,
}) => {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [history, setHistory] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  // Edge view state
  const [sourceDetail, setSourceDetail] = useState<MemoryDetail | null>(null);
  const [targetDetail, setTargetDetail] = useState<MemoryDetail | null>(null);
  const [edgeLoading, setEdgeLoading] = useState(false);
  const [edgeError, setEdgeError] = useState<string | null>(null);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Load node detail
  useEffect(() => {
    if (!nodeId || !isOpen || edgeInfo) {
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
  }, [nodeId, isOpen, edgeInfo]);

  // Load edge details (both endpoints)
  useEffect(() => {
    if (!edgeInfo || !isOpen) {
      setSourceDetail(null);
      setTargetDetail(null);
      setEdgeError(null);
      return;
    }

    setEdgeLoading(true);
    setEdgeError(null);

    Promise.all([fetchMemoryDetail(edgeInfo.sourceId), fetchMemoryDetail(edgeInfo.targetId)])
      .then(([source, target]) => {
        setSourceDetail(source);
        setTargetDetail(target);
      })
      .catch((err: unknown) => {
        setEdgeError(err instanceof Error ? err.message : 'Failed to load relationship details');
      })
      .finally(() => setEdgeLoading(false));
  }, [edgeInfo, isOpen]);

  const handleDelete = async () => {
    if (!nodeId) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteMemory(nodeId);
      setDeleteModalOpen(false);
      setDetail(null);
      onClose();
      onDelete?.();
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete memory');
    } finally {
      setDeleting(false);
    }
  };

  const renderEdgePanel = () => {
    if (!edgeInfo) return null;
    const edgeColor = EDGE_TYPE_COLORS[edgeInfo.type] ?? 'grey';
    const edgeDesc = EDGE_TYPE_DESCRIPTIONS[edgeInfo.type] ?? edgeInfo.type;

    return (
      <>
        {edgeLoading && (
          <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '2rem' }}>
            <Spinner size="lg" />
          </Flex>
        )}

        {edgeError && (
          <Alert variant="danger" title="Failed to load relationship" isInline>
            {edgeError}
          </Alert>
        )}

        {sourceDetail && targetDetail && !edgeLoading && (
          <Stack hasGutter>
            <StackItem>
              <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                <FlexItem>
                  <Label color={edgeColor}>{edgeInfo.type.replace(/_/g, ' ')}</Label>
                </FlexItem>
              </Flex>
              <Content component="small" style={{ marginTop: '0.5rem', color: 'var(--pf-v6-global--Color--200)' }}>
                {edgeDesc}
              </Content>
            </StackItem>

            <Divider />

            <StackItem>
              <Content><h3>Source</h3></Content>
              <Card isCompact isClickable style={{ cursor: 'pointer' }}>
                <CardTitle>
                  <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                    <FlexItem grow={{ default: 'grow' }}>
                      <Button
                        variant="link"
                        isInline
                        onClick={() => onSelectNode(sourceDetail.id)}
                        style={{ textAlign: 'left', fontWeight: 600 }}
                      >
                        {sourceDetail.stub}
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <ScopeBadge scope={sourceDetail.scope} />
                    </FlexItem>
                  </Flex>
                </CardTitle>
                <CardBody>
                  <p style={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.85rem',
                    maxHeight: '120px',
                    overflow: 'hidden',
                    color: 'var(--pf-v6-global--Color--200)',
                  }}>
                    {sourceDetail.content}
                  </p>
                  <DescriptionList isCompact isHorizontal style={{ marginTop: '0.5rem' }}>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Owner</DescriptionListTerm>
                      <DescriptionListDescription>{sourceDetail.owner_id}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Weight</DescriptionListTerm>
                      <DescriptionListDescription>{sourceDetail.weight.toFixed(2)}</DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </CardBody>
              </Card>
            </StackItem>

            <StackItem>
              <Flex justifyContent={{ default: 'justifyContentCenter' }}>
                <ArrowRightIcon style={{ transform: 'rotate(90deg)', color: 'var(--pf-v6-global--Color--200)' }} />
              </Flex>
            </StackItem>

            <StackItem>
              <Content><h3>Target</h3></Content>
              <Card isCompact isClickable style={{ cursor: 'pointer' }}>
                <CardTitle>
                  <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                    <FlexItem grow={{ default: 'grow' }}>
                      <Button
                        variant="link"
                        isInline
                        onClick={() => onSelectNode(targetDetail.id)}
                        style={{ textAlign: 'left', fontWeight: 600 }}
                      >
                        {targetDetail.stub}
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <ScopeBadge scope={targetDetail.scope} />
                    </FlexItem>
                  </Flex>
                </CardTitle>
                <CardBody>
                  <p style={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.85rem',
                    maxHeight: '120px',
                    overflow: 'hidden',
                    color: 'var(--pf-v6-global--Color--200)',
                  }}>
                    {targetDetail.content}
                  </p>
                  <DescriptionList isCompact isHorizontal style={{ marginTop: '0.5rem' }}>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Owner</DescriptionListTerm>
                      <DescriptionListDescription>{targetDetail.owner_id}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Weight</DescriptionListTerm>
                      <DescriptionListDescription>{targetDetail.weight.toFixed(2)}</DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </CardBody>
              </Card>
            </StackItem>
          </Stack>
        )}
      </>
    );
  };

  const renderNodePanel = () => (
    <>
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
                <DescriptionListTerm>
                  Weight{' '}
                  <Tooltip
                    content="Controls injection priority (0.0–1.0), not relevance. High-weight memories get full content injected; low-weight ones arrive as stubs the agent can expand on demand. Typical: 1.0 = policy, 0.9 = strong preference, 0.7 = default."
                  >
                    <OutlinedQuestionCircleIcon style={{ color: 'var(--pf-v6-global--Color--200)', cursor: 'help' }} />
                  </Tooltip>
                </DescriptionListTerm>
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
                            <Button variant="link" isInline size="sm" onClick={() => onSelectNode(otherId)}>
                              {otherId.slice(0, 8)}...
                            </Button>
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
    </>
  );

  const panelTitle = edgeInfo
    ? `${edgeInfo.type.replace(/_/g, ' ')} relationship`
    : detail?.stub ?? '';

  const panelContent = (
    <DrawerPanelContent widths={{ default: 'width_33' }}>
      <DrawerHead>
        <Stack hasGutter>
          <StackItem>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
              <FlexItem>
                <Title headingLevel="h2" size="lg">
                  {edgeInfo ? 'Relationship' : panelTitle}
                </Title>
              </FlexItem>
              {detail && !edgeInfo && (
                <FlexItem>
                  <ScopeBadge scope={detail.scope} />
                </FlexItem>
              )}
              {detail && !detail.is_current && !edgeInfo && (
                <FlexItem>
                  <Label color="orange" isCompact>archived</Label>
                </FlexItem>
              )}
            </Flex>
          </StackItem>
        </Stack>
        <DrawerActions>
          {detail && !edgeInfo && (
            <Button
              variant="danger"
              size="sm"
              icon={<TrashIcon />}
              onClick={() => setDeleteModalOpen(true)}
            >
              Delete
            </Button>
          )}
          <DrawerCloseButton onClick={onClose} />
        </DrawerActions>
      </DrawerHead>

      <div style={{ padding: '0 1.5rem 1.5rem' }}>
        {edgeInfo ? renderEdgePanel() : renderNodePanel()}
      </div>
    </DrawerPanelContent>
  );

  const deleteModal = (
    <Modal
      variant="small"
      isOpen={deleteModalOpen}
      onClose={() => setDeleteModalOpen(false)}
      aria-label="Confirm delete"
    >
      <ModalHeader title="Delete memory?" />
      <ModalBody>
        <Stack hasGutter>
          <StackItem>
            This will soft-delete this memory and all versions in its chain.
            Deleted memories are excluded from search and graph views.
          </StackItem>
          {detail && (
            <StackItem>
              <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                {detail.stub}
              </Content>
            </StackItem>
          )}
          {deleteError && (
            <StackItem>
              <Alert variant="danger" title="Delete failed" isInline>
                {deleteError}
              </Alert>
            </StackItem>
          )}
        </Stack>
      </ModalBody>
      <ModalFooter>
        <Button
          variant="danger"
          onClick={handleDelete}
          isLoading={deleting}
          isDisabled={deleting}
        >
          Delete
        </Button>
        <Button variant="link" onClick={() => setDeleteModalOpen(false)} isDisabled={deleting}>
          Cancel
        </Button>
      </ModalFooter>
    </Modal>
  );

  return (
    <>
      {deleteModal}
      <Drawer isExpanded={isOpen} position="right" style={{ height: '100%' }}>
        <DrawerContent panelContent={panelContent} style={{ height: '100%' }}>
          {children}
        </DrawerContent>
      </Drawer>
    </>
  );
};

export default MemoryDetailDrawer;
