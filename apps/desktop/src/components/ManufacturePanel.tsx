import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, Box, Check, Download, Printer, RefreshCw, Scissors,
  Wrench, X,
} from 'lucide-react';
import { engineFetch, engineRawFetch, type ProjectPayload } from '../api/engine';
import '../styles/manufacture.css';

type WarningPayload = { code: string; message: string };

type OrientationScreen = {
  recommended?: {
    label: string;
    bounds_mm: number[];
    estimated_support_area_mm2: number;
    overhang_triangles: number;
    footprint_mm2: number;
  } | null;
  evaluated_orientations: number;
  method?: string;
  overhang_threshold_deg?: number;
  limitations?: string[];
};

type ManufacturingPart = {
  id: string;
  name: string;
  kind?: string;
  eligible: boolean;
  fits_build_volume: boolean;
  bounds_mm: number[] | null;
  volume_mm3: number | null;
  material?: {
    design_material?: string;
    direct_fdm_material_match?: boolean;
    requested_filament?: string | null;
  };
  minimum_wall_mm?: number | null;
  wall_thickness_status?: string;
  requires_slicer_validation?: boolean;
  recommended_orientation?: string | null;
  recommended_bounds_mm?: number[] | null;
  estimated_support_area_mm2?: number | null;
  overhang_triangles?: number | null;
  orientation_analysis?: OrientationScreen;
  solid_material_estimate?: {
    filament?: string | null;
    density_g_cm3?: number | null;
    mass_g?: number | null;
    note?: string;
  };
  warnings: WarningPayload[];
};

type ProfileState = { path: string | null; exists: boolean };

type PlatePacking = {
  method?: string;
  spacing_mm?: number;
  plate_count: number;
  all_packable: boolean;
  unplaced_object_ids: string[];
  authoritative_arrangement: boolean;
  note?: string;
  plates?: Array<{
    index: number;
    used_footprint_mm2?: number;
    bed_utilization?: number;
    parts: Array<{
      id: string;
      name: string;
      width_mm: number;
      depth_mm: number;
      orientation?: string | null;
    }>;
  }>;
};

type P2SStatus = {
  resource: {
    id: string;
    manufacturer: string;
    model: string;
    process: string;
    build_volume_mm: number[];
    default_nozzle_mm: number;
    supported_nozzles_mm: number[];
  };
  fabricated_part_count: number;
  parts: ManufacturingPart[];
  all_parts_fit_individually: boolean;
  packing_status: string;
  estimated_plate_count?: number | null;
  plate_packing?: PlatePacking;
  bambu_studio_arrangement_required?: boolean;
  slicer: {
    name: string;
    cli_available: boolean;
    executable: string | null;
    profiles: {
      machine: ProfileState;
      process: ProfileState;
      filaments: ProfileState[];
      complete: boolean;
    };
    ready_for_headless_slice: boolean;
  };
  lan_control: {
    implemented: boolean;
    policy: string;
    note: string;
  };
};

type Props = {
  project: ProjectPayload | null;
  selectedId: string | null;
  onSelectPart: (id: string) => void;
  onDraftRedesign: (part: ManufacturingPart) => void;
};

type PreparedPackage = {
  sha256: string;
  stage: 'geometry-exchange' | 'bambu-studio-sliced';
  filename: string;
  branch: string;
};

function formatDimensions(bounds: number[] | null | undefined) {
  if (!bounds?.length) return '—';
  return bounds.map((value) => `${value.toFixed(value >= 100 ? 0 : 1)}`).join(' × ') + ' mm';
}

function formatArea(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 1000) return `${(value / 1000).toFixed(2)}k mm²`;
  return `${value.toFixed(value >= 100 ? 0 : 1)} mm²`;
}

