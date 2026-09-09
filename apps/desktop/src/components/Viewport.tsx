import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, Focus, Move3d, Orbit, Rotate3d, Scaling, Scan, Square, View } from 'lucide-react';
import { SceneController, type CameraPreset, type TransformMode } from '../scene/SceneController';

interface ViewportProps {
  explode: number;
  onExplode: (value: number) => void;
  onSelectionChange: (id: string | null) => void;
  onReady: () => void;
  onError: (error: Error) => void;
}

export function Viewport({ explode, onExplode, onSelectionChange, onReady, onError }: ViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<SceneController | null>(null);
  const [mode, setMode] = useState<TransformMode>('move');
  const [autoRotate, setAutoRotate] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const controller = new SceneController(canvas, { onSelectionChange, onReady, onError });
      controllerRef.current = controller;
      controller.setExplode(explode);
      return () => {
        controller.dispose();
        controllerRef.current = null;
      };
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  }, []); // one renderer per canvas lifetime

  useEffect(() => controllerRef.current?.setExplode(explode), [explode]);

  function transform(next: TransformMode) {
    setMode(next);
    controllerRef.current?.setTransformMode(next);
  }

  function preset(next: CameraPreset) {
    controllerRef.current?.setCameraPreset(next);
  }

  return (
    <div className="viewport-panel" data-testid="viewport-panel">
      <div className="viewport-toolbar">
        <button className={mode === 'move' ? 'active' : ''} onClick={() => transform('move')}><Move3d size={14}/>Move</button>
        <button className={mode === 'rotate' ? 'active' : ''} onClick={() => transform('rotate')}><Rotate3d size={14}/>Rotate</button>
        <button className={mode === 'scale' ? 'active' : ''} onClick={() => transform('scale')}><Scaling size={14}/>Scale</button>
        <span className="sep"/>
        <button onClick={() => preset('fit')}><Scan size={14}/>Fit</button>
        <button onClick={() => preset('iso')}><View size={14}/>Iso</button>
        <button onClick={() => preset('top')}><Square size={14}/>Top</button>
        <button onClick={() => preset('front')}><Square size={14}/>Front</button>
        <button onClick={() => preset('right')}><Square size={14}/>Right</button>
        <span className="sep"/>
        <button className={autoRotate ? 'active' : ''} onClick={() => { const value = !autoRotate; setAutoRotate(value); controllerRef.current?.setAutoRotate(value); }}><Orbit size={14}/>Auto rotate</button>
        <button onClick={() => controllerRef.current?.isolateSelected()}><Focus size={14}/>Isolate</button>
        <button onClick={() => controllerRef.current?.hideSelected()}><EyeOff size={14}/>Hide</button>
        <button onClick={() => controllerRef.current?.showAll()}><Eye size={14}/>Show all</button>
      </div>
      <div className="scene-host">
        <canvas ref={canvasRef} className="scene-canvas" data-testid="scene-canvas"/>
        <div className="axis-gizmo"><b>Z</b><span>X</span><i>Y</i></div>
        <div className="explode-control">
          <div><span>Explode</span><b data-testid="explode-percent">{explode}%</b></div>
          <input aria-label="Explode assembly" data-testid="explode-slider" type="range" min="0" max="100" value={explode} onChange={(event) => onExplode(Number(event.target.value))}/>
        </div>
      </div>
    </div>
  );
}
