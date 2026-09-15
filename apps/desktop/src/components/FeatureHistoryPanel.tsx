import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Copy, Eye, EyeOff, Plus, Trash2, Wrench } from 'lucide-react';
import {
  createCadFeature,
  deleteCadFeature,
  duplicateCadFeature,
  fetchCadFeatures,
  reorderCadFeature,
  suppressCadFeature,
  updateCadFeature,
  type CadFeaturePayload,
} from '../api/engineering';

const divider = '1px solid var(--border-subtle, #22313b)';

type NumericField = { key: string; label: string; defaultValue: number; min?: number; step?: number };
type FeatureTemplate = { type: string; label: string; fields: NumericField[] };

const templates: FeatureTemplate[] = [
  { type: 'hole', label: 'Hole', fields: [
    { key: 'diameter', label: 'Ø', defaultValue: 4, min: .1, step: .1 },
    { key: 'x', label: 'X', defaultValue: 0, step: .5 },
    { key: 'y', label: 'Y', defaultValue: 0, step: .5 },
  ] },
  { type: 'slot', label: 'Slot', fields: [
    { key: 'length', label: 'Length', defaultValue: 20, min: .1, step: .5 },
    { key: 'width', label: 'Width', defaultValue: 5, min: .1, step: .1 },
    { key: 'depth', label: 'Depth', defaultValue: 5, min: .1, step: .1 },
    { key: 'x', label: 'X', defaultValue: 0, step: .5 },
    { key: 'y', label: 'Y', defaultValue: 0, step: .5 },
  ] },
  { type: 'counterbore', label: 'Counterbore', fields: [
    { key: 'diameter', label: 'Hole Ø', defaultValue: 4, min: .1, step: .1 },
    { key: 'counterbore_diameter', label: 'Head Ø', defaultValue: 7, min: .1, step: .1 },
    { key: 'counterbore_depth', label: 'Depth', defaultValue: 2, min: .1, step: .1 },
    { key: 'x', label: 'X', defaultValue: 0, step: .5 },
    { key: 'y', label: 'Y', defaultValue: 0, step: .5 },
  ] },
  { type: 'countersink', label: 'Countersink', fields: [
    { key: 'diameter', label: 'Hole Ø', defaultValue: 4, min: .1, step: .1 },
    { key: 'countersink_diameter', label: 'Sink Ø', defaultValue: 8, min: .1, step: .1 },
    { key: 'angle_deg', label: 'Angle', defaultValue: 90, min: 1, step: 1 },
    { key: 'x', label: 'X', defaultValue: 0, step: .5 },
    { key: 'y', label: 'Y', defaultValue: 0, step: .5 },
  ] },
  { type: 'boss_cylinder', label: 'Cylindrical boss', fields: [
    { key: 'diameter', label: 'Ø', defaultValue: 10, min: .1, step: .1 },
    { key: 'height', label: 'Height', defaultValue: 5, min: .1, step: .1 },
    { key: 'x', label: 'X', defaultValue: 0, step: .5 },
    { key: 'y', label: 'Y', defaultValue: 0, step: .5 },
    { key: 'z', label: 'Z center', defaultValue: 5, step: .5 },
  ] },
  { type: 'fillet', label: 'Fillet', fields: [{ key: 'radius', label: 'Radius', defaultValue: 1, min: .05, step: .05 }] },
  { type: 'chamfer', label: 'Chamfer', fields: [{ key: 'distance', label: 'Distance', defaultValue: 1, min: .05, step: .05 }] },
  { type: 'shell', label: 'Shell', fields: [{ key: 'thickness', label: 'Wall', defaultValue: 1.5, min: .05, step: .05 }] },
];
const defaultTemplate = templates[0]!;

function initialValues(template: FeatureTemplate) {
  return Object.fromEntries(template.fields.map((field) => [field.key, field.defaultValue])) as Record<string, number>;
}

function scalarParameters(feature: CadFeaturePayload) {
  const ignored = new Set(['id', 'type', 'name', 'enabled', 'created_at', 'provenance']);
  return Object.entries(feature).filter(([key, value]) => !ignored.has(key) && (typeof value === 'number' || typeof value === 'string'));
}

