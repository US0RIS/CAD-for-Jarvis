import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, Focus, Move3d, Orbit, Rotate3d, Scaling, Scan, Square, View } from 'lucide-react';
import { SceneController, type CameraPreset, type TransformMode } from '../scene/SceneController';

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
}

export function Viewport({ explode, onExplode, onSelectionChange, onReady, onLoading, onError, sceneRevision, selectedId, empty }: ViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<SceneController | null>(null);
  const mountedRevision = useRef<string | null>(null);
  const [mode, setMode] = useState<TransformMode>('move');
  const [autoRotate, setAutoRotate] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const controller = new SceneController(canvas, { onSelectionChange, onReady, onError });
      controllerRef.current = controller;
      controller.setExplode(explode);
      mountedRevision.current = sceneRevision;
      onLoading();
      void controller.reload().then(() => controller.selectPart(selectedId));
      return () => {
        controller.dispose();
        controllerRef.current = null;
      };
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  }, []);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!controller || mountedRevision.current === sceneRevision) return;
    mountedRevision.current = sceneRevision;
    onLoading();
    void controller.reload().then(() => controller.selectPart(selectedId));
  }, [sceneRevision]);

  useEffect(() => controllerRef.current?.setExplode(explode), [explode]);
  useEffect(() => controllerRef.current?.selectPart(selectedId), [selectedId]);

  function transform(next: TransformMode) {
    setMode(next);
    controllerRef.current?.setTransformMode(next);
  }
  function preset(next: CameraPreset) { controllerRef.current?.setCameraPreset(next); }

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
        <button className={autoRotate ? 'active' : ''} onClick={() => { const value = !autoRotate; setAutoRotate(value); controllerRef.current?.setAutoRotate(value); }} title="Auto rotate"><Orbit size={14}/></button>
        <button onClick={() => controllerRef.current?.isolateSelected()} disabled={!selectedId} title="Isolate"><Focus size={14}/></button>
        <button onClick={() => controllerRef.current?.hideSelected()} disabled={!selectedId} title="Hide"><EyeOff size={14}/></button>
        <button onClick={() => controllerRef.current?.showAll()} title="Show all"><Eye size={14}/></button>
      </div>
    </div>
    <div className="scene-host">
      <canvas ref={canvasRef} className="scene-canvas" data-testid="scene-canvas"/>
      <div className="axis-gizmo"><b>Z</b><span>X</span><i>Y</i></div>
      {!empty ? <div className="explode-control">
        <span>Explode</span>
        <input aria-label="Explode assembly" data-testid="explode-slider" type="range" min="0" max="100" value={explode} onChange={(event) => onExplode(Number(event.target.value))}/>
        <b data-testid="explode-percent">{explode}%</b>
      </div> : <input className="hidden-slider" aria-label="Explode assembly" data-testid="explode-slider" type="range" min="0" max="100" value="0" readOnly/>}
    </div>
  </div>;
}
