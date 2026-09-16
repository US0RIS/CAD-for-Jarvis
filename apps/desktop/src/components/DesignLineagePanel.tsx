import { useMemo, useState } from 'react';
import { Check, CircleAlert, GitBranch, GitCompare, Plus, ShieldCheck, X } from 'lucide-react';
import {
  compareBranch,
  createBranch,
  setBranchStatus,
  type BranchPayload,
  type ProjectPayload,
} from '../api/engine';

type ComparisonPayload = {
  source: string;
  target: string;
  changes: Array<Record<string, unknown>>;
  count: number;
};

function branchStatusLabel(status: BranchPayload['status']) {
  if (status === 'not_working') return 'Not working';
  if (status === 'working') return 'Working';
  return 'Unverified';
}

function summarizeChange(change: Record<string, unknown>) {
  const action = String(change.action ?? change.kind ?? change.type ?? 'changed').replaceAll('_', ' ');
  const subject = String(change.name ?? change.object_name ?? change.object_id ?? change.id ?? change.path ?? 'engineering state');
  return `${action}: ${subject}`;
}

export function DesignLineagePanel({ project, onProject }: { project: ProjectPayload | null; onProject: (project: ProjectPayload) => void }) {
  const [newBranchName, setNewBranchName] = useState('');
  const [compareTarget, setCompareTarget] = useState('');
  const [comparison, setComparison] = useState<ComparisonPayload | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = useMemo(() => project?.branches.find((branch) => branch.active) ?? null, [project]);
  const comparisonCandidates = useMemo(() => (project?.branches ?? []).filter((branch) => !branch.active), [project]);
  const defaultComparison = useMemo(() => {
    const working = comparisonCandidates.find((branch) => branch.status === 'working');
    return working?.name ?? comparisonCandidates[0]?.name ?? '';
  }, [comparisonCandidates]);
  const target = compareTarget || defaultComparison;

  async function create() {
    const name = newBranchName.trim();
    if (!name || busy) return;
    try {
      setBusy('create');
      setError(null);
      setComparison(null);
      const next = await createBranch(name, `Created from ${project?.active_branch ?? 'active design'} in ForgeCAD desktop`);
      onProject(next);
      setNewBranchName('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  async function status(nextStatus: BranchPayload['status']) {
    if (!active || busy) return;
    try {
      setBusy(`status:${nextStatus}`);
      setError(null);
      const result = await setBranchStatus(active.name, nextStatus, 'Set from ForgeCAD design lineage inspector.', active.physical_verified);
      onProject(result.project);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  async function compare() {
    if (!target || busy) return;
    try {
      setBusy('compare');
      setError(null);
      setComparison(await compareBranch(target));
      setCompareTarget(target);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  return <section className="lineage-panel" data-testid="design-lineage-panel" aria-label="Design lineage">
    <div className="lineage-heading">
      <div><GitBranch size={13}/><span><strong>Design lineage</strong><small>Branch known-good designs before risky changes.</small></span></div>
      <span className={`lineage-status ${active?.status ?? 'unverified'}`}>{branchStatusLabel(active?.status ?? 'unverified')}</span>
    </div>

    <div className="lineage-active">
      <div><span>Active branch</span><strong>{active?.name ?? project?.active_branch ?? 'main'}</strong></div>
      <div><span>Commits</span><strong>{active?.commit_count ?? 0}</strong></div>
      <div><span>Physical evidence</span><strong className={active?.physical_verified ? 'verified' : ''}>{active?.physical_verified ? <><ShieldCheck size={11}/>Verified</> : 'Not verified'}</strong></div>
    </div>

    <div className="lineage-actions" aria-label="Branch status">
      <button className={active?.status === 'working' ? 'selected' : ''} disabled={!active || Boolean(busy)} onClick={() => void status('working')}><Check size={11}/>Working</button>
      <button className={active?.status === 'not_working' ? 'selected danger' : ''} disabled={!active || Boolean(busy)} onClick={() => void status('not_working')}><X size={11}/>Not working</button>
      <button className={active?.status === 'unverified' ? 'selected' : ''} disabled={!active || Boolean(busy)} onClick={() => void status('unverified')}>Unverified</button>
    </div>
    <p className="lineage-truth-note">Status is a design label. Physical verification can only come from revision-bound recorded evidence.</p>

    <div className="lineage-create">
      <label htmlFor="new-branch-name">New branch</label>
      <div><input id="new-branch-name" aria-label="New branch name" value={newBranchName} onChange={(event) => setNewBranchName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void create(); } }} placeholder="e.g. lighter-bracket"/><button data-testid="create-design-branch" disabled={!newBranchName.trim() || Boolean(busy)} onClick={() => void create()}><Plus size={11}/>Create</button></div>
      <small>Branches snapshot the complete canonical engineering state, including embedded code.</small>
    </div>

    <div className="lineage-compare">
      <label htmlFor="compare-branch">Compare active branch</label>
      <div><select id="compare-branch" aria-label="Compare active branch to" value={target} disabled={!comparisonCandidates.length || Boolean(busy)} onChange={(event) => { setCompareTarget(event.target.value); setComparison(null); }}>{comparisonCandidates.map((branch) => <option value={branch.name} key={branch.name}>{branch.name} · {branchStatusLabel(branch.status)}</option>)}</select><button data-testid="compare-design-branch" disabled={!target || Boolean(busy)} onClick={() => void compare()}><GitCompare size={11}/>Compare</button></div>
    </div>

    {error && <div className="lineage-error" role="alert"><CircleAlert size={12}/><span>{error}</span></div>}
    {comparison && <div className="lineage-diff" data-testid="design-lineage-diff">
      <div><strong>{comparison.count} canonical {comparison.count === 1 ? 'difference' : 'differences'}</strong><small>{comparison.source} → {comparison.target}</small></div>
      {comparison.count === 0 ? <p>No modeled engineering differences.</p> : <ol>{comparison.changes.slice(0, 8).map((change, index) => <li key={`${index}-${summarizeChange(change)}`}>{summarizeChange(change)}</li>)}</ol>}
      {comparison.count > 8 && <small>+ {comparison.count - 8} more differences</small>}
    </div>}
  </section>;
}
