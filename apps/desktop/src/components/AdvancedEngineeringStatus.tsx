import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Boxes, FlaskConical, RefreshCw, ShieldCheck, TestTube2, Wrench } from 'lucide-react';
import { engineFetch } from '../api/engine';
import '../styles/advanced-engineering-status.css';

type LooseRecord = Record<string, unknown>;
type Snapshot = {
  health: LooseRecord | null;
  constraints: LooseRecord | null;
  rank: LooseRecord | null;
  mates: LooseRecord | null;
  repairTrials: LooseRecord | null;
  retests: LooseRecord | null;
  retestLineage: LooseRecord | null;
  solvers: LooseRecord | null;
  chemistryStudies: LooseRecord | null;
  chemistryRuns: LooseRecord | null;
};

const emptySnapshot: Snapshot = {
  health: null, constraints: null, rank: null, mates: null, repairTrials: null,
  retests: null, retestLineage: null, solvers: null, chemistryStudies: null, chemistryRuns: null,
};

function record(value: unknown): LooseRecord | null {
  return value != null && typeof value === 'object' && !Array.isArray(value) ? value as LooseRecord : null;
}
function rows(value: unknown): LooseRecord[] {
  return Array.isArray(value) ? value.filter((row): row is LooseRecord => row != null && typeof row === 'object' && !Array.isArray(row)) : [];
}
function count(payload: LooseRecord | null, key = 'items') {
  const explicit = Number(payload?.count);
  if (Number.isFinite(explicit)) return explicit;
  return rows(payload?.[key]).length;
}
function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
function boolLabel(value: unknown, yes = 'PASS', no = 'ATTENTION') {
  return value === true ? yes : value === false ? no : 'UNKNOWN';
}
function compact(text: unknown, fallback = '—') {
  if (text == null || text === '') return fallback;
  return String(text).replaceAll('_', ' ');
}

async function settled<T extends LooseRecord>(path: string): Promise<T | null> {
  try { return await engineFetch<T>(path); }
  catch { return null; }
}

