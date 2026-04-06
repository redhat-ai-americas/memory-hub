import React, { useCallback, useEffect, useRef, useState } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import {
  Alert,
  Button,
  Checkbox,
  Flex,
  FlexItem,
  Spinner,
  TextInput,
  Toolbar,
  ToolbarContent,
  ToolbarGroup,
  ToolbarItem,
} from '@patternfly/react-core';
import { SearchIcon } from '@patternfly/react-icons';
import type { GraphResponse, SearchMatch } from '@/types';
import { fetchGraph, searchGraph } from '@/api/client';
import MemoryDetailDrawer from './MemoryDetailDrawer';
import type { EdgeInfo } from './MemoryDetailDrawer';
import { SCOPE_COLORS, SCOPE_OPTIONS } from '@/utils/scopes';

try {
  cytoscape.use(fcose);
} catch {
  // Already registered (HMR reload)
}

function buildElements(data: GraphResponse): cytoscape.ElementDefinition[] {
  const nodes: cytoscape.ElementDefinition[] = data.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.stub.length > 60 ? n.stub.slice(0, 57) + '…' : n.stub,
      scope: n.scope,
      weight: n.weight,
      branch_type: n.branch_type,
      owner_id: n.owner_id,
    },
  }));

  const nodeIds = new Set(data.nodes.map((n) => n.id));
  const edges: cytoscape.ElementDefinition[] = data.edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
      },
    }));

  return [...nodes, ...edges];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildStylesheet(): any[] {
  return [
    {
      selector: 'node',
      style: {
        'background-color': (ele: cytoscape.NodeSingular) =>
          SCOPE_COLORS[ele.data('scope') as string] ?? '#6A6E73',
        width: (ele: cytoscape.NodeSingular) => {
          const w = (ele.data('weight') as number) ?? 0.5;
          return 20 + w * 30;
        },
        height: (ele: cytoscape.NodeSingular) => {
          const w = (ele.data('weight') as number) ?? 0.5;
          return 20 + w * 30;
        },
        label: 'data(label)',
        'font-size': '10px',
        color: '#151515',
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 4,
        'text-max-width': '120px',
        'text-wrap': 'ellipsis',
        'border-width': 2,
        'border-color': '#ffffff',
      },
    },
    {
      selector: 'node.highlighted',
      style: {
        'border-width': 4,
        'border-color': '#F0AB00',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 4,
        'border-color': '#151515',
      },
    },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'overlay-padding': '8px',
      },
    },
    {
      selector: 'edge:selected',
      style: {
        'line-color': '#F0AB00',
        'target-arrow-color': '#F0AB00',
        width: 3,
      },
    },
    {
      selector: 'edge[type = "parent_child"]',
      style: {
        'line-color': '#6A6E73',
        'line-style': 'solid',
        'target-arrow-color': '#6A6E73',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        width: 1.5,
      },
    },
    {
      selector: 'edge[type = "derived_from"]',
      style: {
        'line-color': '#0066CC',
        'line-style': 'dashed',
        'target-arrow-color': '#0066CC',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        width: 1.5,
      },
    },
    {
      selector: 'edge[type = "related_to"]',
      style: {
        'line-color': '#B8BBBE',
        'line-style': 'dotted',
        width: 1,
      },
    },
    {
      selector: 'edge[type = "conflicts_with"]',
      style: {
        'line-color': '#C9190B',
        'line-style': 'solid',
        'target-arrow-color': '#C9190B',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        width: 2,
      },
    },
    {
      selector: 'edge[type = "supersedes"]',
      style: {
        'line-color': '#EC7A08',
        'line-style': 'dashed',
        'target-arrow-color': '#EC7A08',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        width: 1.5,
      },
    },
  ];
}

const STYLESHEET = buildStylesheet();

interface MemoryGraphProps {
  initialOwnerFilter?: string;
}

