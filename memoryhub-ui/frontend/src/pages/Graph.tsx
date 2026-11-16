import React, { useEffect } from 'react';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Icon, useToast } from '@/components/ui';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import MemoryGraph from './MemoryGraph';
import MemoryTimeline from './MemoryTimeline';

/**
 * Platform admins: the graph and the timeline of the scopes they moderate,
 * on a page of their own, opened from Content moderation.
 * Everyone else: the graph lives in the Memory browser (View: Graph), and old
 * #/graph links land there on the same memory.
 */
const Graph: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { role } = useApp();
  useEffect(() => {
    if (role === 'admin') return;
    const focus = route.params.get('focus');
    navigate('/memories', { view: 'graph', gfocus: focus ? 'memory' : undefined, focus: focus ?? undefined, depth: route.params.get('depth') ?? undefined }, { replace: true });
  }, [route, role]);
  if (role !== 'admin') return null;
  return <AdminGraph route={route} />;
};

const AdminGraph: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const p = route.params;
  const view: 'graph' | 'timeline' = p.get('view') === 'timeline' ? 'timeline' : 'graph';
  // A focus link from elsewhere (#/graph?focus=…) opens that memory's neighbourhood.
  useEffect(() => {
    if (p.get('focus') && !p.get('gfocus')) setParams({ gfocus: 'memory' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setParams = (changes: Record<string, string | number | string[] | undefined>) => {
    const next = new URLSearchParams(p);
    Object.entries(changes).forEach(([k, v]) => {
      const value = Array.isArray(v) ? v.join(',') : v === undefined ? '' : String(v);
      if (value === '') next.delete(k);
      else next.set(k, value);
    });
    navigate('/graph', next, { replace: true });
  };
  // The list keeps the filters the graph was opened with.
  const listParams = Object.fromEntries([...p].filter(([k]) => !['view', 'gfocus', 'focus', 'depth', 'layout', 'color', 'glimit', 'gprefer', 'sel', 'tdays', 'tby', 'tcolor'].includes(k)));

  const exportPng = () => {
    const svg = document.querySelector<SVGSVGElement>('main .graph-canvas svg, main svg.graph, main svg[role="img"]');
    if (!svg) {
      toast('Nothing to export yet.', 'err');
      return;
    }
    const box = svg.getBoundingClientRect();
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(box.width));
    clone.setAttribute('height', String(box.height));
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }));
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = box.width * 2;
      canvas.height = box.height * 2;
      const ctx = canvas.getContext('2d')!;
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(2, 2);
      ctx.drawImage(img, 0, 0, box.width, box.height);
      URL.revokeObjectURL(url);
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = `memoryhub-${view}-${new Date().toISOString().slice(0, 10)}.png`;
      a.click();
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      toast('The view could not be exported.', 'err');
    };
    img.src = url;
  };

  return (
    <>
      <PageHeader
        title={view === 'graph' ? 'Memory graph · admin scopes' : 'Memory timeline · admin scopes'}
        crumbs={[{ label: 'Content moderation', href: buildHash('/memories', listParams) }, { label: view === 'graph' ? 'Graph' : 'Timeline' }]}
        description="Relationships between memories you may moderate: organizational, enterprise, role and campaign records, and projects where you are a member. Personal records and links to them are left out entirely — not drawn, not counted."
        actions={
          <>
            <a className="btn bs" href={buildHash('/memories', listParams)}>
              Back to list
            </a>
            <button type="button" className="btn bs" onClick={exportPng}>
              Export view (PNG)
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Graph or timeline"
            value={view}
            onChange={(v) => setParams({ view: v === 'graph' ? undefined : v, sel: undefined })}
            tabs={[
              { value: 'graph', label: 'Graph' },
              { value: 'timeline', label: 'Timeline' },
            ]}
          />
        }
      />
      <div className="body">
        {view === 'graph' ? <MemoryGraph route={route} setParams={setParams} /> : <MemoryTimeline route={route} setParams={setParams} />}
        <div className="alert" role="note">
          <Icon.Info stroke="#0066cc" style={{ flex: 'none', marginTop: 1 }} />
          <div>
            What this {view} never contains: personal records, links to them, or counts of them. Users see their own personal graph in their workspace.
          </div>
        </div>
      </div>
    </>
  );
};

export default Graph;