export function AdvancedEngineeringStatus({ revision }: { revision?: string | null }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [busy, setBusy] = useState(false);
  const [partial, setPartial] = useState(false);
  const serialRef = useRef(0);

  const reload = useCallback(async () => {
    const serial = ++serialRef.current;
    setBusy(true);
    const results = await Promise.all([
      settled('/v6/health'),
      settled('/v6/assembly/constraints'),
      settled('/v6/assembly/constraint-rank'),
      settled('/v6/assembly/mates'),
      settled('/v6/engineering/repair-trials'),
      settled('/v6/physical/retest-cycles'),
      settled('/v6/physical/retest-lineage'),
      settled('/v6/solvers'),
      settled('/v6/chemistry/studies'),
      settled('/v6/chemistry/runs'),
    ]);
    if (serial !== serialRef.current) return;
    const next: Snapshot = {
      health: results[0], constraints: results[1], rank: results[2], mates: results[3], repairTrials: results[4],
      retests: results[5], retestLineage: results[6], solvers: results[7], chemistryStudies: results[8], chemistryRuns: results[9],
    };
    setSnapshot(next);
    setPartial(results.some((result) => result == null));
    setBusy(false);
  }, []);

  useEffect(() => { void reload(); }, [reload, revision]);

  const solverRows = useMemo(() => rows(snapshot.solvers?.items), [snapshot.solvers]);
  const availableSolvers = solverRows.filter((solver) => solver.available === true);
  const cycles = useMemo(() => rows(snapshot.retests?.items), [snapshot.retests]);
  const latestCycle = cycles[cycles.length - 1] ?? null;
  const healthTruth = record(snapshot.health?.validation_truth);
  const rankSummary = record(snapshot.rank?.summary);
  const constraintSummary = record(snapshot.constraints?.summary);
  const lineageCount = count(snapshot.retestLineage);

  return <div className="campaign-card advanced-engineering-status" data-testid="advanced-engineering-status">
    <div className="campaign-title advanced-engineering-heading">
      <Boxes size={18}/>
      <div><strong>Assembly, evidence & solver state</strong><span>Release-level v6 engineering state that is easy to miss when working only from the 3D canvas.</span></div>
      <button className="editor-action" aria-label="Refresh advanced engineering state" onClick={() => void reload()} disabled={busy}><RefreshCw size={11} className={busy ? 'agent-spin' : ''}/></button>
    </div>

    {partial && <div className="advanced-status-note">Some v6 status endpoints are unavailable in this runtime. ForgeCAD is showing only confirmed state; unavailable evidence is not inferred.</div>}

    <div className="advanced-status-grid">
      <section data-testid="assembly-integrity-status">
        <div className="advanced-status-title"><Wrench size={13}/><strong>Assembly integrity</strong><span className={snapshot.constraints?.ok === true ? 'good' : snapshot.constraints?.ok === false ? 'bad' : ''}>{boolLabel(snapshot.constraints?.ok)}</span></div>
        <dl>
          <dt>Mates</dt><dd>{count(snapshot.mates)}</dd>
          <dt>Geometry-backed mounts</dt><dd>{number(snapshot.health?.geometry_backed_mount_count)}</dd>
          <dt>Mount hardware</dt><dd>{number(snapshot.health?.mount_hardware_realization_count)}</dd>
          <dt>Mobility / rank</dt><dd>{compact(rankSummary?.mobility ?? rankSummary?.remaining_dof ?? constraintSummary?.remaining_dof, 'not asserted')}</dd>
        </dl>
        <small>Mate and mounting truth comes from declared interfaces and B-rep geometry, not proximity guesses.</small>
      </section>

      <section data-testid="physical-evidence-status">
        <div className="advanced-status-title"><TestTube2 size={13}/><strong>Physical evidence</strong><span className={healthTruth?.real_hardware_validation_complete === true ? 'good' : ''}>{healthTruth?.real_hardware_validation_complete === true ? 'HARDWARE VALIDATED' : 'NOT GLOBALLY VALIDATED'}</span></div>
        <dl>
          <dt>Retest cycles</dt><dd>{count(snapshot.retests)}</dd>
          <dt>Lineage records</dt><dd>{lineageCount}</dd>
          <dt>Test runs</dt><dd>{number(snapshot.health?.physical_test_run_count)}</dd>
          <dt>Specimens</dt><dd>{number(snapshot.health?.physical_specimen_count)}</dd>
          <dt>Metrology</dt><dd>{number(snapshot.health?.physical_metrology_record_count)}</dd>
          <dt>Residuals</dt><dd>{number(snapshot.health?.prediction_residual_count)}</dd>
        </dl>
        {latestCycle && <div className="advanced-latest"><span>Latest cycle</span><strong>{compact(latestCycle.id ?? latestCycle.name, 'recorded cycle')}</strong><small>{compact(latestCycle.status ?? latestCycle.state, 'status not asserted')}</small></div>}
        <small>A passing retest applies only to its scoped requirement and exact tested engineering fingerprint.</small>
      </section>

      <section data-testid="solver-runtime-status">
        <div className="advanced-status-title"><FlaskConical size={13}/><strong>External solvers</strong><span>{availableSolvers.length}/{solverRows.length || number(snapshot.solvers?.count)} AVAILABLE</span></div>
        <div className="advanced-solver-list">{solverRows.length ? solverRows.map((solver) => <div key={String(solver.id)}><span className={`state-dot ${solver.available === true ? 'available' : ''}`}/><strong>{compact(solver.name ?? solver.id)}</strong><small>{solver.available === true ? compact(solver.module_version ?? solver.executable_path, 'available') : 'not installed / unavailable'}</small></div>) : <small>No solver inventory returned.</small>}</div>
        <small>Missing external solvers fail closed. Availability alone does not prove that a particular model has a supported adapter/case.</small>
      </section>

      <section data-testid="engineering-lineage-status">
        <div className="advanced-status-title"><Activity size={13}/><strong>Engineering lineage</strong><span>CANONICAL</span></div>
        <dl>
          <dt>Repair trials</dt><dd>{count(snapshot.repairTrials)}</dd>
          <dt>Chemistry studies</dt><dd>{count(snapshot.chemistryStudies)}</dd>
          <dt>Chemistry runs</dt><dd>{count(snapshot.chemistryRuns)}</dd>
          <dt>Release stage</dt><dd>{compact(snapshot.health?.release_stage)}</dd>
        </dl>
        <small>Repair and external-solver evidence stays tied to the branch and engineering revision that produced it.</small>
      </section>
    </div>

    <div className="campaign-disclaimer"><ShieldCheck size={11}/>This panel is an evidence inspector. It never upgrades a branch label, solver result, synthetic CI fixture, or fabrication-package hash into physical verification.</div>
  </div>;
}
