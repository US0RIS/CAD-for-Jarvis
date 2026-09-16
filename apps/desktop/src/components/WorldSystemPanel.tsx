import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Box, Database, Link2, RefreshCw, ScanSearch, ShieldCheck, Wifi } from 'lucide-react';
import {
  fetchWorldEntities,
  fetchWorldEvents,
  fetchWorldHealth,
  fetchWorldRelations,
  type WorldEntityPayload,
  type WorldEventPayload,
  type WorldHealthPayload,
  type WorldRelationPayload,
} from '../api/world';
import { EngineeringGraphStatus } from './EngineeringGraphStatus';

function compactValue(value: unknown) {
  if (value == null) return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    const serialized = JSON.stringify(value);
    return serialized.length > 60 ? `${serialized.slice(0, 57)}…` : serialized;
  } catch {
    return String(value);
  }
}

function relativeSource(entity: WorldEntityPayload) {
  const authoritative = entity.provenance.find((row) => row.authoritative) ?? entity.provenance[0];
  if (!authoritative) return 'unknown';
  return authoritative.source_id ? `${authoritative.source} · ${authoritative.source_id}` : authoritative.source;
}

function observationAge(value: string) {
  const at = Date.parse(value);
  if (!Number.isFinite(at)) return 'time unknown';
  const seconds = Math.max(0, Math.floor((Date.now() - at) / 1000));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const cardStyle = {
  border: '1px solid var(--border-subtle, #22313b)',
  borderRadius: 7,
  background: 'var(--bg-panel-raised, #101b23)',
  minWidth: 0,
} as const;

export function WorldSystemPanel({ selectedObjectId = null }: { selectedObjectId?: string | null }) {
  const [health, setHealth] = useState<WorldHealthPayload | null>(null);
  const [entities, setEntities] = useState<WorldEntityPayload[]>([]);
  const [relations, setRelations] = useState<WorldRelationPayload[]>([]);
  const [events, setEvents] = useState<WorldEventPayload[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const hasHealth = useRef(false);

  const reload = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextHealth, nextEntities, nextRelations, nextEvents] = await Promise.all([
        fetchWorldHealth(),
        fetchWorldEntities(),
        fetchWorldRelations(),
        fetchWorldEvents(undefined, 40),
      ]);
      setHealth(nextHealth);
      setEntities(nextEntities.items);
      setRelations(nextRelations.items);
      setEvents(nextEvents.items);
      hasHealth.current = true;
      setError(null);
      setStale(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setStale(hasHealth.current);
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(true), 5_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  useEffect(() => {
    if (!entities.length) return;
    if (selectedObjectId) {
      const projected = entities.find((entity) => entity.source_links.forgecad_object_id === selectedObjectId);
      if (projected) {
        setSelectedEntityId(projected.id);
        return;
      }
    }
    if (selectedEntityId && entities.some((entity) => entity.id === selectedEntityId)) return;
    const project = entities.find((entity) => entity.source_links.forgecad_branch && !entity.source_links.forgecad_object_id);
    const firstPhysical = entities.find((entity) => entity.kind !== 'world');
    setSelectedEntityId(project?.id ?? firstPhysical?.id ?? entities[0]?.id ?? null);
  }, [entities, selectedEntityId, selectedObjectId]);

  const selected = useMemo(
    () => entities.find((entity) => entity.id === selectedEntityId) ?? null,
    [entities, selectedEntityId],
  );
  const selectedRelations = useMemo(
    () => selected ? relations.filter((relation) => relation.a_id === selected.id || relation.b_id === selected.id) : [],
    [relations, selected],
  );
  const recentEvents = useMemo(() => events.slice(-8).reverse(), [events]);
  const entityRows = useMemo(
    () => entities.filter((entity) => entity.kind !== 'world').slice().sort((a, b) => {
      if (a.parent_id === b.parent_id) return a.name.localeCompare(b.name);
      if (a.kind === 'assembly') return -1;
      if (b.kind === 'assembly') return 1;
      return a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name);
    }),
    [entities],
  );

  if (error && !health) {
    return <div className="dock-empty" data-testid="world-system-panel">
      <Database size={18}/><strong>Physical world unavailable</strong><span>{error}</span>
      <button className="wide-action" onClick={() => void reload()}><RefreshCw size={13}/>Retry</button>
    </div>;
  }

  const projectSyncState = !health ? null : Boolean(health.project_sync.ok);
  const adapterState = !health ? null : true;
  const pendingState = !health ? null : (health.capability_runtime.awaiting_confirmation ?? 0) === 0;

  return <div
    data-testid="world-system-panel"
    style={{ display: 'grid', gridTemplateColumns: '230px minmax(220px, .85fr) minmax(320px, 1.5fr)', gap: 8, padding: 8, height: '100%', minHeight: 0, overflow: 'hidden' }}
  >
    <section style={{ ...cardStyle, padding: 10, display: 'flex', flexDirection: 'column', gap: 9, overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <Database size={14}/><strong style={{ fontSize: 12 }}>PHYSICAL WORLD</strong>
        <button
          title="Refresh world model"
          aria-label="Refresh world model"
          onClick={() => void reload()}
          disabled={loading}
          style={{ marginLeft: 'auto', background: 'transparent', border: 0, color: 'inherit', padding: 2, cursor: loading ? 'default' : 'pointer' }}
        ><RefreshCw size={13} className={loading ? 'agent-spin' : ''}/></button>
      </div>
      {stale && error ? <div role="status" style={{ fontSize: 9.5, lineHeight: 1.35, color: 'var(--warning, #f1bf55)' }}>Showing last known world state. Latest refresh failed: {error}</div> : null}
      {!health && !error ? <div style={{ fontSize: 9.5, opacity: .55 }}>Loading physical-world state…</div> : null}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <Metric label="ENTITIES" value={health?.world.entity_count ?? (loading ? '—' : entities.length)} testId="world-entity-count"/>
        <Metric label="RELATIONS" value={health?.world.relation_count ?? (loading ? '—' : relations.length)}/>
        <Metric label="REVISION" value={health?.world.revision ?? '—'}/>
        <Metric label="EVENTS" value={health?.world.event_count ?? (loading ? '—' : events.length)}/>
      </div>
      <StatusLine icon={<ShieldCheck size={12}/>} label="Project sync" value={!health ? 'Loading…' : health.project_sync.ok ? 'Current' : 'Needs attention'} good={projectSyncState}/>
      <StatusLine icon={<Wifi size={12}/>} label="Adapters" value={!health ? 'Loading…' : String(health.capability_runtime.registered_adapters.length)} good={adapterState}/>
      <StatusLine icon={<Activity size={12}/>} label="Pending actions" value={!health ? 'Loading…' : String(health.capability_runtime.awaiting_confirmation ?? 0)} good={pendingState}/>
      <EngineeringGraphStatus selectedObjectId={selectedObjectId}/>
      <div style={{ borderTop: '1px solid var(--border-subtle, #22313b)', paddingTop: 8 }}>
        <div style={{ fontSize: 10, opacity: .55, marginBottom: 5 }}>RECENT WORLD CHANGES</div>
        {recentEvents.length ? recentEvents.map((event) => <div key={event.id} style={{ fontSize: 10.5, lineHeight: 1.35, marginBottom: 5 }}>
          <span style={{ opacity: .6 }}>{event.type}</span><br/>
          <span>{event.entity_id ?? event.relation_id ?? event.source}</span>
        </div>) : <div style={{ fontSize: 11, opacity: .55 }}>{loading ? 'Loading world events…' : 'No world events.'}</div>}
      </div>
    </section>

    <section style={{ ...cardStyle, padding: 8, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 3px 7px' }}>
        <ScanSearch size={13}/><strong style={{ fontSize: 11 }}>ENTITIES</strong>
        <span style={{ marginLeft: 'auto', fontSize: 10, opacity: .5 }}>{health ? entityRows.length : '—'}</span>
      </div>
      <div style={{ overflow: 'auto', minHeight: 0 }}>
        {entityRows.map((entity) => <button
          key={entity.id}
          data-testid={`world-entity-${entity.id}`}
          onClick={() => setSelectedEntityId(entity.id)}
          style={{
            width: '100%', display: 'grid', gridTemplateColumns: '18px 1fr', gap: 6, textAlign: 'left',
            border: 0, borderTop: '1px solid var(--border-subtle, #22313b)', padding: '7px 5px',
            background: entity.id === selectedEntityId ? 'var(--accent-dim, rgba(85,245,154,.12))' : 'transparent',
            color: 'inherit', cursor: 'pointer',
          }}
        >
          <Box size={13} style={{ marginTop: 1, opacity: .7 }}/>
          <span style={{ minWidth: 0 }}><strong style={{ display: 'block', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{entity.name}</strong><small style={{ display: 'block', fontSize: 9.5, opacity: .55 }}>{entity.kind} · {entity.id}</small></span>
        </button>)}
        {!entityRows.length && loading ? <div style={{ fontSize: 10, opacity: .5, padding: 6 }}>Loading entities…</div> : null}
      </div>
    </section>

    <section style={{ ...cardStyle, padding: 10, overflow: 'auto' }} data-testid="world-entity-detail">
      {selected ? <>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 9 }}>
          <Box size={15} style={{ marginTop: 1 }}/>
          <div style={{ minWidth: 0 }}>
            <strong style={{ display: 'block', fontSize: 12 }}>{selected.name}</strong>
            <div style={{ fontSize: 10, opacity: .55, wordBreak: 'break-all' }}>{selected.id}</div>
          </div>
          <div style={{ marginLeft: 'auto', fontSize: 10, opacity: .65 }}>{Math.round(selected.confidence * 100)}% confidence</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 7, marginBottom: 10 }}>
          <MiniSection title="IDENTITY">
            <Row label="Kind" value={selected.kind}/><Row label="Parent" value={selected.parent_id ?? 'root'}/><Row label="Source" value={relativeSource(selected)}/>
          </MiniSection>
          <MiniSection title="WORLD POSE">
            <Row label="Frame" value={selected.pose.frame_id}/><Row label="Position" value={selected.pose.position_m.map((v) => `${v.toFixed(3)} m`).join(', ')}/><Row label="Pose conf." value={`${Math.round(selected.pose.confidence * 100)}%`}/>
          </MiniSection>
          <MiniSection title="DESIGN LINK">
            {Object.keys(selected.source_links).length ? Object.entries(selected.source_links).slice(0, 4).map(([key, value]) => <Row key={key} label={key} value={value}/>) : <span style={{ opacity: .5, fontSize: 10 }}>No engineering source link.</span>}
          </MiniSection>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 7 }}>
          <MiniSection title="CAPABILITIES">
            {selected.capabilities.length ? selected.capabilities.map((capability) => <Tag key={capability.name}>{capability.name}</Tag>) : <Empty>None declared</Empty>}
          </MiniSection>
          <MiniSection title="LIVE / OBSERVED STATE">
            {Object.keys(selected.live_state).length ? Object.entries(selected.live_state).map(([key, sample]) => <div key={key} style={{ marginBottom: 5 }}><div style={{ fontSize: 10.5 }}>{key}: <strong>{compactValue(sample.value)}{sample.unit ? ` ${sample.unit}` : ''}</strong></div><div title={sample.observed_at} style={{ fontSize: 9, opacity: .5 }}>{sample.source}{sample.source_id ? ` · ${sample.source_id}` : ''} · {Math.round(sample.confidence * 100)}% · observed {observationAge(sample.observed_at)}</div></div>) : <Empty>No live observations</Empty>}
          </MiniSection>
          <MiniSection title="INTERFACES / RELATIONS">
            {selected.interfaces.slice(0, 5).map((iface) => <div key={iface.id} style={{ fontSize: 10, marginBottom: 4 }}><Link2 size={10} style={{ marginRight: 4, verticalAlign: -1 }}/>{iface.id} <span style={{ opacity: .5 }}>{iface.kind}</span></div>)}
            {selectedRelations.slice(0, 5).map((relation) => <div key={relation.id} style={{ fontSize: 10, marginBottom: 4 }}><span style={{ opacity: .55 }}>{relation.kind}</span> → {relation.a_id === selected.id ? relation.b_id : relation.a_id}</div>)}
            {!selected.interfaces.length && !selectedRelations.length ? <Empty>No interfaces or relations</Empty> : null}
          </MiniSection>
        </div>
      </> : <div className="dock-empty"><Box size={18}/><span>{loading ? 'Loading world entities…' : 'Select a world entity.'}</span></div>}
    </section>
  </div>;
}

function Metric({ label, value, testId }: { label: string; value: string | number; testId?: string }) {
  return <div style={{ padding: 6, border: '1px solid var(--border-subtle, #22313b)', borderRadius: 5 }}><div style={{ fontSize: 9, opacity: .5 }}>{label}</div><strong data-testid={testId} style={{ fontSize: 13 }}>{value}</strong></div>;
}

function StatusLine({ icon, label, value, good }: { icon: React.ReactNode; label: string; value: string; good: boolean | null }) {
  const color = good == null ? 'inherit' : good ? 'var(--accent, #55f59a)' : 'var(--warning, #f1bf55)';
  return <div style={{ display: 'grid', gridTemplateColumns: '14px 1fr auto', gap: 5, alignItems: 'center', fontSize: 10.5 }}><span style={{ opacity: .65 }}>{icon}</span><span style={{ opacity: .65 }}>{label}</span><strong style={{ fontWeight: 600, color, opacity: good == null ? .65 : 1 }}>{value}</strong></div>;
}

function MiniSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <div style={{ borderTop: '1px solid var(--border-subtle, #22313b)', paddingTop: 6, minWidth: 0 }}><div style={{ fontSize: 9, opacity: .5, marginBottom: 5 }}>{title}</div>{children}</div>;
}

function Row({ label, value }: { label: string; value: string }) {
  return <div style={{ display: 'grid', gridTemplateColumns: '70px minmax(0, 1fr)', gap: 5, marginBottom: 3, fontSize: 9.5 }}><span style={{ opacity: .5 }}>{label}</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={value}>{value}</span></div>;
}

function Tag({ children }: { children: React.ReactNode }) {
  return <span style={{ display: 'inline-block', fontSize: 9.5, padding: '2px 5px', margin: '0 4px 4px 0', borderRadius: 4, border: '1px solid var(--border-subtle, #22313b)' }}>{children}</span>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div style={{ opacity: .5, fontSize: 10 }}>{children}</div>;
}
