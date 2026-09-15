import { Activity, Cable, Droplets, Flame, Orbit, ShieldAlert, Zap } from 'lucide-react';
import type { ProjectPayload, ValidationPayload } from '../api/engine';
import { AdvancedEngineeringStatus } from './AdvancedEngineeringStatus';
import { SimulationWorkspace } from './SimulationWorkspace';

type DomainKey = 'electrical' | 'thermal' | 'fluid' | 'routing' | 'safety' | 'kinematics';
type LooseRecord = Record<string, unknown>;

const DOMAINS: Array<{ key: DomainKey; title: string; icon: typeof Zap; description: string }> = [
  { key: 'electrical', title: 'Electrical', icon: Zap, description: 'Canonical nets, rail/current/logic compatibility and interface coverage.' },
  { key: 'thermal', title: 'Thermal', icon: Flame, description: 'Steady-state lumped heat/conductance network and temperature limits.' },
  { key: 'fluid', title: 'Fluid', icon: Droplets, description: 'Steady incompressible hydraulic pressure, flow and routed-tube resistance.' },
  { key: 'routing', title: 'Routing', icon: Cable, description: 'Cable/tube centerline length, bend feasibility, bindings and clearance proxies.' },
  { key: 'safety', title: 'Safety', icon: ShieldAlert, description: 'Failure modes, controls, FMEA prioritization and current-design verification.' },
  { key: 'kinematics', title: 'Kinematics', icon: Orbit, description: 'Joint limits, sampled mechanism sweeps and exact B-rep interference checks.' },
];

