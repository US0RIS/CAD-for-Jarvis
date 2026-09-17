import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Droplets, Flame, Gauge, Orbit, Play, RefreshCw, ShieldAlert, Wind } from 'lucide-react';
import type { ProjectPayload } from '../api/engine';
import {
  driveSimulationJoint,
  fetchSimulationHealth,
  fetchSimulationRuns,
  runAerodynamics,
  runFluidSteady,
  runGravityLoadPath,
  runRigidBody,
  runStructural,
  runTransientThermal,
  sweepSimulationJoint,
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

function parseNumber(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be a finite number`);
  return parsed;
}

function compactResult(result: Record<string, unknown> | null): string {
  if (!result) return '';
  const text = JSON.stringify(result, null, 2);
  return text.length > 7000 ? `${text.slice(0, 7000)}\n…` : text;
}

function runState(run: SimulationRun): 'CURRENT' | 'STALE' {
  return run.stale || run.fingerprint_current === false ? 'STALE' : 'CURRENT';
}

function jointState(edge: SimulationJointEdge, values: NumericMap): Record<string, number> {
  const key = (name: string) => values[`${edge.joint_id}:${name}`] ?? 0;
  if (edge.type === 'revolute') return { rotation_deg: key('rotation_deg') };
  if (edge.type === 'prismatic') return { translation_mm: key('translation_mm') };
  if (edge.type === 'cylindrical') return { rotation_deg: key('rotation_deg'), translation_mm: key('translation_mm') };
  if (edge.type === 'planar') return { rotation_deg: key('rotation_deg'), plane_u_mm: key('plane_u_mm'), plane_v_mm: key('plane_v_mm') };
  return {};
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
        onChange={(event) => setValue(`${prefix}:${key}`, Number(event.target.value))}
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

export function SimulationWorkspace({ project }: { project: ProjectPayload | null }) {
  const revision = project?.revision ?? null;
  const [health, setHealth] = useState<SimulationHealth | null>(null);
  const [runs, setRuns] = useState<SimulationRuns | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionState>({ label: '', error: null, detail: null });
  const [jointValues, setJointValues] = useState<NumericMap>({});
  const [motion, setMotion] = useState({ duration: '1', samples: '21' });
  const [thermal, setThermal] = useState({ duration: '300', timestep: '1', initial: '22' });
  const [aero, setAero] = useState({ vx: '10', vy: '0', vz: '0', density: '1.225', cd: '1.0', area: '' });
  const [structural, setStructural] = useState({ objectId: '', mode: 'canonical' as 'canonical' | 'screening', force: '100', direction: 'z' as 'x' | 'y' | 'z' });
  const [rigid, setRigid] = useState({ duration: '1', fx: '0', fy: '0', fz: '0', tx: '0', ty: '0', tz: '0' });

  useEffect(() => {
    const ids = project?.parts.map((part) => part.id) ?? [];
    if (!ids.length) {
      setStructural((row) => row.objectId ? { ...row, objectId: '' } : row);
      return;
    }
    setStructural((row) => ids.includes(row.objectId) ? row : { ...row, objectId: ids[0] ?? '' });
  }, [project?.revision, project?.parts]);

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
    if (busy) return;
    setBusy(true);
    setAction({ label, error: null, detail: null });
    try {
      const detail = await task();
      setAction({ label, error: null, detail });
      await refresh();
    } catch (error) {
      setAction({ label, error: error instanceof Error ? error.message : String(error), detail: null });
    } finally {
      setBusy(false);
    }
  }, [busy, refresh]);

  const setJointValue = useCallback((key: string, value: number) => {
    setJointValues((current) => ({ ...current, [key]: Number.isFinite(value) ? value : 0 }));
  }, []);

  const driveJoint = useCallback((edge: SimulationJointEdge) => {
    if (edge.type === 'fixed') return;
    const state = jointState(edge, jointValues);
    const input: JointPoseInput = { joint_id: edge.joint_id, commit: true, reason: `6.1 simulation drive: ${edge.name}` };
    Object.assign(input, state);
    void runAction(`Drive ${edge.name}`, () => driveSimulationJoint(input));
  }, [jointValues, runAction]);

  const sweepJoint = useCallback((edge: SimulationJointEdge) => {
    if (edge.type === 'fixed') return;
    const endState = jointState(edge, jointValues);
    const startState = Object.fromEntries(Object.keys(endState).map((key) => [key, 0]));
    void runAction(`Simulate ${edge.name}`, () => sweepSimulationJoint({
      joint_id: edge.joint_id,
      start_state: startState,
      end_state: endState,
      duration_s: parseNumber(motion.duration, 'Motion duration'),
      samples: Math.trunc(parseNumber(motion.samples, 'Motion samples')),
      gravity_m_s2: [0, 0, -9.80665],
    }));
  }, [jointValues, motion, runAction]);

  const domainRows = useMemo(() => {
    if (!health) return [];
    const order = ['multibody_kinematics', 'joint_load_path', 'transient_thermal', 'integral_aerodynamics', 'steady_thermal_network', 'steady_fluid_network', 'solid_fea', 'rigid_body'];
    return order.flatMap((key) => health.domains[key] ? [[key, health.domains[key]] as const] : []);
  }, [health]);

  const currentRuns = runs?.items.filter((row) => !row.stale && row.fingerprint_current !== false) ?? [];
  const staleRuns = runs?.items.filter((row) => row.stale || row.fingerprint_current === false) ?? [];

  return <div className="campaign-card simulation-workspace" data-testid="simulation-workspace">
    <div className="campaign-title" style={{ alignItems: 'flex-start' }}>
      <Gauge size={18}/>
      <div style={{ minWidth: 0 }}>
        <strong>Simulation workspace · 6.1</strong>
        <span>One canonical assembly state drives constrained motion, loads, structural response, thermal behavior, fluids and aerodynamic loads.</span>
      </div>
      <button className="icon-button" type="button" title="Refresh simulation state" aria-label="Refresh simulation state" onClick={() => void refresh()} disabled={loading || busy}><RefreshCw size={14}/></button>
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
      <div className="simulation-section-heading"><Orbit size={15}/><div><strong>Joint continuity & motion</strong><span>Drive one pose or simulate a time sweep. Every downstream body follows its supporting joint chain.</span></div></div>
      <div className="simulation-input-grid">
        <label className="field"><span>Sweep duration (s)</span><input aria-label="Sweep duration" type="number" min="0.001" step="any" value={motion.duration} onChange={(event) => setMotion((row) => ({ ...row, duration: event.target.value }))}/></label>
        <label className="field"><span>Sweep samples</span><input aria-label="Sweep samples" type="number" min="3" max="121" step="1" value={motion.samples} onChange={(event) => setMotion((row) => ({ ...row, samples: event.target.value }))}/></label>
      </div>
      {!health?.assembly.edges.length && <small>No canonical rigid joints are modeled in this branch.</small>}
      <div className="simulation-joint-list">
        {health?.assembly.edges.map((edge) => <div className="simulation-joint-row" key={edge.joint_id} data-testid={`simulation-joint-${edge.joint_id}`}>
          <div className="simulation-joint-name"><strong>{edge.name}</strong><span>{edge.type} · {edge.parent_id} → {edge.child_id}</span></div>
          <div>{jointFields(edge, jointValues, setJointValue)}</div>
          <div className="simulation-action-buttons">
            <button type="button" onClick={() => driveJoint(edge)} disabled={edge.type === 'fixed' || !health.assembly.ok || busy}><Play size={13}/>Drive pose</button>
            <button type="button" onClick={() => sweepJoint(edge)} disabled={edge.type === 'fixed' || !health.assembly.ok || busy}><Activity size={13}/>Simulate sweep</button>
          </div>
        </div>)}
      </div>
      <button type="button" onClick={() => void runAction('Gravity load path', () => runGravityLoadPath())} disabled={!health?.assembly.ok || busy}><Play size={13}/>Solve gravity load path</button>
      <small>Sweeps use sampled exact-B-rep interference checks. A reported collision is penetration evidence, not a solved impact/contact response.</small>
    </div>

    <div className="simulation-two-column">
      <section className="simulation-section" data-testid="simulation-thermal">
        <div className="simulation-section-heading"><Flame size={15}/><div><strong>Transient thermal</strong><span>Thermal mass + conduction + convection + fixed sinks + modeled radiation.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Duration (s)</span><input type="number" min="0.001" step="any" value={thermal.duration} onChange={(event) => setThermal((row) => ({ ...row, duration: event.target.value }))}/></label>
          <label className="field"><span>Step (s)</span><input type="number" min="0.0001" step="any" value={thermal.timestep} onChange={(event) => setThermal((row) => ({ ...row, timestep: event.target.value }))}/></label>
          <label className="field"><span>Initial °C</span><input type="number" step="any" value={thermal.initial} onChange={(event) => setThermal((row) => ({ ...row, initial: event.target.value }))}/></label>
        </div>
        <button type="button" disabled={busy} onClick={() => void runAction('Transient thermal', () => runTransientThermal({ duration_s: parseNumber(thermal.duration, 'Duration'), timestep_s: parseNumber(thermal.timestep, 'Timestep'), initial_temperature_c: parseNumber(thermal.initial, 'Initial temperature') }))}><Play size={13}/>Run transient thermal</button>
        <small>Requires canonical heat loads and explicit thermal boundaries. Missing physics is reported, not guessed.</small>
      </section>

      <section className="simulation-section" data-testid="simulation-aerodynamics">
        <div className="simulation-section-heading"><Wind size={15}/><div><strong>Aerodynamic loads</strong><span>Geometry-aware coefficient model for integrated loads; explicitly not CFD.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Air Vx (m/s)</span><input type="number" step="any" value={aero.vx} onChange={(event) => setAero((row) => ({ ...row, vx: event.target.value }))}/></label>
          <label className="field"><span>Vy</span><input type="number" step="any" value={aero.vy} onChange={(event) => setAero((row) => ({ ...row, vy: event.target.value }))}/></label>
          <label className="field"><span>Vz</span><input type="number" step="any" value={aero.vz} onChange={(event) => setAero((row) => ({ ...row, vz: event.target.value }))}/></label>
          <label className="field"><span>Density kg/m³</span><input type="number" min="0.001" step="any" value={aero.density} onChange={(event) => setAero((row) => ({ ...row, density: event.target.value }))}/></label>
          <label className="field"><span>Cd</span><input type="number" min="0" step="any" value={aero.cd} onChange={(event) => setAero((row) => ({ ...row, cd: event.target.value }))}/></label>
          <label className="field"><span>Reference area m²</span><input type="number" min="0" step="any" placeholder="geometry envelope" value={aero.area} onChange={(event) => setAero((row) => ({ ...row, area: event.target.value }))}/></label>
        </div>
        <button type="button" disabled={busy} onClick={() => void runAction('Aerodynamic loads', () => {
          const input = {
            relative_air_velocity_m_s: [parseNumber(aero.vx, 'Vx'), parseNumber(aero.vy, 'Vy'), parseNumber(aero.vz, 'Vz')] as [number, number, number],
            air_density_kg_m3: parseNumber(aero.density, 'Air density'),
            drag_coefficient: parseNumber(aero.cd, 'Drag coefficient'),
          };
          return aero.area.trim() ? runAerodynamics({ ...input, reference_area_m2: parseNumber(aero.area, 'Reference area') }) : runAerodynamics(input);
        })}><Play size={13}/>Run aerodynamic loads</button>
        <small>OpenFOAM remains fail-closed until ForgeCAD has a validated geometry→mesh→boundary-condition case adapter.</small>
      </section>

      <section className="simulation-section" data-testid="simulation-structural">
        <div className="simulation-section-heading"><Gauge size={15}/><div><strong>Structural FEA</strong><span>Use canonical loads/supports when modeled; screening mode is explicit and separately labeled.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Part</span><select value={structural.objectId} onChange={(event) => setStructural((row) => ({ ...row, objectId: event.target.value }))}>{project?.parts.map((part) => <option value={part.id} key={part.id}>{part.name}</option>)}</select></label>
          <label className="field"><span>Mode</span><select value={structural.mode} onChange={(event) => setStructural((row) => ({ ...row, mode: event.target.value as 'canonical' | 'screening' }))}><option value="canonical">Canonical BCs</option><option value="screening">Screening load</option></select></label>
          {structural.mode === 'screening' && <>
            <label className="field"><span>Force (N)</span><input type="number" step="any" value={structural.force} onChange={(event) => setStructural((row) => ({ ...row, force: event.target.value }))}/></label>
            <label className="field"><span>Direction</span><select value={structural.direction} onChange={(event) => setStructural((row) => ({ ...row, direction: event.target.value as 'x' | 'y' | 'z' }))}><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></label>
          </>}
        </div>
        <button type="button" disabled={busy || !structural.objectId} onClick={() => void runAction('Structural FEA', () => runStructural({ object_id: structural.objectId, mode: structural.mode, force_n: parseNumber(structural.force, 'Structural force'), load_direction: structural.direction, convergence: true }))}><Play size={13}/>Run structural FEA</button>
        <small>Built-in solid FEA is exact for its supported unfeatured-box geometry scope and fails closed outside that scope.</small>
      </section>

      <section className="simulation-section" data-testid="simulation-fluid">
        <div className="simulation-section-heading"><Droplets size={15}/><div><strong>Fluid network</strong><span>Steady incompressible pressure/flow solve from canonical pressure boundaries, demands and explicit hydraulic links.</span></div></div>
        <button type="button" disabled={busy} onClick={() => void runAction('Steady fluid network', () => runFluidSteady())}><Play size={13}/>Run steady fluid network</button>
        <small>This is hydraulic network analysis, not CFD. Turbulence, compressibility, cavitation, two-phase flow and transients remain unsupported unless explicitly solved elsewhere.</small>
      </section>

      <section className="simulation-section" data-testid="simulation-rigid-body">
        <div className="simulation-section-heading"><Orbit size={15}/><div><strong>Rigid-body response</strong><span>Assembly mass/inertia plus constant force, torque and gravity over an explicit duration.</span></div></div>
        <div className="simulation-input-grid">
          <label className="field"><span>Duration (s)</span><input type="number" min="0" step="any" value={rigid.duration} onChange={(event) => setRigid((row) => ({ ...row, duration: event.target.value }))}/></label>
          <label className="field"><span>Fx (N)</span><input type="number" step="any" value={rigid.fx} onChange={(event) => setRigid((row) => ({ ...row, fx: event.target.value }))}/></label>
          <label className="field"><span>Fy (N)</span><input type="number" step="any" value={rigid.fy} onChange={(event) => setRigid((row) => ({ ...row, fy: event.target.value }))}/></label>
          <label className="field"><span>Fz (N)</span><input type="number" step="any" value={rigid.fz} onChange={(event) => setRigid((row) => ({ ...row, fz: event.target.value }))}/></label>
          <label className="field"><span>Tx (N·m)</span><input type="number" step="any" value={rigid.tx} onChange={(event) => setRigid((row) => ({ ...row, tx: event.target.value }))}/></label>
          <label className="field"><span>Ty (N·m)</span><input type="number" step="any" value={rigid.ty} onChange={(event) => setRigid((row) => ({ ...row, ty: event.target.value }))}/></label>
          <label className="field"><span>Tz (N·m)</span><input type="number" step="any" value={rigid.tz} onChange={(event) => setRigid((row) => ({ ...row, tz: event.target.value }))}/></label>
        </div>
        <button type="button" disabled={busy} onClick={() => void runAction('Rigid-body response', () => runRigidBody({ duration_s: parseNumber(rigid.duration, 'Rigid-body duration'), force_n: [parseNumber(rigid.fx, 'Fx'), parseNumber(rigid.fy, 'Fy'), parseNumber(rigid.fz, 'Fz')], torque_nm: [parseNumber(rigid.tx, 'Tx'), parseNumber(rigid.ty, 'Ty'), parseNumber(rigid.tz, 'Tz')] }))}><Play size={13}/>Run rigid-body response</button>
        <small>Selected bodies are treated as one rigid assembly in this solver; use joint sweep for constrained articulation.</small>
      </section>
    </div>

    <div className="simulation-section" data-testid="simulation-domain-fidelity">
      <div className="simulation-section-heading"><Gauge size={15}/><div><strong>Solver fidelity</strong><span>Availability and claim strength are separate. Screening evidence is never relabeled as CFD, general FEA or physical validation.</span></div></div>
      <div className="simulation-domain-grid">
        {domainRows.map(([key, row]) => <div className="simulation-domain" key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{row.available ? row.grade : 'unavailable'}</strong>{row.is_cfd === false && <small>not CFD</small>}</div>)}
      </div>
    </div>

    {(action.label || runs?.count) ? <div className="simulation-section" data-testid="simulation-results">
      <div className="simulation-section-heading">{action.error ? <AlertTriangle size={15}/> : <CheckCircle2 size={15}/>}<div><strong>Simulation evidence</strong><span>{runs?.count ?? 0} recorded run{runs?.count === 1 ? '' : 's'} · current results are tied to design fingerprint {health?.design_fingerprint.slice(0, 12) ?? '…'}.</span></div></div>
      {action.label && <div className={action.error ? 'simulation-warning' : 'simulation-action-result'}><strong>{action.label}</strong><span>{action.error ?? (busy ? 'Running…' : 'Completed and recorded against the current canonical design state.')}</span>{action.detail && <details><summary>Inspect latest result</summary><pre>{compactResult(action.detail)}</pre></details>}</div>}
      <div className="simulation-run-list">
        {runs?.items.slice().reverse().slice(0, 10).map((run, index) => <div className="simulation-run-row" key={String(run.id ?? `${run.kind}:${index}`)}>
          <div><strong>{String(run.kind ?? 'simulation')}</strong><span>{String(run.solver ?? 'legacy solver')} · {String(run.solver_grade ?? 'legacy')}</span></div>
          <b className={runState(run) === 'CURRENT' ? 'simulation-current' : 'simulation-stale'}>{runState(run)}</b>
        </div>)}
      </div>
    </div> : null}
  </div>;
}
