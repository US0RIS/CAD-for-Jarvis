import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, Focus, Move3d, Orbit, Rotate3d, Scaling, Scan, Square, View } from 'lucide-react';
import { fetchComponentAssetRevision, hasNewResolvedGeometry, type ComponentAssetRevision } from '../api/componentFidelity';
import { SceneController, type CameraPreset, type TransformMode } from '../scene/SceneController';
import '../styles/scene-startup.css';

const EMPTY_HIDDEN_IDS: ReadonlySet<string> = new Set();
const SLOW_SCENE_MS = 8_000;
const AUTO_RETRY_MS = 900;
const COMPONENT_FIDELITY_POLL_MS = 1_500;

interface ViewportProps {
  explode: number;
  onExplode: (value: number) => void;
  onSelectionChange: (id: string | null) => void;
  onReady: () => void;
  onLoading: () => void;
  onError: (error: Error) => void;
  sceneRevision: string;
  selectedId: string | null;
  empty: boolean;
  optimisticHiddenIds?: ReadonlySet<string>;
}

export function Viewport({ explode, onExplode, onSelectionChange, onReady, onLoading, onError, sceneRevision, selectedId, empty, optimisticHiddenIds = EMPTY_HIDDEN_IDS }: ViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<SceneController | null>(null);
  const mountedRevision = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(selectedId);
  const callbacksRef = useRef({ onSelectionChange, onReady, onLoading, onError });
  const slowTimerRef = useRef<number | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const automaticRetriesRef = useRef(0);
  const exactCadRevisionRef = useRef<ComponentAssetRevision | null>(null);
  const [mode, setMode] = useState<TransformMode>('move');
  const [autoRotate, setAutoRotate] = useState(false);
  const [sceneSlow, setSceneSlow] = useState(false);
  const [sceneError, setSceneError] = useState<string | null>(null);

  callbacksRef.current = { onSelectionChange, onReady, onLoading, onError };

  function clearSlowTimer() {
    if (slowTimerRef.current != null) {
      window.clearTimeout(slowTimerRef.current);
      slowTimerRef.current = null;
    }
  }

  function beginLoading() {
    clearSlowTimer();
    setSceneSlow(false);
    setSceneError(null);
    callbacksRef.current.onLoading();
    slowTimerRef.current = window.setTimeout(() => {
      slowTimerRef.current = null;
      setSceneSlow(true);
    }, SLOW_SCENE_MS);
  }

  function reloadScene(controller: SceneController) {
    beginLoading();
    void controller.reload().then(() => controller.selectPart(selectedIdRef.current));
  }

  function sceneReady() {
    clearSlowTimer();
    if (retryTimerRef.current != null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    automaticRetriesRef.current = 0;
    setSceneSlow(false);
    setSceneError(null);
    callbacksRef.current.onReady();
  }

  function sceneFailed(error: Error) {
    clearSlowTimer();
    setSceneSlow(false);
    setSceneError(error.message || 'ForgeCAD could not build the 3D scene.');
    callbacksRef.current.onError(error);

    // Recover once automatically from transient engine/session failures. The engine
    // client de-duplicates an in-flight /v2/scene promise, so this cannot create a
    // parallel tessellation storm if the original request is still settling.
    if (automaticRetriesRef.current < 1 && retryTimerRef.current == null) {
      automaticRetriesRef.current += 1;
      retryTimerRef.current = window.setTimeout(() => {
        retryTimerRef.current = null;
        const controller = controllerRef.current;
        if (controller) reloadScene(controller);
      }, AUTO_RETRY_MS);
    }
  }

  useEffect(() => {
    selectedIdRef.current = selectedId;
    controllerRef.current?.selectPart(selectedId);
  }, [selectedId]);

  const sceneEnabled = sceneRevision !== 'loading';
  useEffect(() => {
    if (!sceneEnabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const controller = new SceneController(canvas, {
        onSelectionChange: (id) => callbacksRef.current.onSelectionChange(id),
        onReady: sceneReady,
        onError: sceneFailed,
      });
      controllerRef.current = controller;
      controller.setExplode(explode);
      controller.setOptimisticHidden(optimisticHiddenIds);
      mountedRevision.current = sceneRevision;
      automaticRetriesRef.current = 0;
      reloadScene(controller);
      return () => {
        clearSlowTimer();
        if (retryTimerRef.current != null) window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
        controller.dispose();
        controllerRef.current = null;
      };
    } catch (error) {
      sceneFailed(error instanceof Error ? error : new Error(String(error)));
    }
  }, [sceneEnabled]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!controller || mountedRevision.current === sceneRevision) return;
    mountedRevision.current = sceneRevision;
    automaticRetriesRef.current = 0;
    reloadScene(controller);
  }, [sceneRevision]);

  // Exact vendor CAD resolves in the engine background so the first viewport never
  // blocks on a manufacturer website. This polls an O(1) process revision endpoint;
  // it does not re-import large STEP assemblies. A generation advance means a new
  // exact asset passed verification. An epoch change means the engine restarted, so a
  // scene built against the previous process is refreshed even if generation reset.
  useEffect(() => {
    if (!sceneEnabled || empty) return;
    let cancelled = false;
    let inFlight = false;
    const poll = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const payload = await fetchComponentAssetRevision();
        if (cancelled) return;
        const next: ComponentAssetRevision = { epoch: payload.epoch, generation: payload.generation };
        const shouldReload = hasNewResolvedGeometry(exactCadRevisionRef.current, next);
        exactCadRevisionRef.current = next;
        if (!shouldReload) return;
        const controller = controllerRef.current;
        if (controller) reloadScene(controller);
      } catch {
        // Fidelity polling is opportunistic. Normal scene/project errors remain visible
        // through the existing viewport/runtime error paths; a transient poll failure
        // must not degrade CAD editing.
      } finally {
        inFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, COMPONENT_FIDELITY_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sceneEnabled, empty]);

  useEffect(() => controllerRef.current?.setExplode(explode), [explode]);
  useEffect(() => controllerRef.current?.setOptimisticHidden(optimisticHiddenIds), [optimisticHiddenIds]);

  function transform(next: TransformMode) {
    setMode(next);
    controllerRef.current?.setTransformMode(next);
  }
  function preset(next: CameraPreset) { controllerRef.current?.setCameraPreset(next); }
  function retryScene() {
    const controller = controllerRef.current;
    if (!controller) return;
    automaticRetriesRef.current = 0;
    if (retryTimerRef.current != null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    reloadScene(controller);
  }

  return <div className="viewport-panel" data-testid="viewport-panel">
    <div className="viewport-toolbar">
      <div className="viewport-tool-group">
        <button className={mode === 'move' ? 'active' : ''} onClick={() => transform('move')} title="Move"><Move3d size={14}/><span>Move</span></button>
        <button className={mode === 'rotate' ? 'active' : ''} onClick={() => transform('rotate')} title="Rotate"><Rotate3d size={14}/><span>Rotate</span></button>
        <button className={mode === 'scale' ? 'active' : ''} onClick={() => transform('scale')} title="Scale"><Scaling size={14}/><span>Scale</span></button>
      </div>
      <span className="toolbar-separator"/>
      <div className="viewport-tool-group">
        <button onClick={() => preset('fit')} title="Fit"><Scan size={14}/><span>Fit</span></button>
        <button onClick={() => preset('iso')} title="Isometric"><View size={14}/><span>Iso</span></button>
        <button onClick={() => preset('top')} title="Top"><Square size={14}/><span>Top</span></button>
        <button onClick={() => preset('front')} title="Front"><Square size={14}/><span>Front</span></button>
        <button onClick={() => preset('right')} title="Right"><Square size={14}/><span>Right</span></button>
      </div>
      <span className="toolbar-separator"/>
      <div className="viewport-tool-group compact-tools">
        <button className={autoRotate ? 'active' : ''} onClick={() => { const value = !autoRotate; setAutoRotate(value); controllerRef.current?.setAutoRotate(value); }} title="Auto rotate" aria-label="Auto rotate"><Orbit size={14}/></button>
        <button onClick={() => controllerRef.current?.isolateSelected()} disabled={!selectedId} title="Isolate" aria-label="Isolate selected object"><Focus size={14}/></button>
        <button onClick={() => controllerRef.current?.hideSelected()} disabled={!selectedId} title="Hide" aria-label="Hide selected object"><EyeOff size={14}/></button>
        <button onClick={() => controllerRef.current?.showAll()} title="Show all" aria-label="Show all objects"><Eye size={14}/></button>
      </div>
    </div>
    <div className="scene-host">
      <canvas ref={canvasRef} className="scene-canvas" data-testid="scene-canvas"/>
      <div className="axis-gizmo"><b>Z</b><span>X</span><i>Y</i></div>
      {sceneSlow && !sceneError && <div className="scene-startup-overlay slow" data-testid="scene-startup-slow"><strong>Building 3D geometry…</strong><span>This assembly is taking longer than expected. ForgeCAD is still working; cached geometry will make subsequent launches substantially faster.</span></div>}
      {sceneError && <div className="scene-startup-overlay error" data-testid="scene-startup-error"><strong>3D scene did not finish</strong><span>{sceneError}</span><button data-testid="retry-3d" onClick={retryScene}>Retry 3D</button></div>}
      {!empty ? <div className="explode-control">
        <span>Explode</span>
        <input aria-label="Explode assembly" data-testid="explode-slider" type="range" min="0" max="100" value={explode} onChange={(event) => onExplode(Number(event.target.value))}/>
        <b data-testid="explode-percent">{explode}%</b>
      </div> : <input className="hidden-slider" aria-label="Explode assembly" data-testid="explode-slider" type="range" min="0" max="100" value="0" readOnly/>}
    </div>
  </div>;
}