export function FeatureHistoryPanel({ objectId, onChanged }: { objectId: string | null; onChanged?: () => void }) {
  const [features, setFeatures] = useState<CadFeaturePayload[]>([]);
  const [templateType, setTemplateType] = useState(defaultTemplate.type);
  const [featureName, setFeatureName] = useState('');
  const [values, setValues] = useState<Record<string, number>>(initialValues(defaultTemplate));
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const template = useMemo(() => templates.find((row) => row.type === templateType) ?? defaultTemplate, [templateType]);
  const reload = useCallback(async () => {
    if (!objectId) { setFeatures([]); return; }
    try {
      const result = await fetchCadFeatures(objectId);
      setFeatures(result.items);
      setError(null);
    } catch (caught) {
      setFeatures([]);
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [objectId]);
  useEffect(() => { void reload(); }, [reload]);

  const chooseTemplate = (type: string) => {
    const next = templates.find((row) => row.type === type) ?? defaultTemplate;
    setTemplateType(next.type);
    setValues(initialValues(next));
  };
  const mutate = async (label: string, action: () => Promise<unknown>) => {
    if (!objectId || busy) return;
    setBusy(label);
    try {
      await action();
      await reload();
      onChanged?.();
      setError(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  };
  const addFeature = () => void mutate('add', async () => {
    await createCadFeature(objectId!, { type: template.type, name: featureName.trim() || template.label, parameters: values });
    setFeatureName('');
  });
  const updateScalar = (feature: CadFeaturePayload, key: string, raw: string) => {
    const previous = feature[key];
    const next = typeof previous === 'number' ? Number(raw) : raw;
    if (typeof previous === 'number' && !Number.isFinite(next as number)) return;
    void mutate(`edit:${feature.id}:${key}`, () => updateCadFeature(objectId!, feature.id, { [key]: next }));
  };

  if (!objectId) return <div style={{ fontSize: 9.5, opacity: .55 }}>Select a fabricated CAD object to edit its feature history.</div>;

  return <div data-testid="feature-history-panel" style={{ borderTop: divider, paddingTop: 7, marginTop: 7 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 5 }}><Wrench size={11}/><span style={{ fontSize: 9, opacity: .6 }}>FEATURE HISTORY</span><span style={{ marginLeft: 'auto', fontSize: 9, opacity: .5 }}>{features.length}</span></div>
    {error ? <div style={{ fontSize: 8.8, color: 'var(--warning, #f1bf55)', marginBottom: 5, lineHeight: 1.3 }}>{error}</div> : null}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginBottom: 5 }}>
      <select aria-label="Feature type" value={templateType} onChange={(event) => chooseTemplate(event.target.value)} style={fieldStyle}>{templates.map((row) => <option key={row.type} value={row.type}>{row.label}</option>)}</select>
      <input aria-label="Feature name" value={featureName} onChange={(event) => setFeatureName(event.target.value)} placeholder={template.label} style={fieldStyle}/>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 4 }}>
      {template.fields.map((field) => <label key={field.key} style={{ fontSize: 8.5, opacity: .8 }}>
        <span style={{ display: 'block', opacity: .55, marginBottom: 2 }}>{field.label}{field.key === 'angle_deg' ? ' deg' : ' mm'}</span>
        <input aria-label={`${template.label} ${field.label}`} type="number" value={values[field.key] ?? field.defaultValue} min={field.min} step={field.step ?? .1} onChange={(event) => setValues((current) => ({ ...current, [field.key]: Number(event.target.value) }))} style={fieldStyle}/>
      </label>)}
    </div>
    <button className="wide-action" data-testid="add-cad-feature" disabled={Boolean(busy)} onClick={addFeature} style={{ marginTop: 5 }}><Plus size={11}/>Add {template.label}</button>

    <div style={{ marginTop: 6 }}>
      {features.length ? features.map((feature, index) => {
        const open = expanded === feature.id;
        const scalars = scalarParameters(feature);
        return <div key={feature.id} data-testid={`feature-row-${feature.id}`} style={{ borderTop: divider, padding: '5px 0' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto', gap: 4, alignItems: 'center' }}>
            <button title={open ? 'Collapse feature' : 'Expand feature'} onClick={() => setExpanded(open ? null : feature.id)} style={iconButtonStyle}>{open ? <ChevronUp size={10}/> : <ChevronDown size={10}/>}</button>
            <button onClick={() => setExpanded(open ? null : feature.id)} style={{ border: 0, background: 'transparent', color: 'inherit', padding: 0, textAlign: 'left', minWidth: 0, cursor: 'pointer' }}>
              <strong style={{ display: 'block', fontSize: 9.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: feature.enabled ? 1 : .45 }}>{feature.name}</strong>
              <span style={{ display: 'block', fontSize: 8, opacity: .45 }}>{index + 1}. {feature.type.replaceAll('_', ' ')}</span>
            </button>
            <div style={{ display: 'flex', gap: 1 }}>
              <button title={feature.enabled ? 'Suppress feature' : 'Unsuppress feature'} disabled={Boolean(busy)} onClick={() => void mutate(`suppress:${feature.id}`, () => suppressCadFeature(objectId, feature.id, feature.enabled))} style={iconButtonStyle}>{feature.enabled ? <Eye size={10}/> : <EyeOff size={10}/>}</button>
              <button title="Duplicate feature" disabled={Boolean(busy)} onClick={() => void mutate(`duplicate:${feature.id}`, () => duplicateCadFeature(objectId, feature.id))} style={iconButtonStyle}><Copy size={10}/></button>
              <button title="Delete feature" disabled={Boolean(busy)} onClick={() => void mutate(`delete:${feature.id}`, () => deleteCadFeature(objectId, feature.id))} style={iconButtonStyle}><Trash2 size={10}/></button>
            </div>
          </div>
          {open ? <div style={{ padding: '5px 0 1px 22px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              {scalars.map(([key, value]) => <label key={`${feature.id}:${key}:${String(value)}`} style={{ fontSize: 8, opacity: .75 }}>
                <span style={{ display: 'block', opacity: .55, marginBottom: 2 }}>{key.replaceAll('_', ' ')}</span>
                <input aria-label={`${feature.name} ${key}`} type={typeof value === 'number' ? 'number' : 'text'} defaultValue={String(value)} onBlur={(event) => { if (event.target.value !== String(value)) updateScalar(feature, key, event.target.value); }} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} style={fieldStyle}/>
              </label>)}
            </div>
            <div style={{ display: 'flex', gap: 4, marginTop: 5 }}><button disabled={Boolean(busy) || index === 0} onClick={() => void mutate(`up:${feature.id}`, () => reorderCadFeature(objectId, feature.id, index - 1))} style={smallButtonStyle}>Move up</button><button disabled={Boolean(busy) || index === features.length - 1} onClick={() => void mutate(`down:${feature.id}`, () => reorderCadFeature(objectId, feature.id, index + 1))} style={smallButtonStyle}>Move down</button></div>
          </div> : null}
        </div>;
      }) : <div style={{ fontSize: 9, opacity: .5, padding: '4px 0' }}>No features. Base geometry is unchanged.</div>}
    </div>
  </div>;
}

const fieldStyle = { width: '100%', minWidth: 0, boxSizing: 'border-box' as const, border: divider, borderRadius: 4, background: 'var(--bg-canvas, #0b1319)', color: 'inherit', fontSize: 9, padding: '4px 5px', outline: 'none' };
const iconButtonStyle = { display: 'grid', placeItems: 'center', width: 18, height: 18, border: 0, borderRadius: 3, background: 'transparent', color: 'inherit', padding: 0, cursor: 'pointer', opacity: .7 };
const smallButtonStyle = { border: divider, borderRadius: 4, background: 'transparent', color: 'inherit', fontSize: 8, padding: '3px 5px', cursor: 'pointer' };
