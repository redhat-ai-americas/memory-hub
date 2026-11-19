import React from 'react';
import { Hub } from '@/components/Shell';
import { type HashRoute } from '@/hooks/useHashRoute';
import Clients from './Clients';
import Identities from './Identities';

/** User menu item "My agents & API keys": your agents and their OAuth clients. */
const MyAgents: React.FC<{ route: HashRoute }> = ({ route }) => (
  <Hub
    title="My agents & API keys"
    description="The agents registered to you and the credentials they use to reach MemoryHub. Your agents act with your permissions: they read what you can read and write where you can write."
    route={route}
    fallback="agents"
    views={[
      { value: 'agents', label: 'My agents', render: () => <Identities route={route} /> },
      { value: 'keys', label: 'API keys & OAuth clients', render: () => <Clients route={route} /> },
    ]}
  />
);

export default MyAgents;