function record(value: unknown): LooseRecord | null {
  return value != null && typeof value === 'object' && !Array.isArray(value) ? value as LooseRecord : null;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function finite(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function countFor(key: DomainKey, data: LooseRecord): number {
  const explicit = finite(data.count ?? data.node_count ?? data.joint_count ?? data.net_count);
  if (explicit != null) return explicit;
  if (key === 'electrical') return array(data.nets).length;
  if (key === 'thermal' || key === 'fluid') return array(data.nodes).length;
  if (key === 'routing') return array(data.items).length;
  if (key === 'safety') return array(data.failure_modes).length;
  if (key === 'kinematics') return array(data.items).length;
  return 0;
}

function maxTemperature(data: LooseRecord): number | null {
  const values = array(data.nodes)
    .map((row) => record(row)?.temperature_c)
    .map(finite)
    .filter((value): value is number => value != null);
  return values.length ? Math.max(...values) : finite(data.max_temperature_c);
}

function collisionCount(data: LooseRecord): number {
  const direct = array(data.collisions).length;
  if (direct) return direct;
  return array(data.items).reduce<number>((sum, row) => sum + array(record(row)?.collisions).length, 0);
}

function detailFor(key: DomainKey, data: LooseRecord, count: number): string {
  if (key === 'electrical') return `${count} modeled net${count === 1 ? '' : 's'} · ${array(data.risks).length} electrical finding${array(data.risks).length === 1 ? '' : 's'}`;
  if (key === 'thermal') {
    const max = maxTemperature(data);
    return `${count} thermal node${count === 1 ? '' : 's'}${max == null ? '' : ` · max ${max.toFixed(1)} °C`}`;
  }
  if (key === 'fluid') return `${count} hydraulic node${count === 1 ? '' : 's'} · ${array(data.links).length} explicit link${array(data.links).length === 1 ? '' : 's'}`;
  if (key === 'routing') return `${count} routed path${count === 1 ? '' : 's'} · ${array(data.risks).length} routing finding${array(data.risks).length === 1 ? '' : 's'}`;
  if (key === 'safety') {
    const verified = array(data.failure_modes).filter((row) => record(row)?.verification_status === 'passed').length;
    return `${count} failure mode${count === 1 ? '' : 's'} · ${verified} current-design verified`;
  }
  const collisions = collisionCount(data);
  return `${count} kinematic joint${count === 1 ? '' : 's'} · ${collisions} sampled collision${collisions === 1 ? '' : 's'}`;
}

function pretty(value: unknown): string {
  const text = JSON.stringify(value, null, 2);
  return text.length > 4800 ? `${text.slice(0, 4800)}\n…` : text;
}

function analysisState(modeled: boolean, data: LooseRecord | null, errors: number): 'NOT MODELED' | 'PASS' | 'ATTENTION' | 'MODELED' {
  if (!modeled) return 'NOT MODELED';
  if (errors > 0 || data?.ok === false) return 'ATTENTION';
  if (data?.ok === true) return 'PASS';
  return 'MODELED';
}

export function EngineeringDomainSummary({ validation, project, mode = 'analysis' }: { validation: ValidationPayload | null; project: ProjectPayload | null; mode?: 'design' | 'analysis' }) {
  const root = (validation ?? {}) as unknown as LooseRecord;
  const projectRoot = (project ?? {}) as unknown as LooseRecord;
  const engineeringState = record(projectRoot.engineering_state);
  const routes = array(projectRoot.routes).length;
  const failureModes = array(projectRoot.failure_modes).length;
  const joints = array(engineeringState?.joints).length;
  const loads = array(engineeringState?.loads).length;
  const constraints = array(engineeringState?.constraints).length;
  const parameters = Object.keys(record(engineeringState?.design_parameters) ?? {}).length;

  return <>
    <div className="campaign-card" data-testid="canonical-engineering-state">
      <div className="campaign-title"><Activity size={18}/><div><strong>Canonical engineering state</strong><span>Branch-owned records that the agent, solvers, history and physical evidence all reference.</span></div></div>
      <div className="campaign-result-meta">
        <span><b>{parameters}</b> parameters</span>
        <span><b>{loads}</b> loads</span>
        <span><b>{constraints}</b> constraints</span>
        <span><b>{joints}</b> joints</span>
        <span><b>{routes}</b> routes</span>
        <span><b>{failureModes}</b> failure modes</span>
      </div>
    </div>

    {mode === 'analysis' && <>
      <SimulationWorkspace revision={project?.revision ?? null}/>
      <div className="campaign-card" data-testid="analysis-domains">
        <div className="campaign-title"><Activity size={18}/><div><strong>System analyses</strong><span>Deterministic domain evidence from the same canonical project state. Unknown inputs remain unknown.</span></div></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
          {DOMAINS.map(({ key, title, icon: Icon, description }) => {
            const data = record(root[key]);
            const count = data ? countFor(key, data) : 0;
            const requested = data?.requested;
            const modeled = data != null && (requested === true || count > 0 || data.supported === false);
            const errors = finite(record(data?.counts)?.error) ?? 0;
            const state = analysisState(modeled, data, errors);
            const solver = String(data?.solver ?? 'canonical validation');
            const grade = String(data?.solver_grade ?? 'engineering state');
            return <div key={key} data-testid={`analysis-domain-${key}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: 7, padding: 10, minWidth: 0 }}>
              <div className="campaign-title" style={{ marginBottom: 6 }}><Icon size={15}/><div><strong>{title}</strong><span>{state}</span></div></div>
              <p style={{ margin: '0 0 6px', fontSize: 11 }}>{modeled && data ? detailFor(key, data, count) : description}</p>
              <small>{modeled ? `${solver} · ${grade}${state === 'MODELED' ? ' · no explicit pass/fail assertion' : ''}` : 'No canonical model in this branch.'}</small>
              {modeled && data && <details style={{ marginTop: 7 }}><summary style={{ cursor: 'pointer', fontSize: 11 }}>Inspect evidence</summary><pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 220, fontSize: 10 }}>{pretty(data)}</pre></details>}
            </div>;
          })}
        </div>
        <div className="campaign-disclaimer"><ShieldAlert size={11}/>PASS is shown only when the domain explicitly reports <code>ok: true</code>. Modeled-but-unasserted results remain MODELED. Analysis evidence is not certification or physical verification.</div>
      </div>
      <AdvancedEngineeringStatus revision={project?.revision ?? null}/>
    </>}
  </>;
}
