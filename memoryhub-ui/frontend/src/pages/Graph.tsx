import React, { useEffect } from 'react';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';

/**
 * The graph now lives in the Memory browser (View: Graph). Old #/graph links
 * keep working and land on the same memory.
 */
const Graph: React.FC<{ route: HashRoute }> = ({ route }) => {
  useEffect(() => {
    const focus = route.params.get('focus');
    navigate('/memories', { view: 'graph', gfocus: focus ? 'memory' : undefined, focus: focus ?? undefined, depth: route.params.get('depth') ?? undefined }, { replace: true });
  }, [route]);
  return null;
};

export default Graph;
