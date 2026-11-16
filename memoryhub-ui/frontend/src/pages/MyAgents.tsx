import React from 'react';
import { Hub } from '@/components/Shell';
import { type HashRoute } from '@/hooks/useHashRoute';
import Clients from './Clients';
import Connect from './Connect';
import Verify from './Verify';
import Identities from './Identities';

/** User menu item "My agents & API keys": your agents, their credentials, connecting a new one and checking the connection. */
const MyAgents: React.FC<{ route: HashRoute }> = ({ route }) => (
  <Hub
    title="My agents & API keys"
    description="The agents registered to you and the credentials they use to reach MemoryHub. Your agents act with your permissions: they read what you can read and write where you can write."
    route={route}
    fallback="agents"
    views={[
      { value: 'agents', label: 'My agents', render: () => <Identities route={route} /> },
      { value: 'keys', label: 'API keys & OAuth clients', render: () => <Clients route={route} /> },
      { value: 'connect', label: 'Connect an agent', render: () => <Connect /> },
      { value: 'verify', label: 'Connection check', render: () => <Verify /> },
    ]}
  />
);

export default MyAgents;
