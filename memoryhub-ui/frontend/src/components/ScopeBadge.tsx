import React from 'react';
import { Label } from '@patternfly/react-core';
import { SCOPE_LABEL_COLORS } from '@/utils/scopes';

interface ScopeBadgeProps {
  scope: string;
}

const ScopeBadge: React.FC<ScopeBadgeProps> = ({ scope }) => {
  const color = SCOPE_LABEL_COLORS[scope] ?? 'grey';
  return (
    <Label color={color} isCompact>
      {scope}
    </Label>
  );
};

export default ScopeBadge;
