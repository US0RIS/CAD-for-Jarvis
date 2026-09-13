import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Gauge } from 'lucide-react';
import { engineFetch } from '../api/engine';

interface ToleranceContributor {
  id: string;
  name: string;
  worst_case_span_share?: number | null;
}

interface ToleranceStack {
  id: string;
  name: string;
  ok: boolean;
  error?: string;
  nominal_mm?: number;
  worst_case?: {
    min_mm?: number;
    max_mm?: number;
    passes_spec?: boolean | null;
    lower_margin_mm?: number | null;
    upper_margin_mm?: number | null;
  };
  rss?: {
    min_mm?: number;
    max_mm?: number;
    passes_spec?: boolean | null;
  };
  statistical?: {
    available?: boolean;
    yield_fraction?: number | null;
    defect_ppm?: number | null;
    cp?: number | null;
    cpk?: number | null;
  };
  contributors?: ToleranceContributor[];
}

interface ToleranceStacksPayload {
  version: string;
  count: number;
  ok: boolean;
  items: ToleranceStack[];
  design_parameter_values: Record<string, number>;
}

function number(value: unknown, digits = 3): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '—';
}

function percent(value: unknown): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(3)}%` : '—';
}

function state(stack: ToleranceStack): { label: string; className: string } {
  if (!stack.ok) return { label: 'INVALID', className: 'bad' };
  const pass = stack.worst_case?.passes_spec;
  if (pass === true) return { label: 'WC PASS', className: 'good' };
  if (pass === false) return { label: 'WC FAIL', className: 'bad' };
  return { label: 'NO SPEC', className: '' };
}

export function ToleranceSummary({ revision }: { revision?: string | null }) {
  const [payload, setPayload] = useState<ToleranceStacksPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    void engineFetch<ToleranceStacksPayload>('/v2/analysis/tolerance-stacks')
      .then((result) => { if (active) setPayload(result); })
      .catch((cause) => {
        if (!active) return;
        setPayload(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => { active = false; };
  }, [revision]);

  return <div className="campaign-card tolerance-summary" data-testid="tolerance-stacks">
    <div className="campaign-title"><Gauge size={18}/><div><strong>Tolerance stacks</strong><span>Worst-case, RSS, and explicit-process statistical capability from canonical design constraints.</span></div></div>
    {error && <div className="history-row"><span>error</span><strong>Tolerance analysis unavailable</strong><small>{error}</small></div>}
    {!error && !payload && <p>Loading tolerance analysis…</p>}
    {!error && payload?.count === 0 && <p>No canonical tolerance stack is defined. Add <code>dimension_tolerance</code> contributors and a <code>tolerance_spec</code> when fit, clearance, preload, or assembled length depends on manufacturing variation.</p>}
    {(payload?.items ?? []).map((stack) => {
      const status = state(stack);
      const sensitivity = [...(stack.contributors ?? [])].sort((a, b) => Number(b.worst_case_span_share ?? 0) - Number(a.worst_case_span_share ?? 0))[0];
      const yieldFraction = stack.statistical?.yield_fraction;
      return <div className="requirement-row" key={stack.id} data-testid={`tolerance-stack-${stack.id}`}>
        <span className={`requirement-state ${status.className}`}>{status.label}</span>
        <div>
          <strong>{stack.name || stack.id}</strong>
          {!stack.ok ? <small>{stack.error ?? 'Tolerance stack could not be solved.'}</small> : <>
            <small>Nominal {number(stack.nominal_mm)} mm · worst case {number(stack.worst_case?.min_mm)}–{number(stack.worst_case?.max_mm)} mm · RSS {number(stack.rss?.min_mm)}–{number(stack.rss?.max_mm)} mm</small>
            <small>{stack.statistical?.available ? `Explicit σ model · yield ${percent(yieldFraction)} · Cpk ${number(stack.statistical?.cpk, 2)} · ${number(stack.statistical?.defect_ppm, 1)} ppm` : 'Statistical yield unavailable until every active contributor has an explicit process σ.'}{sensitivity ? ` · largest WC contributor: ${sensitivity.name}` : ''}</small>
          </>}
        </div>
        {stack.ok && stack.worst_case?.passes_spec === true ? <CheckCircle2 size={15}/> : stack.worst_case?.passes_spec === false || !stack.ok ? <AlertTriangle size={15}/> : null}
      </div>;
    })}
    <div className="campaign-disclaimer"><AlertTriangle size={11}/>RSS is a design-iteration accumulation, not a probability claim. Yield/Cp/Cpk are shown only from explicit sigma values and remain process-model estimates, not physical verification.</div>
  </div>;
}
