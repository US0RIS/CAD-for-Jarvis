import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Box, Flame, Play } from 'lucide-react';
import type { ProjectPayload } from '../api/engine';
import { runThermalField } from '../api/simulation';

type Result = Record<string, unknown>;

type ThermalSummary = {
  supported?: boolean;
  reason?: string;
  grid?: number[];
  integration_steps?: number;
  actual_timestep_s?: number;
  stability_limit_s?: number;
  temperature?: {
    minimum_c?: number;
    mean_c?: number;
    maximum_c?: number;
    center_c?: number;
    maximum_gradient_k_m?: number;
  };
  energy_balance?: { residual_j?: number; generated_heat_j?: number };
  limitations?: string[];
};

function finite(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be finite`);
  return parsed;
}

function integer(value: string, label: string): number {
  const parsed = Math.trunc(finite(value, label));
  if (parsed < 3 || parsed > 36) throw new Error(`${label} must be between 3 and 36`);
  return parsed;
}

export function ThermalFieldPanel({ project }: { project: ProjectPayload | null }) {
  const parts = project?.parts ?? [];
  const [objectId, setObjectId] = useState('');
  const [duration, setDuration] = useState('60');
  const [timestep, setTimestep] = useState('0.1');
  const [initial, setInitial] = useState('25');
  const [heat, setHeat] = useState('10');
  const [h, setH] = useState('10');
  const [ambient, setAmbient] = useState('25');
  const [emissivity, setEmissivity] = useState('0.8');
  const [nx, setNx] = useState('12');
  const [ny, setNy] = useState('8');
  const [nz, setNz] = useState('6');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const ids = parts.map((part) => part.id);
    if (!ids.length) setObjectId('');
    else if (!ids.includes(objectId)) setObjectId(ids[0] ?? '');
  }, [objectId, parts]);

  const summary = useMemo(() => result as ThermalSummary | null, [result]);
  const temperature = summary?.temperature;

  async function run() {
    if (!objectId || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await runThermalField({
        object_id: objectId,
        duration_s: finite(duration, 'Duration'),
        timestep_s: finite(timestep, 'Timestep'),
        initial_temperature_c: finite(initial, 'Initial temperature'),
        heat_w: finite(heat, 'Heat'),
        convection_h_w_m2k: finite(h, 'Convection coefficient'),
        ambient_temperature_c: finite(ambient, 'Ambient temperature'),
        emissivity: finite(emissivity, 'Emissivity'),
        grid: [integer(nx, 'Nx'), integer(ny, 'Ny'), integer(nz, 'Nz')],
      });
      setResult(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return <div className="campaign-card simulation-workspace" data-testid="thermal-field-workspace">
    <div className="campaign-title">
      <Flame size={18}/>
      <div><strong>3D thermal field</strong><span>Resolve internal transient conduction gradients inside supported solids. This is separate from the assembly thermal network.</span></div>
    </div>
    <div className="simulation-section">
      <div className="simulation-section-heading"><Box size={15}/><div><strong>Field case</strong><span>Exact built-in scope: unfeatured rectangular box solids. Unsupported CAD fails closed.</span></div></div>
      <div className="simulation-input-grid">
        <label className="field"><span>Part</span><select aria-label="Thermal field part" value={objectId} onChange={(event) => setObjectId(event.currentTarget.value)}>{parts.map((part) => <option value={part.id} key={part.id}>{part.name}</option>)}</select></label>
        <label className="field"><span>Heat (W)</span><input aria-label="Thermal field heat" type="number" step="any" value={heat} onChange={(event) => setHeat(event.currentTarget.value)}/></label>
        <label className="field"><span>Initial °C</span><input aria-label="Thermal field initial temperature" type="number" step="any" value={initial} onChange={(event) => setInitial(event.currentTarget.value)}/></label>
        <label className="field"><span>Ambient °C</span><input aria-label="Thermal field ambient temperature" type="number" step="any" value={ambient} onChange={(event) => setAmbient(event.currentTarget.value)}/></label>
        <label className="field"><span>h (W/m²K)</span><input aria-label="Thermal field convection" type="number" min="0" step="any" value={h} onChange={(event) => setH(event.currentTarget.value)}/></label>
        <label className="field"><span>Emissivity</span><input aria-label="Thermal field emissivity" type="number" min="0" max="1" step="any" value={emissivity} onChange={(event) => setEmissivity(event.currentTarget.value)}/></label>
        <label className="field"><span>Duration (s)</span><input aria-label="Thermal field duration" type="number" min="0.001" step="any" value={duration} onChange={(event) => setDuration(event.currentTarget.value)}/></label>
        <label className="field"><span>Requested step (s)</span><input aria-label="Thermal field timestep" type="number" min="0.000001" step="any" value={timestep} onChange={(event) => setTimestep(event.currentTarget.value)}/></label>
        <label className="field"><span>Grid Nx</span><input aria-label="Thermal field grid x" type="number" min="3" max="36" step="1" value={nx} onChange={(event) => setNx(event.currentTarget.value)}/></label>
        <label className="field"><span>Grid Ny</span><input aria-label="Thermal field grid y" type="number" min="3" max="36" step="1" value={ny} onChange={(event) => setNy(event.currentTarget.value)}/></label>
        <label className="field"><span>Grid Nz</span><input aria-label="Thermal field grid z" type="number" min="3" max="36" step="1" value={nz} onChange={(event) => setNz(event.currentTarget.value)}/></label>
      </div>
      <button type="button" disabled={busy || !objectId} onClick={() => void run()}><Play size={13}/>{busy ? 'Solving 3D field…' : 'Run 3D thermal field'}</button>
      <small>The solver reduces the integration timestep automatically when the requested step would violate its conservative explicit stability limit.</small>
    </div>

    {error && <div className="simulation-warning"><AlertTriangle size={14}/><span>{error}</span></div>}
    {summary && summary.supported === false && <div className="simulation-warning" data-testid="thermal-field-unsupported"><AlertTriangle size={14}/><span>{summary.reason ?? 'Selected geometry is outside the built-in thermal field scope.'}</span></div>}
    {summary?.supported === true && temperature && <div className="simulation-section" data-testid="thermal-field-result">
      <div className="campaign-result-meta">
        <span><b>{Number(temperature.minimum_c ?? 0).toFixed(2)} °C</b> min</span>
        <span><b>{Number(temperature.mean_c ?? 0).toFixed(2)} °C</b> mean</span>
        <span><b>{Number(temperature.maximum_c ?? 0).toFixed(2)} °C</b> max</span>
        <span><b>{Number(temperature.maximum_gradient_k_m ?? 0).toFixed(1)} K/m</b> max gradient</span>
        <span><b>{summary.grid?.join('×') ?? '—'}</b> cells</span>
      </div>
      <small>{summary.integration_steps ?? 0} integration steps · actual Δt {Number(summary.actual_timestep_s ?? 0).toPrecision(4)} s · stability limit {Number(summary.stability_limit_s ?? 0).toPrecision(4)} s</small>
      <details><summary>Inspect solver evidence</summary><pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 280, fontSize: 10 }}>{JSON.stringify(result, null, 2).slice(0, 9000)}</pre></details>
    </div>}
    <div className="campaign-disclaimer"><AlertTriangle size={11}/>Uniform volumetric heat and all-surface convection/radiation are explicit case assumptions. The 3D field is a numerical prediction, not physical verification.</div>
  </div>;
}
