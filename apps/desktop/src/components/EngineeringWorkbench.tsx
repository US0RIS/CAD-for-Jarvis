import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, CheckCircle2, Download, FileUp, GitCompare, PackageOpen, RefreshCw,
  ShieldAlert, Trophy, Upload, XCircle,
} from 'lucide-react';
import {
  activateBranch,
  compareBranch,
  createJob,
  downloadProjectBundle,
  fetchRegistryStats,
  fetchValidation,
  importProjectBundle,
  importStepFile,
  setBranchStatus,
  type JobPayload,
  type ProjectPayload,
  type RegistryStatsPayload,
  type ValidationPayload,
} from '../api/engine';
import '../styles/engineering-workbench.css';

interface Props {
  mode: 'design' | 'analysis';
  project: ProjectPayload | null;
  selectedId: string | null;
  activeJob: JobPayload | null;
  onProject: (project: ProjectPayload) => void;
  onStartSimulation: () => void;
  onStartCampaign: () => void;
}

type CampaignCandidate = {
  branch: string;
  parameters?: Record<string, number>;
  metrics?: { mass_kg?: number; [key: string]: unknown };
  structural?: { max_displacement_mm?: number; max_deflection_mm?: number; yield_fos?: number; [key: string]: unknown };
  thermal?: { max_temperature_c?: number; [key: string]: unknown };
  manufacturing?: { ok?: boolean; [key: string]: unknown };
  verifier?: { passed?: boolean; gates?: Record<string, boolean>; [key: string]: unknown };
  feasible?: boolean;
  score?: number;
  error?: string;
};

type CampaignResult = {
  status?: string;
  source_branch?: string;
  winner_branch?: string | null;
  objective?: string;
  candidates?: CampaignCandidate[];
  constraints?: Record<string, unknown>;
  roles?: Record<string, unknown>;
};

function ResultBlock({ value }: { value: unknown }) {
  if (value == null) return null;
  const text = JSON.stringify(value, null, 2);
  return <pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 230, fontSize: 11 }}>{text.length > 6500 ? `${text.slice(0, 6500)}\n…` : text}</pre>;
}

