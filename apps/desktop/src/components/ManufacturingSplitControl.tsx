import { useState } from 'react';
import { Activity, AlertTriangle, GitBranch, Scissors, X } from 'lucide-react';
import { engineFetch, type ProjectPayload } from '../api/engine';

export type SplitEligiblePart = {
  id: string;
  name: string;
  bounds_mm: number[] | null;
};

type SplitPlan = {
  object_id: string;
  object_name: string;
  source_bounds_mm: number[];
  usable_piece_envelope_mm: number[];
  margin_mm: number;
  split_required: boolean;
  grid_counts: number[];
  piece_count: number;
  seam_count: number;
  alignment_pair_count: number;
  alignment_diameter_mm: number;
  alignment_depth_mm: number;
  joint_validation_required: boolean;
  note: string;
};

type SplitResult = {
  source_branch: string;
  split_branch: string;
  source_object_id: string;
  split_group: string;
  piece_ids: string[];
  plan: SplitPlan;
  warnings: string[];
  physical_verification: boolean;
};

type ApplyResponse = {
  split: SplitResult;
  project: ProjectPayload;
};

type Props = {
  part: SplitEligiblePart;
  disabled?: boolean;
  onApplied?: (response: ApplyResponse) => void;
  onError?: (message: string) => void;
};

function dimensions(values: number[] | null | undefined) {
  if (!values?.length) return '—';
  return values.map((value) => value.toFixed(value >= 100 ? 0 : 1)).join(' × ') + ' mm';
}

export function ManufacturingSplitControl({ part, disabled = false, onApplied, onError }: Props) {
  const [plan, setPlan] = useState<SplitPlan | null>(null);
  const [busy, setBusy] = useState<'plan' | 'apply' | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function preview() {
    if (busy || disabled) return;
    setBusy('plan');
    setError(null);
    try {
      const result = await engineFetch<SplitPlan>('/v2/manufacturing/p2s/split-plan', {
        method: 'POST',
        body: JSON.stringify({
          object_id: part.id,
          margin_mm: 8,
          max_pieces: 24,
          alignment_diameter_mm: 3.2,
          alignment_depth_mm: 8,
        }),
      });
      setPlan(result);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      onError?.(message);
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!plan || busy || disabled) return;
    setBusy('apply');
    setError(null);
    try {
      const response = await engineFetch<ApplyResponse>('/v2/manufacturing/p2s/split', {
        method: 'POST',
        body: JSON.stringify({
          object_id: part.id,
          margin_mm: plan.margin_mm,
          max_pieces: Math.max(24, plan.piece_count),
          alignment_diameter_mm: plan.alignment_diameter_mm,
          alignment_depth_mm: plan.alignment_depth_mm,
          create_branch: true,
        }),
      });
      setPlan(null);
      onApplied?.(response);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      onError?.(message);
    } finally {
      setBusy(null);
    }
  }

  if (!plan) {
    return <div className="manufacture-split-control" data-testid={`split-control-${part.id}`}>
      <button className="manufacture-split-button" disabled={disabled || Boolean(busy)} onClick={() => void preview()}>
        {busy === 'plan' ? <Activity size={11} className="agent-spin"/> : <Scissors size={11}/>}Plan P2S split
      </button>
      {error && <small className="manufacture-split-error"><AlertTriangle size={9}/>{error}</small>}
    </div>;
  }

  return <div className="manufacture-split-preview" data-testid={`split-preview-${part.id}`}>
    <div className="manufacture-split-heading">
      <div><strong>P2S split preview</strong><small>{plan.piece_count} physical bodies · grid {plan.grid_counts.join(' × ')}</small></div>
      <button className="icon-button" title="Close split preview" disabled={Boolean(busy)} onClick={() => setPlan(null)}><X size={10}/></button>
    </div>
    <dl>
      <dt>Source envelope</dt><dd>{dimensions(plan.source_bounds_mm)}</dd>
      <dt>Piece envelope</dt><dd>{dimensions(plan.usable_piece_envelope_mm)}</dd>
      <dt>Internal seams</dt><dd>{plan.seam_count}</dd>
      <dt>Alignment pairs</dt><dd>{plan.alignment_pair_count}</dd>
    </dl>
    <div className="manufacture-split-warning"><AlertTriangle size={10}/><span>The split creates actual clipped solids and blind alignment sockets. Seam strength remains unverified and must be engineered/tested.</span></div>
    <button className="primary-action manufacture-split-apply" disabled={disabled || Boolean(busy) || !plan.split_required} onClick={() => void apply()}>
      {busy === 'apply' ? <Activity size={11} className="agent-spin"/> : <GitBranch size={11}/>}Create split branch
    </button>
    {error && <small className="manufacture-split-error"><AlertTriangle size={9}/>{error}</small>}
  </div>;
}
