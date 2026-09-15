import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Boxes, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react';
import {
  fetchEngineeringHealth,
  fetchEngineeringImpact,
  fetchEngineeringNode,
  fetchProductProfile,
  updateProductProfile,
  type EngineeringHealthPayload,
  type EngineeringNodeDetailPayload,
  type ProductProfilePayload,
} from '../api/engineering';

const divider = '1px solid var(--border-subtle, #22313b)';

function shortHash(value?: string) {
  if (!value) return '—';
  return value.length > 12 ? value.slice(0, 12) : value;
}

export function EngineeringGraphStatus({ selectedObjectId = null }: { selectedObjectId?: string | null }) {
  const [health, setHealth] = useState<EngineeringHealthPayload | null>(null);
  const [profile, setProfile] = useState<ProductProfilePayload | null>(null);
  const [detail, setDetail] = useState<EngineeringNodeDetailPayload | null>(null);
  const [impactCount, setImpactCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const requestSerial = useRef(0);
  const hasHealth = useRef(false);

  const reload = useCallback(async (quiet = false) => {
    const serial = ++requestSerial.current;
    if (!quiet) setBusy(true);
    try {
      const [nextHealth, nextProfile] = await Promise.all([fetchEngineeringHealth(), fetchProductProfile()]);
      if (serial !== requestSerial.current) return;
      setHealth(nextHealth);
      setProfile(nextProfile);
      hasHealth.current = true;
      setError(null);
      setStale(false);
    } catch (caught) {
      if (serial !== requestSerial.current) return;
      setError(caught instanceof Error ? caught.message : String(caught));
      setStale(hasHealth.current);
    } finally {
      if (!quiet && serial === requestSerial.current) setBusy(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(true), 5_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  useEffect(() => {
    if (!selectedObjectId) {
      setDetail(null);
      setImpactCount(0);
      setDetailError(null);
      return;
    }
    const nodeId = `cad:${selectedObjectId}`;
    let active = true;
    setDetailError(null);
    Promise.all([fetchEngineeringNode(nodeId), fetchEngineeringImpact(nodeId)])
      .then(([nextDetail, impact]) => {
        if (!active) return;
        setDetail(nextDetail);
        setImpactCount(impact.count);
        setDetailError(null);
      })
      .catch((caught) => {
        if (!active) return;
        setDetail(null);
        setImpactCount(0);
        setDetailError(caught instanceof Error ? caught.message : String(caught));
      });
    return () => { active = false; };
  }, [selectedObjectId, health?.engineering_graph.graph_revision]);

  const mode = profile?.profile.mode ?? 'general_engineering';
  const findings = profile?.screening.findings ?? [];
  const domains = useMemo(
    () => Object.entries(health?.engineering_graph.domains ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8),
    [health],
  );
  const syncLabel = !health ? 'Loading…' : health.graph_sync.ok ? 'Current' : 'Needs attention';
  const syncColor = !health ? 'inherit' : health.graph_sync.ok ? 'var(--accent, #55f59a)' : 'var(--warning, #f1bf55)';

  const setMode = async (nextMode: 'general_engineering' | 'product_lab') => {
    if (nextMode === mode) return;
    setBusy(true);
    try {
      const existing = profile?.profile ?? {};
      const updated = await updateProductProfile({
        ...existing,
        mode: nextMode,
        human_contact: nextMode === 'product_lab' ? Boolean(existing.human_contact) : false,
        wearable: nextMode === 'product_lab' ? Boolean(existing.wearable) : false,
      });
      setProfile(updated);
      setError(null);
      await reload(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return <div data-testid="engineering-graph-status" style={{ borderTop: divider, paddingTop: 8, marginTop: 1 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
      <Boxes size={12}/><strong style={{ fontSize: 10 }}>ENGINEERING GRAPH</strong>
      <button
        title="Refresh engineering graph status"
        aria-label="Refresh engineering graph status"
        onClick={() => void reload()}
        disabled={busy}
        style={{ marginLeft: 'auto', border: 0, padding: 1, background: 'transparent', color: 'inherit', cursor: 'pointer' }}
      ><RefreshCw size={11} className={busy ? 'agent-spin' : ''}/></button>
    </div>
    {error ? <div style={{ fontSize: 9.5, color: 'var(--warning, #f1bf55)', marginBottom: 5 }}>{stale ? 'Showing last known graph state. Latest refresh failed: ' : ''}{error}</div> : null}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5 }}>
      <TinyMetric label="NODES" value={health?.engineering_graph.node_count ?? '—'}/>
      <TinyMetric label="EDGES" value={health?.engineering_graph.edge_count ?? '—'}/>
      <TinyMetric label="DIRTY" value={health?.engineering_graph.dirty_node_count ?? '—'} warn={health != null && (health.engineering_graph.dirty_node_count ?? 0) > 0}/>
      <TinyMetric label="STALE EV." value={health?.engineering_graph.stale_evidence_count ?? '—'} warn={health != null && (health.engineering_graph.stale_evidence_count ?? 0) > 0}/>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr', gap: 5, fontSize: 9.5, marginTop: 6 }}>
      <span style={{ opacity: .5 }}>Revision</span><span title={health?.engineering_graph.graph_revision}>{shortHash(health?.engineering_graph.graph_revision)}</span>
      <span style={{ opacity: .5 }}>Sync</span><strong style={{ color: syncColor }}>{syncLabel}</strong>
    </div>
    {domains.length ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 6 }}>
      {domains.map(([domain, count]) => <span key={domain} style={{ fontSize: 8.5, border: divider, borderRadius: 4, padding: '1px 4px', opacity: .75 }}>{domain} {count}</span>)}
    </div> : null}

    <div style={{ borderTop: divider, paddingTop: 7, marginTop: 7 }} data-testid="product-lab-profile">
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 5 }}><Sparkles size={11}/><span style={{ fontSize: 9, opacity: .6 }}>WORKSPACE PROFILE</span></div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
        <ModeButton active={mode === 'general_engineering'} disabled={busy || !profile} onClick={() => void setMode('general_engineering')}>General</ModeButton>
        <ModeButton active={mode === 'product_lab'} disabled={busy || !profile} onClick={() => void setMode('product_lab')}>Product Lab</ModeButton>
      </div>
      {!profile ? <div style={{ fontSize: 9, opacity: .55, marginTop: 5 }}>Loading workspace profile…</div> : null}
      {mode === 'product_lab' && profile ? <div style={{ fontSize: 9, opacity: .65, lineHeight: 1.35, marginTop: 5 }}>
        Compact-product engineering profile: packaging, wearables/human-contact budgets, prototype DFM and physical evidence use the same canonical graph.
      </div> : null}
      {findings.slice(0, 3).map((finding) => <div key={`${finding.code}-${finding.message}`} style={{ display: 'grid', gridTemplateColumns: '12px 1fr', gap: 4, marginTop: 4, fontSize: 8.8, color: finding.severity === 'error' ? 'var(--danger, #ff6b6b)' : 'var(--warning, #f1bf55)' }}><TriangleAlert size={10}/><span>{finding.message}</span></div>)}
    </div>

    {detail ? <div style={{ borderTop: divider, paddingTop: 7, marginTop: 7 }} data-testid="engineering-selected-context">
      <div style={{ fontSize: 9, opacity: .55, marginBottom: 4 }}>SELECTED ENGINEERING CONTEXT</div>
      <div style={{ fontSize: 10.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detail.node.name}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginTop: 5 }}>
        <TinyMetric label="LINKS" value={detail.edges.length}/>
        <TinyMetric label="IMPACT" value={impactCount}/>
        <TinyMetric label="EVIDENCE" value={detail.evidence.length}/>
        <TinyMetric label="STATE" value={detail.node.dirty ? 'DIRTY' : 'CURRENT'} warn={detail.node.dirty}/>
      </div>
      {detail.node.dirty_reasons.slice(0, 2).map((reason) => <div key={reason} style={{ fontSize: 8.8, opacity: .65, marginTop: 4 }}>{reason}</div>)}
    </div> : selectedObjectId && !detailError ? <div style={{ borderTop: divider, paddingTop: 7, marginTop: 7, fontSize: 9, opacity: .55 }}>Loading selected engineering context…</div> : null}
    {detailError ? <div style={{ borderTop: divider, paddingTop: 7, marginTop: 7, fontSize: 9, color: 'var(--warning, #f1bf55)' }}>Selected engineering context unavailable: {detailError}</div> : null}
  </div>;
}

function TinyMetric({ label, value, warn = false }: { label: string; value: string | number; warn?: boolean }) {
  return <div style={{ border: divider, borderRadius: 4, padding: '4px 5px', minWidth: 0 }}><div style={{ fontSize: 8, opacity: .5 }}>{label}</div><strong style={{ display: 'block', fontSize: 10.5, color: warn ? 'var(--warning, #f1bf55)' : 'inherit', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</strong></div>;
}

function ModeButton({ active, disabled, onClick, children }: { active: boolean; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button disabled={disabled} onClick={onClick} style={{ border: active ? '1px solid var(--accent, #55f59a)' : divider, borderRadius: 4, background: active ? 'var(--accent-dim, rgba(85,245,154,.12))' : 'transparent', color: 'inherit', fontSize: 9, padding: '4px 5px', cursor: disabled ? 'default' : 'pointer' }}>{children}</button>;
}
