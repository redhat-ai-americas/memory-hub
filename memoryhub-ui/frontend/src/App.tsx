import React, { useState } from 'react';
import {
  Button,
  Content,
  Masthead,
  MastheadMain,
  MastheadBrand,
  MastheadContent,
  MastheadToggle,
  Nav,
  NavItem,
  NavList,
  Page,
  PageSidebar,
  PageSidebarBody,
  Title,
} from '@patternfly/react-core';
import { BarsIcon } from '@patternfly/react-icons';

import MemoryGraph from './components/MemoryGraph';
import StatusOverview from './components/StatusOverview';

type ActivePanel = 'graph' | 'status';

interface NavEntry {
  id: string;
  label: string;
  panel?: ActivePanel;
  disabled?: boolean;
}

const NAV_ITEMS: NavEntry[] = [
  { id: 'graph', label: 'Memory Graph', panel: 'graph' },
  { id: 'status', label: 'Status Overview', panel: 'status' },
  { id: 'users', label: 'Users & Agents', disabled: true },
  { id: 'curation', label: 'Curation Rules', disabled: true },
  { id: 'contradictions', label: 'Contradictions', disabled: true },
  { id: 'observability', label: 'Observability', disabled: true },
  { id: 'clients', label: 'Client Management', disabled: true },
];

const App: React.FC = () => {
  const [activePanel, setActivePanel] = useState<ActivePanel>('graph');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const masthead = (
    <Masthead>
      <MastheadToggle>
        <Button variant="plain" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle sidebar">
          <BarsIcon />
        </Button>
      </MastheadToggle>
      <MastheadMain>
        <MastheadBrand style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <svg
            width="28"
            height="28"
            viewBox="0 0 28 28"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <circle cx="14" cy="14" r="13" stroke="white" strokeWidth="2" />
            <circle cx="14" cy="14" r="5" fill="white" />
            <line x1="14" y1="1" x2="14" y2="7" stroke="white" strokeWidth="2" />
            <line x1="14" y1="21" x2="14" y2="27" stroke="white" strokeWidth="2" />
            <line x1="1" y1="14" x2="7" y2="14" stroke="white" strokeWidth="2" />
            <line x1="21" y1="14" x2="27" y2="14" stroke="white" strokeWidth="2" />
          </svg>
          <Title headingLevel="h1" size="lg" style={{ color: 'white', margin: 0 }}>
            MemoryHub
          </Title>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Content component="small" style={{ color: 'rgba(255,255,255,0.7)' }}>
          Agent Memory Dashboard
        </Content>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar isSidebarOpen={sidebarOpen}>
      <PageSidebarBody>
        <Nav aria-label="Primary navigation">
          <NavList>
            {NAV_ITEMS.map((item) => (
              <NavItem
                key={item.id}
                itemId={item.id}
                isActive={!item.disabled && item.panel === activePanel}
                onClick={() => {
                  if (!item.disabled && item.panel) {
                    setActivePanel(item.panel);
                  }
                }}
                style={item.disabled ? { opacity: 0.45, cursor: 'not-allowed', pointerEvents: 'none' } : {}}
                aria-disabled={item.disabled}
              >
                {item.label}
              </NavItem>
            ))}
          </NavList>
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar} style={{ height: '100vh', overflow: 'hidden' }}>
      {activePanel === 'graph' && (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
          <MemoryGraph />
        </div>
      )}
      {activePanel === 'status' && <StatusOverview />}
    </Page>
  );
};

export default App;