function finiteNumber(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function metric(value: unknown, unit = '', digits = 2) {
  const number = finiteNumber(value);
  if (number == null) return '—';
  return `${number.toFixed(digits)}${unit}`;
}

function parameterSummary(parameters?: Record<string, number>) {
  if (!parameters) return 'baseline geometry';
  const rows = Object.entries(parameters);
  if (!rows.length) return 'baseline geometry';
  return rows.map(([key, value]) => `${key} ${Number(value).toFixed(2)} mm`).join(' · ');
}

export function EngineeringWorkbench({ mode, project, selectedId, activeJob, onProject, onStartSimulation, onStartCampaign }: Props) {
  const [validation, setValidation] = useState<ValidationPayload | null>(null);
  const [stats, setStats] = useState<RegistryStatsPayload | null>(null);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [campaignObjective, setCampaignObjective] = useState<'mass' | 'deflection' | 'safety' | 'temperature'>('mass');
  const [campaignProcess, setCampaignProcess] = useState<'cnc' | 'fdm'>('cnc');
  const [campaignForce, setCampaignForce] = useState('100');
  const [campaignDeflection, setCampaignDeflection] = useState('1');
  const [campaignFos, setCampaignFos] = useState('1.5');
  const [campaignTemperature, setCampaignTemperature] = useState('80');
  const [campaignCandidates, setCampaignCandidates] = useState('7');
  const stepInput = useRef<HTMLInputElement | null>(null);
  const bundleInput = useRef<HTMLInputElement | null>(null);
  const activeBranch = project?.branches.find((branch) => branch.active) ?? null;
  const workingBranch = project?.branches.find((branch) => branch.status === 'working' && !branch.active) ?? project?.branches.find((branch) => branch.status === 'working') ?? null;
  const selected = useMemo(() => project?.parts.find((part) => part.id === selectedId) ?? null, [project, selectedId]);
  const fabricatedParts = useMemo(() => project?.parts.filter((part) => !part.component_ref) ?? [], [project]);
  const campaignResult = useMemo<CampaignResult | null>(() => {
    if (activeJob?.kind !== 'campaign' || !activeJob.result || !Array.isArray((activeJob.result as CampaignResult).candidates)) return null;
    return activeJob.result as CampaignResult;
  }, [activeJob]);
  const requirements = (validation?.requirements ?? []) as Array<Record<string, unknown>>;

  async function refresh() {
    try {
      setError(null);
      const [nextValidation, nextStats] = await Promise.all([fetchValidation(), fetchRegistryStats()]);
      setValidation(nextValidation);
      setStats(nextStats);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  useEffect(() => { void refresh(); }, [project?.revision]);

  async function status(status: 'working' | 'not_working' | 'unverified', verified: boolean) {
    if (!activeBranch) return;
    try {
      setBusy(true);
      const result = await setBranchStatus(activeBranch.name, status, `Set from ForgeCAD design inspector`, verified);
      onProject(result.project);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function compare() {
    if (!workingBranch) return;
    try {
      setBusy(true);
      setComparison(await compareBranch(workingBranch.name));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function activate(name: string) {
    try {
      setBusy(true);
      setError(null);
      onProject(await activateBranch(name));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function exportBundle() {
    try {
      setBusy(true);
      const blob = await downloadProjectBundle();
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = `${(project?.name ?? 'ForgeCAD-Project').replace(/[^A-Za-z0-9_.-]+/g, '-')}.forgecad.zip`;
      link.click();
      URL.revokeObjectURL(href);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function onStep(file?: File) {
    if (!file) return;
    try {
      setBusy(true);
      const result = await importStepFile(file);
      onProject(result.project);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      if (stepInput.current) stepInput.current.value = '';
    }
  }

  async function onBundle(file?: File) {
    if (!file) return;
    try {
      setBusy(true);
      const result = await importProjectBundle(file);
      onProject(result.project);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      if (bundleInput.current) bundleInput.current.value = '';
    }
  }

  async function startConfiguredCampaign() {
    const campaignTarget = selected && !selected.component_ref ? selected : fabricatedParts[0] ?? null;
    if (!campaignTarget || !project) return;
    const force = Math.max(0.001, finiteNumber(campaignForce) ?? 100);
    const deflection = Math.max(0.0001, finiteNumber(campaignDeflection) ?? 1);
    const fos = Math.max(0.01, finiteNumber(campaignFos) ?? 1.5);
    const count = Math.max(3, Math.min(24, Math.round(finiteNumber(campaignCandidates) ?? 7)));
    const payload: Record<string, unknown> = {
      objective: campaignObjective,
      process: campaignProcess,
      force_n: force,
      deflection_max_mm: deflection,
      yield_fos_min: fos,
      max_candidates: count,
    };
    if (campaignObjective === 'temperature') payload.max_temperature_c = Math.max(-273.15, finiteNumber(campaignTemperature) ?? 80);
    if (campaignProcess === 'fdm') payload.manufacturing_resource = 'bambu-lab-p2s';
    try {
      setError(null);
      await createJob({
        kind: 'campaign',
        selected_object_id: campaignTarget.id,
        branch: project.active_branch,
        payload,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  if (mode === 'design') return <div className="component-library" data-testid="design-inspector">
    <h2>Canonical design</h2>
    <p>Purchased hardware is immutable engineering data. Human, AI and Jarvis edits share one typed operation model.</p>
    {error && <div className="runtime-banner error"><ShieldAlert size={15}/><div><strong>Engineering operation failed</strong><span>{error}</span></div></div>}
    <div className="campaign-card">
      <div className="campaign-title"><GitCompare size={18}/><div><strong>Design branch</strong><span>{activeBranch?.name ?? '—'} · {activeBranch?.status ?? '—'}</span></div></div>
      <div className="filter-row">
        <button disabled={busy} onClick={() => void status('working', true)}>Works in real life</button>
        <button disabled={busy} onClick={() => void status('not_working', false)}>Not working</button>
        <button disabled={busy} onClick={() => void status('unverified', false)}>Unverified</button>
      </div>
      <button disabled={busy || !workingBranch} onClick={() => void compare()}>Compare to working branch →</button>
      {comparison && <ResultBlock value={comparison}/>} 
    </div>

    {selected && <div className="campaign-card">
      <div className="campaign-title"><PackageOpen size={18}/><div><strong>{selected.name}</strong><span>{selected.role} · {selected.geometry_fidelity ?? 'geometry'} · {selected.mass_g} g</span></div></div>
      <p>{selected.component_ref ? `Registry component: ${selected.component_ref}` : 'Fabricated/custom part generated from exact CAD geometry.'}</p>
    </div>}

    <div className="campaign-card">
      <strong>Portable project + CAD import</strong>
      <p>Bundles carry project state, frozen component snapshots, code and local CAD assets.</p>
      <div className="filter-row">
        <button disabled={busy} onClick={() => void exportBundle()}><Download size={13}/> Export bundle</button>
        <button disabled={busy} onClick={() => bundleInput.current?.click()}><Upload size={13}/> Import bundle</button>
        <button disabled={busy} data-testid="import-step" onClick={() => stepInput.current?.click()}><FileUp size={13}/> Import STEP</button>
      </div>
      <input ref={bundleInput} hidden type="file" accept=".zip,.forgecad.zip" onChange={(event) => void onBundle(event.target.files?.[0])}/>
      <input ref={stepInput} hidden type="file" accept=".step,.stp" onChange={(event) => void onStep(event.target.files?.[0])}/>
    </div>

    <div className="campaign-card">
      <strong>Bill of materials</strong>
      <p>{project?.bom?.length ?? 0} purchased line items · {project?.connections?.length ?? 0} modeled interface connections.</p>
      {(project?.bom ?? []).slice(0, 8).map((item, index) => <div className="history-row" key={index}><strong>{String(item.manufacturer ?? '')} {String(item.model ?? item.description ?? '')}</strong><small>qty {String(item.qty ?? 1)} · {String(item.supplier ?? 'catalog')}</small></div>)}
    </div>
  </div>;

  const campaignBusy = activeJob?.kind === 'campaign' && !['completed', 'failed', 'cancelled'].includes(activeJob.state);
  const campaignTarget = selected && !selected.component_ref ? selected : fabricatedParts[0] ?? null;

  return <div className="component-library engineering-analysis" data-testid="analysis-workspace">
    <h2>Engineering validation</h2>
    <p>Deterministic structural, modal, thermal, manufacturability, electrical and assembly screening.</p>
    {error && <div className="runtime-banner error"><ShieldAlert size={15}/><div><strong>Validation failed</strong><span>{error}</span></div></div>}
    <div className="campaign-card">
      <div className="campaign-title">{validation?.ok ? <CheckCircle2 size={18}/> : <ShieldAlert size={18}/>}<div><strong>{validation?.ok ? 'Reality checks pass' : 'Engineering risks need attention'}</strong><span>{validation ? `${validation.counts.error} errors · ${validation.counts.warning} warnings · ${validation.counts.info} info` : 'Loading validation…'}</span></div></div>
      <button disabled={busy} onClick={() => void refresh()}><RefreshCw size={13}/> Re-run validation</button>
      {(validation?.risks ?? []).slice(0, 8).map((risk, index) => <div className="history-row" key={`${risk.code}-${index}`}><span>{risk.severity}</span><strong>{risk.message}</strong><small>{risk.code ?? 'engineering_check'}</small></div>)}
    </div>

    {requirements.length > 0 && <div className="campaign-card requirement-gates" data-testid="requirement-gates">
      <strong>Requirement gates</strong>
      <p>Deterministic metrics and recorded physical evidence are evaluated separately; evidence cannot override a failing numeric gate.</p>
      <div className="requirement-list">{requirements.slice(0, 10).map((row, index) => {
        const passed = row.passed === true;
        const failed = row.passed === false;
        const statusText = passed ? 'PASS' : failed ? 'FAIL' : String(row.verification_status ?? 'UNVERIFIED').toUpperCase();
        return <div className="requirement-row" key={String(row.id ?? index)}>
          <span className={`requirement-state ${passed ? 'good' : failed ? 'bad' : ''}`}>{statusText}</span>
          <div><strong>{String(row.statement ?? row.description ?? row.id ?? 'Requirement')}</strong><small>{row.value != null ? `Measured ${String(row.value)} against ${String(row.op ?? '')} ${String(row.target ?? '')}` : String(row.verification_method ?? row.verification ?? 'Verification pending')}</small></div>
        </div>;
      })}</div>
    </div>}

    <div className="campaign-card campaign-console" data-testid="campaign-console">
      <div className="campaign-title"><Activity size={18}/><div><strong>Autonomous variant campaign</strong><span>Generate sibling branches, screen each candidate, independently verify gates, and activate the best unverified result.</span></div></div>
      <div className="campaign-target"><span>Target</span><strong>{campaignTarget?.name ?? 'No fabricated part available'}</strong><small>{selected?.component_ref ? 'Selected object is purchased hardware; ForgeCAD will optimize the first fabricated part instead.' : campaignTarget ? `${campaignTarget.role} · ${campaignTarget.material}` : 'Create or import custom geometry first.'}</small></div>
      <div className="campaign-form">
        <label><span>Objective</span><select value={campaignObjective} onChange={(event) => setCampaignObjective(event.target.value as typeof campaignObjective)}><option value="mass">Minimum mass</option><option value="deflection">Minimum deflection</option><option value="safety">Maximum safety factor</option><option value="temperature">Minimum temperature</option></select></label>
        <label><span>Process</span><select value={campaignProcess} onChange={(event) => setCampaignProcess(event.target.value as typeof campaignProcess)}><option value="cnc">General / CNC</option><option value="fdm">Bambu P2S / FDM</option></select></label>
        <label><span>Load</span><div className="campaign-input"><input value={campaignForce} onChange={(event) => setCampaignForce(event.target.value)} inputMode="decimal"/><b>N</b></div></label>
        <label><span>Max deflection</span><div className="campaign-input"><input value={campaignDeflection} onChange={(event) => setCampaignDeflection(event.target.value)} inputMode="decimal"/><b>mm</b></div></label>
        <label><span>Min yield FoS</span><div className="campaign-input"><input value={campaignFos} onChange={(event) => setCampaignFos(event.target.value)} inputMode="decimal"/><b>×</b></div></label>
        <label><span>Candidates</span><div className="campaign-input"><input value={campaignCandidates} onChange={(event) => setCampaignCandidates(event.target.value)} inputMode="numeric"/><b>3–24</b></div></label>
        {campaignObjective === 'temperature' && <label><span>Max temperature</span><div className="campaign-input"><input value={campaignTemperature} onChange={(event) => setCampaignTemperature(event.target.value)} inputMode="decimal"/><b>°C</b></div></label>}
      </div>
      <div className="campaign-actions"><button onClick={onStartSimulation} disabled={!project?.parts.length || campaignBusy}>Run engineering screen</button><button className="primary-action" data-testid="run-campaign" onClick={() => void startConfiguredCampaign()} disabled={!campaignTarget || campaignBusy}>{campaignBusy ? <Activity size={12} className="agent-spin"/> : <GitCompare size={12}/>}Run variant campaign</button></div>
      <div className="campaign-quick"><button onClick={onStartCampaign} disabled={!campaignTarget || campaignBusy}>Run default campaign</button><span>Uses ForgeCAD's conservative default gates.</span></div>
      {activeJob?.kind === 'campaign' && !campaignResult && <div className="campaign-running"><Activity size={12} className={campaignBusy ? 'agent-spin' : ''}/><div><strong>{activeJob.state}</strong><span>{activeJob.message ?? 'Evaluating design variants…'}</span></div></div>}
    </div>

    {campaignResult && <div className="campaign-card campaign-results" data-testid="campaign-results">
      <div className="campaign-title">{campaignResult.winner_branch ? <Trophy size={18}/> : <XCircle size={18}/>}<div><strong>{campaignResult.winner_branch ? 'Best candidate selected' : 'No feasible candidate'}</strong><span>{campaignResult.winner_branch ? `${campaignResult.winner_branch} · objective ${campaignResult.objective ?? 'mass'}` : 'Every candidate failed at least one deterministic gate.'}</span></div></div>
      <div className="campaign-result-meta"><span>Source <b>{campaignResult.source_branch ?? '—'}</b></span><span>{campaignResult.candidates?.filter((row) => row.feasible).length ?? 0} feasible</span><span>{campaignResult.candidates?.length ?? 0} evaluated</span></div>
      <div className="candidate-list">{(campaignResult.candidates ?? []).map((row, index) => {
        const displacement = row.structural?.max_displacement_mm ?? row.structural?.max_deflection_mm;
        const winner = row.branch === campaignResult.winner_branch;
        const active = project?.active_branch === row.branch;
        const failedGates = Object.entries(row.verifier?.gates ?? {}).filter(([, passed]) => !passed).map(([gate]) => gate);
        return <div className={`candidate-row ${row.feasible ? 'feasible' : 'rejected'} ${winner ? 'winner' : ''}`} key={row.branch}>
          <div className="candidate-rank">{winner ? <Trophy size={12}/> : index + 1}</div>
          <div className="candidate-main"><strong>{row.branch}</strong><small>{parameterSummary(row.parameters)}</small><div className="candidate-metrics"><span>mass {metric(row.metrics?.mass_kg, ' kg', 3)}</span><span>defl. {metric(displacement, ' mm', 3)}</span><span>FoS {metric(row.structural?.yield_fos, '', 2)}</span><span>temp {metric(row.thermal?.max_temperature_c, ' °C', 1)}</span></div>{row.error && <em>{row.error}</em>}{!row.feasible && failedGates.length > 0 && <em>Failed: {failedGates.join(', ')}</em>}</div>
          <div className="candidate-side"><span className={`candidate-state ${row.feasible ? 'good' : 'bad'}`}>{row.feasible ? winner ? 'WINNER' : 'PASS' : 'REJECT'}</span><button disabled={busy || active} onClick={() => void activate(row.branch)}>{active ? 'Active' : 'Open'}</button></div>
        </div>;
      })}</div>
      <div className="campaign-disclaimer"><ShieldAlert size={11}/>Campaign passes are deterministic screening results. The selected branch remains unverified until real-world evidence is recorded and the design is explicitly marked working.</div>
    </div>}

    <div className="campaign-card">
      <strong>Real component registry</strong>
      <p>{stats ? `${stats.total} total components · ${stats.builtin} built in · ${stats.categories.length} categories` : 'Loading registry statistics…'}</p>
      {stats && <p>Geometry fidelity: {Object.entries(stats.geometry_fidelity).map(([key, value]) => `${key} ${value}`).join(' · ')}</p>}
    </div>
  </div>;
}
