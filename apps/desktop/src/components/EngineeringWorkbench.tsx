import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, CheckCircle2, Download, FileUp, GitCompare, PackageOpen, RefreshCw, ShieldAlert, Upload } from 'lucide-react';
import {
  compareBranch,
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

interface Props {
  mode: 'design' | 'analysis';
  project: ProjectPayload | null;
  selectedId: string | null;
  activeJob: JobPayload | null;
  onProject: (project: ProjectPayload) => void;
  onStartSimulation: () => void;
  onStartCampaign: () => void;
}

function ResultBlock({ value }: { value: unknown }) {
  if (value == null) return null;
  const text = JSON.stringify(value, null, 2);
  return <pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 230, fontSize: 11 }}>{text.length > 6500 ? `${text.slice(0, 6500)}\n…` : text}</pre>;
}

export function EngineeringWorkbench({ mode, project, selectedId, activeJob, onProject, onStartSimulation, onStartCampaign }: Props) {
  const [validation, setValidation] = useState<ValidationPayload | null>(null);
  const [stats, setStats] = useState<RegistryStatsPayload | null>(null);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stepInput = useRef<HTMLInputElement | null>(null);
  const bundleInput = useRef<HTMLInputElement | null>(null);
  const activeBranch = project?.branches.find((branch) => branch.active) ?? null;
  const workingBranch = project?.branches.find((branch) => branch.status === 'working' && !branch.active) ?? project?.branches.find((branch) => branch.status === 'working') ?? null;
  const selected = useMemo(() => project?.parts.find((part) => part.id === selectedId) ?? null, [project, selectedId]);

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

  return <div className="component-library" data-testid="analysis-workspace">
    <h2>Engineering validation</h2>
    <p>Deterministic structural, modal, thermal, manufacturability, electrical and assembly screening.</p>
    {error && <div className="runtime-banner error"><ShieldAlert size={15}/><div><strong>Validation failed</strong><span>{error}</span></div></div>}
    <div className="campaign-card">
      <div className="campaign-title">{validation?.ok ? <CheckCircle2 size={18}/> : <ShieldAlert size={18}/>}<div><strong>{validation?.ok ? 'Reality checks pass' : 'Engineering risks need attention'}</strong><span>{validation ? `${validation.counts.error} errors · ${validation.counts.warning} warnings · ${validation.counts.info} info` : 'Loading validation…'}</span></div></div>
      <button disabled={busy} onClick={() => void refresh()}><RefreshCw size={13}/> Re-run validation</button>
      {(validation?.risks ?? []).slice(0, 8).map((risk, index) => <div className="history-row" key={`${risk.code}-${index}`}><span>{risk.severity}</span><strong>{risk.message}</strong><small>{risk.code ?? 'engineering_check'}</small></div>)}
    </div>

    <div className="campaign-card">
      <div className="campaign-title"><Activity size={18}/><div><strong>Analysis + optimization</strong><span>Real solver jobs run off the UI thread and are versioned with the design.</span></div></div>
      <div className="filter-row"><button onClick={onStartSimulation}>Run engineering screen</button><button onClick={onStartCampaign}>Optimize variant</button></div>
      {activeJob && <><p>{activeJob.kind}: {activeJob.state} · {activeJob.message ?? ''}</p><ResultBlock value={activeJob.result}/></>}
    </div>

    <div className="campaign-card">
      <strong>Real component registry</strong>
      <p>{stats ? `${stats.total} total components · ${stats.builtin} built in · ${stats.categories.length} categories` : 'Loading registry statistics…'}</p>
      {stats && <p>Geometry fidelity: {Object.entries(stats.geometry_fidelity).map(([key, value]) => `${key} ${value}`).join(' · ')}</p>}
    </div>
  </div>;
}
