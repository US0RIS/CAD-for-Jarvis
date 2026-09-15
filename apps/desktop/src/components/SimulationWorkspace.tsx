import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Flame, Gauge, Orbit, Play, RefreshCw, ShieldAlert, Wind } from 'lucide-react';
import {
  driveSimulationJoint,
  fetchSimulationHealth,
  fetchSimulationRuns,
  runAerodynamics,
  runGravityLoadPath,
  runTransientThermal,
  type JointPoseInput,
  type SimulationHealth,
  type SimulationJointEdge,
  type SimulationRun,
  type SimulationRuns,
} from '../api/simulation';

type NumericMap = Record<string, number>;

type ActionState = {
  label: string;
  error: string | null;
  detail: Record<string, unknown> | null;
};

const FIELD_STYLE = { width: '100%', minWidth: 0 } as const;

function number(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be a finite number`);
  return parsed;
}

function compactResult(result: Record<string, unknown> | null): string {
  if (!result) return '';
  const text = JSON.stringify(result, null, 2);
  return text.length > 6000 ? `${text.slice(0, 6000)}\n…` : text;
}

function runState(run: SimulationRun): string {
  if (run.stale || run.fingerprint_current === false) return 'STALE';
  return 'CURRENT';
}

function jointFields(edge: SimulationJointEdge, values: NumericMap, setValue: (key: string, value: number) => void) {
  const prefix = edge.joint_id;
  const input = (key: string, label: string, unit: string) => <label className="field" key={key}>
    <span>{label}</span>
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 5, alignItems: 'center' }}>
      <input
        aria-label={`${edge.name} ${label}`}
        type="number"
        step="any"
        value={values[`${prefix}:${key}`] ?? 0}
        onChange={(event) => setValue(`${prefix}:${key}`, Number(event.currentTarget.value))}
        style={FIELD_STYLE}
      />
      <small>{unit}</small>
    </div>
  </label>;

  if (edge.type === 'fixed') return <small>0 DOF · rigid connection</small>;
  if (edge.type === 'revolute') return input('rotation_deg', 'Angle', 'deg');
  if (edge.type === 'prismatic') return input('translation_mm', 'Travel', 'mm');
  if (edge.type === 'cylindrical') return <div className="simulation-input-grid">{input('rotation_deg', 'Angle', 'deg')}{input('translation_mm', 'Travel', 'mm')}</div>;
  return <div className="simulation-input-grid">{input('rotation_deg', 'Angle', 'deg')}{input('plane_u_mm', 'Plane U', 'mm')}{input('plane_v_mm', 'Plane V', 'mm')}</div>;
}

export function SimulationWorkspace({ revision }: { revision: string | null }) {
  const [health, setHealth] = useState<SimulationHealth | null>(null);
  const [runs, setRuns] = useState<SimulationRuns | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionState>({ label: '', error: null, detail: null });
  const [jointValues, setJointValues] = useState<NumericMap>({});
  const [thermal, setThermal] = useState({ duration: '300', timestep: '1', initial: '22' });
  const [aero, setAero] = useState({ vx: '10', vy: '0', vz: '0', density: '1.225', cd: '1.0', area: '' });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextHealth, nextRuns] = await Promise.all([fetchSimulationHealth(), fetchSimulationRuns()]);
      setHealth(nextHealth);
      setRuns(nextRuns);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh, revision]);

  const runAction = useCallback(async (label: string, task: () => Promise<Record<string, unknown>>) => {
    setAction({ label, error: null, detail: null });
    try {
      const detail = await task();
      setAction({ label, error: null, detail });
      await refresh();
    } catch (error) {
      setAction({ label, error: error instanceof Error ? error.message : String(error), detail: null });
    }
  }, [refresh]);

  const driveJoint = useCallback((edge: SimulationJointEdge) => {
    if (edge.type === 'fixed') return;
    const prefix = edge.joint_id;
    const input: JointPoseInput = { joint_id: edge.joint_id, commit: true, reason: `6.1 simulation drive: ${edge.name}` };
    if (edge.type === 'revolute') input.rotation_deg = jointValues[`${prefix}:rotation_deg`] ?? 0;
    if (edge.type === 'prismatic') input.translation_mm = jointValues[`${prefix}:translation_mm`] ?? 0;
    if (edge.type === 'cylindrical') {
      input.rotation_deg = jointValues[`${prefix}:rotation_deg`] ?? 0;
      input.translation_mm = jointValues[`${prefix}:translation_mm`] ?? 0;
    }
    if (edge.type === 'planar') {
      input.rotation_deg = jointValues[`${prefix}:rotation_deg`] ?? 0;
      input.plane_u_mm = jointValues[`${prefix}:plane_u_mm`] ?? 0;
      input.plane_v_mm = jointValues[`${prefix}:plane_v_mm`] ?? 0;
    }
    void runAction(`Drive ${edge.name}`, () => driveSimulationJoint(input));
  }, [jointValues, runAction]);

  const domainRows = useMemo(() => {
    if (!health) return [];
    const order = ['multibody_kinematics', 'joint_load_path', 'transient_thermal', 'integral_aerodynamics', 'steady_thermal_network', 'steady_fluid_network', 'solid_fea', 'rigid_body'];
    return order.flatMap((key) => health.domains[key] ? [[key, health.domains[key]] as const] : []);
  }, [health]);

  const setJointValue = useCallback((key: string, value: number) => {
    setJointValues((current) => ({ ...current, [key]: Number.isFinite(value) ? value : 0 }));
  }, []);

  const currentRuns = runs?.items.filter((row) => !row.stale && row.fingerprint_current !== false) ?? [];
  const staleRuns = runs?.items.filter((row) => row.stale || row.fingerprint_current === false) ?? [];

  return <div className="campaign-card simulation-workspace" data-testid="simulation-workspace">
    <div className="campaign-title" style={{ alignItems: 'flex-start' }}>
      <Gauge size={18}/>
      <div style={{ minWidth: 0 }}>
        <strong>Simulation workspace · 6.1</strong>
        <span>One canonical assembly state drives motion, load paths, thermal behavior and aerodynamic loads.</span>
      </div>
      <button className="icon-button" type="button" title="Refresh simulation state" aria-label="Refresh simulation state" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14}/></button>
    </div>

    {loadError && <div className="campaign-disclaimer" data-testid="simulation-load-error"><AlertTriangle size={12}/>{loadError}</div>}
    {health && <>
      <div className="campaign-result-meta" data-testid="simulation-health">
        <span><b>{health.assembly.joint_count}</b> joints</span>
        <span><b>{health.assembly.object_count}</b> bodies</span>
        <span><b>{currentRuns.length}</b> current runs</span>
        <span><b>{staleRuns.length}</b> stale runs</span>
        <span><b>{health.assembly.ok ? 'READY' : 'BLOCKED'}</b> kinematics</span>
      </div>
      <div className="campaign-disclaimer"><ShieldAlert size={11}/>{health.truth}</div>
    </>}

    {health && !health.assembly.ok && <div className="simulation-warning" data-testid="simulation-assembly-errors">
      <AlertTriangle size={15}/><div><strong>Assembly simulation is blocked</strong>{health.assembly.errors.map((row) => <span key={`${row.code}:${row.message}`}>{row.message}</span>)}</div>
    </div>}

    <div className="simulation-section" data-testid="simulation-joints">
      <div className="simulation-section-heading"><Orbit size={15}/><div><strong>Joint continuity</strong><span>Driving a joint moves its complete downstream subassembly while preserving the kinematic tree.</span></div></div>
      {!health?.assembly.edges.length && <small>No canonical rigid joints are modeled in this branch.</small>}
      <div className="simulation-joint-list">
        {health?.assembly.edges.map((edge) => <div className="simulation-joint-row" key={edge.joint_id} data-testid={`simulation-joint-${edge.joint_id}`}>
          <div className="simulation-joint-name"><strong>{edge.name}</strong><span>{edge.type} · {edge.parent_id} → {edge.child_id}</span></div>
          <div>{jointFields(edge, jointValues, setJointValue)}</div>
          <button type="button" onClick={() => driveJoint(edge)} disabled={edge.type === 'fixed' || !health.assembly.ok || Boolean(action.label && !action.error && !action.detail)}><Play size={13}/>Drive</button>
        </div>)}
      </div>
      <button type="button" onClick={() => void runAction('Gravity load path', () => runGravityLoadPath())} disabled={!health?.assembly.ok}><Play size={13}/>Solve gravity load path</button>
    </div>

    <div className="simulation-two-column">
      <section className="simulation-section" data-testid="simulation-thermal">
        <div className="simulation-section-heading"><Flame size={15}/><div><strong>Transient thermal</strong><span>Thermal mass + conduction + convection + fixed sinks + modeled radiation.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Duration (s)</span><input type="number" min="0.001" step="any" value={thermal.duration} onChange={(event) => setThermal((row) => ({ ...row, duration: event.currentTarget.value }))}/></label>
          <label className="field"><span>Step (s)</span><input type="number" min="0.0001" step="any" value={thermal.timestep} onChange={(event) => setThermal((row) => ({ ...row, timestep: event.currentTarget.value }))}/></label>
          <label className="field"><span>Initial °C</span><input type="number" step="any" value={thermal.initial} onChange={(event) => setThermal((row) => ({ ...row, initial: event.currentTarget.value }))}/></label>
        </div>
        <button type="button" onClick={() => void runAction('Transient thermal', () => runTransientThermal({ duration_s: number(thermal.duration, 'Duration'), timestep_s: number(thermal.timestep, 'Timestep'), initial_temperature_c: number(thermal.initial, 'Initial temperature') }))}><Play size={13}/>Run transient thermal</button>
        <small>Requires canonical heat loads and explicit thermal boundaries. Missing physics is reported, not guessed.</small>
      </section>

      <section className="simulation-section" data-testid="simulation-aerodynamics">
        <div className="simulation-section-heading"><Wind size={15}/><div><strong>Aerodynamic loads</strong><span>Geometry-aware coefficient model for integrated loads; explicitly not CFD.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Air Vx (m/s)</span><input type="number" step="any" value={aero.vx} onChange={(event) => setAero((row) => ({ ...row, vx: event.currentTarget.value }))}/></label>
          <label className="field"><span>Vy</span><input type="number" step="any" value={aero.vy} onChange={(event) => setAero((row) => ({ ...row, vy: event.currentTarget.value }))}/></label>
          <label className="field"><span>Vz</span><input type="number" step="any" value={aero.vz} onChange={(event) => setAero((row) => ({ ...row, vz: event.currentTarget.value }))}/></label>
          <label className="field"><span>Density kg/m³</span><input type="number" min="0.001" step="any" value={aero.density} onChange={(event) => setAero((row) => ({ ...row, density: event.currentTarget.value }))}/></label>
          <label className="field"><span>Cd</span><input type="number" min="0" step="any" value={aero.cd} onChange={(event) => setAero((row) => ({ ...row, cd: event.currentTarget.value }))}/></label>
          <label className="field"><span>Reference area m²</span><input type="number" min="0" step="any" placeholder="geometry envelope" value={aero.area} onChange={(event) => setAero((row) => ({ ...row, area: event.currentTarget.value }))}/></label>
        </div>
        <button type="button" onClick={() => void runAction('Aerodynamic loads', () => {
          const input = {
            relative_air_velocity_m_s: [number(aero.vx, 'Vx'), number(aero.vy, 'Vy'), number(aero.vz, 'Vz')] as [number, number, number],
            air_density_kg_m3: number(aero.density, 'Air density'),
            drag_coefficient: number(aero.cd, 'Drag coefficient'),
          };
          return aero.area.trim() ? runAerodynamics({ ...input, reference_area_m2: number(aero.area, 'Reference area') }) : runAerodynamics(input);
        })}><Play size={13}/>Run aerodynamic loads</button>
        <small>OpenFOAM remains fail-closed until ForgeCAD has a validated geometry→mesh→boundary-condition case adapter.</small>
      </section>
    </div>

    <div className="simulation-section" data-testid="simulation-domain-fidelity">
      <div className="simulation-section-heading"><Gauge size={15}/><div><strong>Solver fidelity</strong><span>Availability and claim strength are separate. A screening solver is never displayed as CFD/FEA-equivalent evidence.</span></div></div>
      <div className="simulation-domain-grid">
        {domainRows.map(([key, row]) => <div className="simulation-domain" key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{row.available ? row.grade : 'unavailable'}</strong>{row.is_cfd === false && <small>not CFD</small>}</div>)}
      </div>
    </div>

    {(action.label || runs?.count) ? <div className="simulation-section" data-testid="simulation-results">
      <div className="simulation-section-heading">{action.error ? <AlertTriangle size={15}/> : <CheckCircle2 size={15}/>}<div><strong>Simulation evidence</strong><span>{runs?.count ?? 0} recorded run{runs?.count === 1 ? '' : 's'} · current results are tied to design fingerprint {health?.design_fingerprint.slice(0, 12) ?? '…'}.</span></div></div>
      {action.label && <div className={action.error ? 'simulation-warning' : 'simulation-action-result'}><strong>{action.label}</strong><span>{action.error ?? 'Completed and recorded against the current canonical design state.'}</span>{action.detail && <details><summary>Inspect latest result</summary><pre>{compactResult(action.detail)}</pre></details>}</div>}
      <div className="simulation-run-list">
        {runs?.items.slice().reverse().slice(0, 8).map((run, index) => <div className="simulation-run-row" key={String(run.id ?? `${run.kind}:${index}`)}>
          <div><strong>{String(run.kind ?? 'simulation')}</strong><span>{String(run.solver ?? 'legacy solver')} · {String(run.solver_grade ?? 'legacy')}</span></div>
          <b className={runState(run) === 'CURRENT' ? 'simulation-current' : 'simulation-stale'}>{runState(run)}</b>
        </div>)}
      </div>
    </div> : null}
  </div>;
}