const MemoryGraph: React.FC<MemoryGraphProps> = ({ initialOwnerFilter }) => {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchMatch[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [enabledScopes, setEnabledScopes] = useState<Set<string>>(new Set(SCOPE_OPTIONS));
  const [ownerFilter, setOwnerFilter] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<EdgeInfo | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Apply initial owner filter from navigation (e.g. Users & Agents panel)
  useEffect(() => {
    if (initialOwnerFilter !== undefined) {
      setOwnerFilter(initialOwnerFilter);
    }
  }, [initialOwnerFilter]);

  const [graphHeight, setGraphHeight] = useState(600);
  const [needsLayout, setNeedsLayout] = useState(true);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);

  // Measure the graph container and set an explicit pixel height for cytoscape
  useEffect(() => {
    const container = graphContainerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const h = entry.contentRect.height;
        if (h > 0) setGraphHeight(h);
      }
    });
    observer.observe(container);
    // Initial measurement
    const h = container.getBoundingClientRect().height;
    if (h > 0) setGraphHeight(h);

    return () => observer.disconnect();
  }, []);

  // Register cy event listeners once, using a polling check for cy availability
  useEffect(() => {
    const interval = setInterval(() => {
      const cy = cyRef.current;
      if (!cy) return;
      clearInterval(interval);

      const onNodeTap = (evt: cytoscape.EventObject) => {
        const node = evt.target as cytoscape.NodeSingular;
        setSelectedEdge(null);
        setSelectedNodeId(node.id());
        setDrawerOpen(true);
      };
      const onEdgeTap = (evt: cytoscape.EventObject) => {
        const edge = evt.target as cytoscape.EdgeSingular;
        setSelectedNodeId(null);
        setSelectedEdge({
          sourceId: edge.source().id(),
          targetId: edge.target().id(),
          type: edge.data('type') as string,
        });
        setDrawerOpen(true);
      };
      const onBgTap = (evt: cytoscape.EventObject) => {
        if (evt.target === cy) {
          setDrawerOpen(false);
          setSelectedNodeId(null);
          setSelectedEdge(null);
        }
      };

      cy.on('tap', 'node', onNodeTap);
      cy.on('tap', 'edge', onEdgeTap);
      cy.on('tap', onBgTap);
    }, 100);

    return () => clearInterval(interval);
  }, []);

  const loadGraph = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchGraph()
      .then((data) => setGraphData(data))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load graph data');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const handleSearch = useCallback(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      cyRef.current?.nodes().removeClass('highlighted');
      return;
    }
    setSearchError(null);
    searchGraph(searchQuery.trim())
      .then((matches) => {
        setSearchResults(matches);
        const cy = cyRef.current;
        if (!cy) return;
        cy.nodes().removeClass('highlighted');
        const matchIds = new Set(matches.map((m) => m.id));
        cy.nodes().forEach((node) => {
          if (matchIds.has(node.id())) {
            node.addClass('highlighted');
          }
        });
      })
      .catch((err: unknown) => {
        setSearchError(err instanceof Error ? err.message : 'Search failed');
      });
  }, [searchQuery]);

  const filteredElements = React.useMemo(() => {
    if (!graphData) return [];
    const filtered: GraphResponse = {
      nodes: graphData.nodes.filter((n) => {
        if (!enabledScopes.has(n.scope)) return false;
        if (ownerFilter && !n.owner_id.includes(ownerFilter)) return false;
        return true;
      }),
      edges: graphData.edges,
    };
    setNeedsLayout(true);
    return buildElements(filtered);
  }, [graphData, enabledScopes, ownerFilter]);

  const toggleScope = (scope: string) => {
    setEnabledScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) {
        next.delete(scope);
      } else {
        next.add(scope);
      }
      return next;
    });
  };

  const containerStyle: React.CSSProperties = {
    width: '100%',
    height: `${graphHeight}px`,
    backgroundImage:
      'radial-gradient(circle, #d0d0d0 1px, transparent 1px)',
    backgroundSize: '20px 20px',
    backgroundColor: '#fafafa',
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 76px)',
    }}>
      <Toolbar style={{ borderBottom: '1px solid var(--pf-v6-global--BorderColor--100)', flexShrink: 0 }}>
        <ToolbarContent>
          <ToolbarItem>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
              <FlexItem>
                <TextInput
                  value={searchQuery}
                  onChange={(_e, val) => setSearchQuery(val)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="Search memories…"
                  style={{ width: '240px' }}
                  aria-label="Search memories"
                />
              </FlexItem>
              <FlexItem>
                <Button variant="control" onClick={handleSearch} aria-label="Submit search">
                  <SearchIcon />
                </Button>
              </FlexItem>
              {searchResults !== null && (
                <FlexItem>
                  <Button
                    variant="link"
                    onClick={() => {
                      setSearchResults(null);
                      setSearchQuery('');
                      cyRef.current?.nodes().removeClass('highlighted');
                    }}
                  >
                    Clear ({searchResults.length} found)
                  </Button>
                </FlexItem>
              )}
            </Flex>
          </ToolbarItem>

          <ToolbarGroup variant="filter-group">
            {SCOPE_OPTIONS.map((scope) => (
              <ToolbarItem key={scope}>
                <Checkbox
                  id={`scope-${scope}`}
                  label={scope}
                  isChecked={enabledScopes.has(scope)}
                  onChange={(_event: React.FormEvent<HTMLInputElement>, _checked: boolean) => toggleScope(scope)}
                />
              </ToolbarItem>
            ))}
          </ToolbarGroup>

          <ToolbarItem>
            <TextInput
              value={ownerFilter}
              onChange={(_e, val) => setOwnerFilter(val)}
              placeholder="Filter by owner…"
              style={{ width: '180px' }}
              aria-label="Filter by owner"
            />
          </ToolbarItem>

          <ToolbarItem>
            <Button variant="secondary" onClick={loadGraph} isDisabled={loading}>
              Refresh
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      {searchError && (
        <Alert variant="warning" title="Search error" isInline isPlain>
          {searchError}
        </Alert>
      )}

      <div
        ref={graphContainerRef}
        style={{ flex: 1, position: 'relative', overflow: 'hidden', minHeight: 0 }}
      >
        {loading && (
          <Flex
            justifyContent={{ default: 'justifyContentCenter' }}
            alignItems={{ default: 'alignItemsCenter' }}
            style={{ height: '100%' }}
          >
            <Spinner size="xl" />
          </Flex>
        )}

        {error && !loading && (
          <div style={{ padding: '1rem' }}>
            <Alert variant="danger" title="Failed to load graph" isInline>
              {error}
            </Alert>
          </div>
        )}

        {!loading && !error && graphData && (
          <MemoryDetailDrawer
            isOpen={drawerOpen}
            nodeId={selectedNodeId}
            edgeInfo={selectedEdge}
            onClose={() => {
              setDrawerOpen(false);
              setSelectedNodeId(null);
              setSelectedEdge(null);
            }}
            onSelectNode={(id) => {
              setSelectedEdge(null);
              setSelectedNodeId(id);
            }}
            onDelete={() => {
              setDrawerOpen(false);
              setSelectedNodeId(null);
              loadGraph();
            }}
          >
            {graphData.nodes.length === 0 ? (
              <Flex
                justifyContent={{ default: 'justifyContentCenter' }}
                alignItems={{ default: 'alignItemsCenter' }}
                style={{ height: '100%' }}
              >
                <Alert variant="info" title="No memories found" isInline>
                  The graph is empty. Start writing memories via the MemoryHub MCP server.
                </Alert>
              </Flex>
            ) : (
              <CytoscapeComponent
                elements={filteredElements}
                style={containerStyle}
                stylesheet={STYLESHEET}
                layout={needsLayout ? {
                  name: 'fcose',
                  animate: true,
                  animationDuration: 500,
                  randomize: true,
                  quality: 'default',
                  nodeSeparation: 120,
                  idealEdgeLength: 100,
                  nodeRepulsion: 8000,
                  edgeElasticity: 0.45,
                  gravity: 0.25,
                  gravityRange: 3.8,
                  numIter: 2500,
                } as cytoscape.LayoutOptions : { name: 'preset' } as cytoscape.LayoutOptions}
                cy={(cy: cytoscape.Core) => {
                  cyRef.current = cy;
                  if (needsLayout) setNeedsLayout(false);
                }}
              />
            )}
          </MemoryDetailDrawer>
        )}
      </div>
    </div>
  );
};

export default MemoryGraph;