function basename(path: string | null | undefined) {
  if (!path) return 'Not configured';
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function responseFilename(response: Response, fallback: string) {
  const header = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match?.[1] || fallback;
}

export function ManufacturePanel({ project, selectedId, onSelectPart, onDraftRedesign }: Props) {
  const [status, setStatus] = useState<P2SStatus | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'export' | 'slice' | 'evidence' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [preparedPackage, setPreparedPackage] = useState<PreparedPackage | null>(null);
  const [prototypeNote, setPrototypeNote] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await engineFetch<P2SStatus>('/v2/manufacturing/p2s');
      setStatus(next);
      const eligible = next.parts.filter((part) => part.eligible).map((part) => part.id);
      const preferred = selectedId && eligible.includes(selectedId) ? [selectedId] : eligible;
      setSelected(new Set(preferred));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
  }, [project?.revision, refresh]);

  const selectedParts = useMemo(
    () => status?.parts.filter((part) => selected.has(part.id)) ?? [],
    [selected, status],
  );
  const selectedFit = selectedParts.length > 0 && selectedParts.every((part) => part.fits_build_volume && part.eligible);
  const excludedPurchased = Math.max(0, (project?.parts.length ?? 0) - (status?.fabricated_part_count ?? 0));
  const warningCount = status?.parts.reduce((total, part) => total + part.warnings.length, 0) ?? 0;
  const screenedOrientations = status?.parts.reduce((total, part) => total + (part.orientation_analysis?.evaluated_orientations ?? 0), 0) ?? 0;

  function togglePart(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function export3mf(slice: boolean) {
    if (!selected.size || busy) return;
    setBusy(slice ? 'slice' : 'export');
    setError(null);
    setLastAction(null);
    try {
      const response = await engineRawFetch(
        slice ? '/v2/manufacturing/p2s/slice' : '/v2/manufacturing/p2s/export',
        {
          method: 'POST',
          body: JSON.stringify({ object_ids: Array.from(selected), tolerance_mm: 0.15 }),
        },
      );
      const blob = await response.blob();
      const fallback = `${(project?.name || 'ForgeCAD-Design').replace(/[^a-z0-9._-]+/gi, '-')}-${slice ? 'P2S-sliced' : 'P2S'}.3mf`;
      const filename = responseFilename(response, fallback);
      const sha256 = response.headers.get('X-ForgeCAD-Package-SHA256') ?? '';
      const branch = response.headers.get('X-ForgeCAD-Branch') ?? project?.active_branch ?? 'main';
      const stage = (response.headers.get('X-ForgeCAD-3MF-Stage') === 'bambu-studio-sliced' ? 'bambu-studio-sliced' : 'geometry-exchange') as PreparedPackage['stage'];
      downloadBlob(blob, filename);
      if (/^[0-9a-f]{64}$/i.test(sha256)) setPreparedPackage({ sha256, stage, filename, branch });
      setLastAction(slice ? 'Sliced P2S 3MF prepared by Bambu Studio.' : 'Geometry 3MF exported for Bambu Studio.');
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function recordPrototype(outcome: 'success' | 'failure') {
    if (!preparedPackage || busy) return;
    setBusy('evidence');
    setError(null);
    try {
      const materialNames = Array.from(new Set(selectedParts.map((part) => part.material?.requested_filament || part.material?.design_material).filter(Boolean)));
      await engineFetch('/v2/evidence/manufacturing', {
        method: 'POST',
        body: JSON.stringify({
          package_sha256: preparedPackage.sha256,
          resource_id: status?.resource.id ?? 'bambu-lab-p2s',
          outcome,
          material: materialNames.join(', ') || null,
          machine_profile: status?.slicer.profiles.machine.path ?? null,
          process_profile: status?.slicer.profiles.process.path ?? null,
          filament_profiles: status?.slicer.profiles.filaments.map((profile) => profile.path).filter(Boolean) ?? [],
          slicer: status?.slicer.name ?? 'Bambu Studio',
          observations: prototypeNote.trim() ? [prototypeNote.trim()] : [],
          note: prototypeNote.trim(),
        }),
      });
      setLastAction(`Physical prototype ${outcome} recorded on ${preparedPackage.branch}.`);
      setPrototypeNote('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !status) {
    return <div className="manufacture-panel" data-testid="manufacture-panel">
      <div className="panel-title"><div><strong>Manufacture</strong><small>Bambu Lab P2S</small></div></div>
      <div className="manufacture-loading"><Activity size={14} className="agent-spin"/>Checking printable geometry and local slicer…</div>
    </div>;
  }

  return <div className="manufacture-panel" data-testid="manufacture-panel">
    <div className="panel-title manufacture-title">
      <div><strong>Manufacture</strong><small>{status ? `${status.resource.manufacturer} ${status.resource.model} · ${status.resource.process.toUpperCase()}` : 'Bambu Lab P2S'}</small></div>
      <button className="icon-button" title="Refresh manufacturing status" onClick={() => void refresh()} disabled={loading || Boolean(busy)}><RefreshCw size={13} className={loading ? 'agent-spin' : ''}/></button>
    </div>

    {error && <div className="runtime-banner error manufacture-error"><AlertTriangle size={14}/><div><strong>Manufacturing check failed</strong><span>{error}</span></div></div>}
    {lastAction && <div className="manufacture-success"><Check size={12}/>{lastAction}</div>}

    {status && <div className="manufacture-scroll">
      <section className="property-section">
        <div className="property-section-title">MANUFACTURING RESOURCE</div>
        <div className="manufacture-resource-row">
          <span className="manufacture-resource-icon"><Printer size={17}/></span>
          <div><strong>{status.resource.manufacturer} {status.resource.model}</strong><small>{status.resource.build_volume_mm.join(' × ')} mm build volume</small></div>
          <span className="manufacture-state good">AVAILABLE</span>
        </div>
        <dl className="property-grid manufacture-grid">
          <dt>Nozzle</dt><dd>{status.resource.default_nozzle_mm.toFixed(1)} mm default</dd>
          <dt>Slicer</dt><dd>{status.slicer.name}</dd>
          <dt>CLI</dt><dd>{status.slicer.cli_available ? 'Detected' : 'Not detected'}</dd>
          <dt>Profiles</dt><dd>{status.slicer.profiles.complete ? 'Configured' : 'Incomplete'}</dd>
          <dt>Plates</dt><dd>{status.estimated_plate_count ?? (status.fabricated_part_count ? 'Needs redesign' : '—')}</dd>
          <dt>Orientation</dt><dd>{screenedOrientations ? `${screenedOrientations} poses screened` : 'Not screened'}</dd>
        </dl>
        {status.plate_packing && <div className={`manufacture-packing ${status.plate_packing.all_packable ? 'ready' : 'blocked'}`} data-testid="plate-packing">
          <div><strong>{status.plate_packing.all_packable ? `${status.plate_packing.plate_count} screened plate${status.plate_packing.plate_count === 1 ? '' : 's'}` : `${status.plate_packing.unplaced_object_ids.length} body${status.plate_packing.unplaced_object_ids.length === 1 ? '' : 'ies'} need redesign`}</strong><small>{status.plate_packing.method ?? 'ForgeCAD packing screen'} · {status.plate_packing.spacing_mm ?? 6} mm spacing</small></div>
          <span className={`manufacture-state ${status.plate_packing.all_packable ? 'good' : 'bad'}`}>{status.plate_packing.all_packable ? 'SCREENED' : 'BLOCKED'}</span>
          {(status.plate_packing.plates ?? []).slice(0, 4).map((plate) => <div className="manufacture-plate" key={plate.index}><span>Plate {plate.index}</span><b>{plate.parts.length} part{plate.parts.length === 1 ? '' : 's'}</b><small>{plate.bed_utilization != null ? `${(plate.bed_utilization * 100).toFixed(1)}% footprint` : 'layout screened'}</small></div>)}
          <p>Bambu Studio still owns final arrangement, support generation and slicing.</p>
        </div>}
      </section>

      <section className="property-section manufacture-parts-section">
        <div className="property-section-title manufacture-section-heading"><span>PRINTABLE BODIES</span><span>{status.fabricated_part_count}</span></div>
        <div className="manufacture-summary-line">
          <span>{selected.size} selected</span><span>{excludedPurchased} purchased/reference excluded</span><span>{warningCount} checks</span>
        </div>
        {!status.parts.length ? <div className="manufacture-empty"><Box size={18}/><strong>No fabricated bodies</strong><span>Custom CAD, imported STEP, or explicitly fabricated parts will appear here. Purchased catalog components are never sent to the printer.</span></div> : <div className="manufacture-parts">
          {status.parts.map((part) => {
            const oversize = !part.fits_build_volume;
            const materialWarning = part.material && !part.material.direct_fdm_material_match;
            const orientation = part.orientation_analysis;
            return <div key={part.id} className={`manufacture-part ${selected.has(part.id) ? 'selected' : ''}`} data-testid={`manufacture-part-${part.id}`}>
              <label className="manufacture-part-select">
                <input type="checkbox" checked={selected.has(part.id)} disabled={!part.eligible} onChange={() => togglePart(part.id)}/>
                <span className="manufacture-part-main">
                  <strong>{part.name}</strong>
                  <small>{formatDimensions(part.bounds_mm)}</small>
                </span>
                <span className={`manufacture-state ${oversize ? 'bad' : materialWarning || part.warnings.length ? 'warn' : 'good'}`}>{!part.eligible ? 'INVALID' : oversize ? 'OVERSIZE' : part.warnings.length ? 'CHECK' : 'FIT'}</span>
              </label>
              <div className="manufacture-part-meta"><span>{part.material?.design_material ?? 'material unknown'}</span><span>{part.wall_thickness_status === 'declared' ? `${part.minimum_wall_mm} mm min wall` : 'wall unverified'}</span></div>
              {orientation && <div className="manufacture-orientation" data-testid={`orientation-${part.id}`}>
                <div><span>Recommended pose</span><strong>{part.recommended_orientation ?? 'No fitting orthogonal pose'}</strong></div>
                <dl>
                  <dt>Oriented envelope</dt><dd>{formatDimensions(part.recommended_bounds_mm)}</dd>
                  <dt>Support-risk area</dt><dd>{formatArea(part.estimated_support_area_mm2)}</dd>
                  <dt>Overhang faces</dt><dd>{part.overhang_triangles ?? '—'}</dd>
                  <dt>Solid mass</dt><dd>{part.solid_material_estimate?.mass_g != null ? `${part.solid_material_estimate.mass_g.toFixed(1)} g` : '—'}</dd>
                </dl>
                <small>{orientation.evaluated_orientations} right-handed orthogonal poses · {orientation.method ?? 'mesh overhang screen'}</small>
              </div>}
              {part.warnings.length > 0 && <div className="manufacture-warnings">{part.warnings.slice(0, 3).map((warning) => <div key={`${part.id}-${warning.code}`}><AlertTriangle size={10}/><span>{warning.message}</span></div>)}</div>}
              {(oversize || materialWarning) && <button className="manufacture-repair" onClick={() => { onSelectPart(part.id); onDraftRedesign(part); }}><Wrench size={11}/>Ask Copilot to redesign</button>}
            </div>;
          })}
        </div>}
      </section>

      <section className="property-section">
        <div className="property-section-title">BAMBU STUDIO</div>
        <dl className="property-grid manufacture-grid">
          <dt>Executable</dt><dd title={status.slicer.executable ?? undefined}>{status.slicer.cli_available ? basename(status.slicer.executable) : 'Not found'}</dd>
          <dt>Machine</dt><dd title={status.slicer.profiles.machine.path ?? undefined}>{basename(status.slicer.profiles.machine.path)}</dd>
          <dt>Process</dt><dd title={status.slicer.profiles.process.path ?? undefined}>{basename(status.slicer.profiles.process.path)}</dd>
          <dt>Filament</dt><dd>{status.slicer.profiles.filaments.length ? status.slicer.profiles.filaments.map((profile) => basename(profile.path)).join(', ') : 'Not configured'}</dd>
        </dl>
        <div className={`manufacture-slicer-state ${status.slicer.ready_for_headless_slice ? 'ready' : ''}`}>
          <span className="state-dot"/>
          <div><strong>{status.slicer.ready_for_headless_slice ? 'Headless slicing ready' : 'Geometry export ready; slicer setup incomplete'}</strong><small>{status.slicer.ready_for_headless_slice ? 'ForgeCAD can invoke Bambu Studio with explicit local profiles.' : 'ForgeCAD will not invent machine, process, or filament profiles.'}</small></div>
        </div>
      </section>

      <section className="property-section">
        <div className="property-section-title">PREPARE</div>
        <div className="manufacture-actions">
          <button className="wide-action" disabled={!selected.size || Boolean(busy)} onClick={() => void export3mf(false)}>{busy === 'export' ? <Activity size={13} className="agent-spin"/> : <Download size={13}/>}Export geometry 3MF</button>
          <button className="primary-action manufacture-primary" disabled={!selected.size || !selectedFit || !status.slicer.ready_for_headless_slice || Boolean(busy)} onClick={() => void export3mf(true)}>{busy === 'slice' ? <Activity size={13} className="agent-spin"/> : <Scissors size={13}/>}Slice for P2S</button>
        </div>
        {!selectedFit && selected.size > 0 && <div className="manufacture-hint warning"><AlertTriangle size={10}/>One or more selected bodies exceed the P2S build envelope. Redesign or split them before slicing.</div>}
        <div className="manufacture-hint"><Box size={10}/>3MF export includes fabricated bodies only. Purchased catalog components stay in the assembly but are excluded from the print package.</div>
      </section>

      {preparedPackage && <section className="property-section manufacture-evidence-section" data-testid="manufacture-evidence">
        <div className="property-section-title">PROTOTYPE EVIDENCE</div>
        <div className="manufacture-package-row"><div><strong>{preparedPackage.filename}</strong><span>{preparedPackage.stage.replaceAll('-', ' ')} · branch {preparedPackage.branch}</span></div><button className="icon-button" title="Clear prepared-package evidence target" onClick={() => setPreparedPackage(null)}><X size={11}/></button></div>
        <div className="manufacture-hash" title={preparedPackage.sha256}>SHA-256 {preparedPackage.sha256.slice(0, 12)}…{preparedPackage.sha256.slice(-8)}</div>
        <textarea className="manufacture-evidence-note" value={prototypeNote} onChange={(event) => setPrototypeNote(event.target.value)} placeholder="Prototype observations, fit issues, print failure, measurements…"/>
        <div className="manufacture-evidence-actions">
          <button disabled={Boolean(busy)} onClick={() => void recordPrototype('failure')}><AlertTriangle size={11}/>{busy === 'evidence' ? 'Recording…' : 'Record failed print'}</button>
          <button className="primary-action" disabled={Boolean(busy)} onClick={() => void recordPrototype('success')}><Check size={11}/>{busy === 'evidence' ? 'Recording…' : 'Record successful print'}</button>
        </div>
        <div className="manufacture-hint"><Activity size={10}/>Evidence is attached to this design branch and exact package hash. Recording a successful print does not silently mark the engineering design as physically verified.</div>
      </section>}

      <section className="property-section">
        <div className="property-section-title">PHYSICAL HANDOFF</div>
        <div className="manufacture-handoff"><Printer size={13}/><div><strong>Printer transmission is intentionally gated</strong><span>ForgeCAD prepares and validates the package here. Starting a physical print will require an explicit confirmation once a supported printer-control transport is enabled.</span></div></div>
      </section>
    </div>}
  </div>;
}