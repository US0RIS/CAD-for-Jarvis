import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';

export type TransformMode = 'move' | 'rotate' | 'scale';
export type CameraPreset = 'fit' | 'iso' | 'top' | 'front' | 'right';

interface ScenePartRecord {
  id: string;
  object: THREE.Object3D;
  basePosition: THREE.Vector3;
}

export interface SceneControllerEvents {
  onSelectionChange?: (id: string | null) => void;
  onReady?: () => void;
  onError?: (error: Error) => void;
}

export class SceneController {
  private readonly canvas: HTMLCanvasElement;
  private readonly events: SceneControllerEvents;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly orbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly transformHelper: THREE.Object3D;
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly parts = new Map<string, ScenePartRecord>();
  private resizeObserver?: ResizeObserver;
  private frameHandle = 0;
  private selectedId: string | null = null;
  private explode = 0;

  constructor(canvas: HTMLCanvasElement, events: SceneControllerEvents = {}) {
    this.canvas = canvas;
    this.events = events;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene.background = new THREE.Color('#0a131a');
    this.camera.position.set(7.8, 5.4, 8.6);

    this.orbit = new OrbitControls(this.camera, canvas);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.07;
    this.orbit.target.set(0, 0.3, 0);

    this.transform = new TransformControls(this.camera, canvas);
    this.transform.setSpace('local');
    this.transform.addEventListener('dragging-changed', (event) => {
      this.orbit.enabled = !event.value;
    });
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);

    this.installLighting();
    this.installFixtureAssembly();
    this.installEvents();
    this.fitCamera();
    this.resize();
    this.animate();
    queueMicrotask(() => this.events.onReady?.());
  }

  private installLighting() {
    const hemi = new THREE.HemisphereLight(0xeaf8ff, 0x102018, 1.4);
    this.scene.add(hemi);

    const key = new THREE.DirectionalLight(0xffffff, 4.2);
    key.position.set(5, 8, 7);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0x7fb7ff, 1.35);
    fill.position.set(-5, 3, -4);
    this.scene.add(fill);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 60),
      new THREE.MeshStandardMaterial({ color: 0x0a1218, roughness: 0.96, metalness: 0 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.35;
    floor.receiveShadow = true;
    this.scene.add(floor);

    const grid = new THREE.GridHelper(60, 60, 0x28404b, 0x172831);
    grid.position.y = -1.34;
    this.scene.add(grid);
  }

  private addPart(id: string, object: THREE.Object3D) {
    object.userData.partId = id;
    object.traverse((node) => {
      node.userData.partId = id;
      if (node instanceof THREE.Mesh) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
    this.scene.add(object);
    this.parts.set(id, { id, object, basePosition: object.position.clone() });
  }

  private installFixtureAssembly() {
    const darkMetal = new THREE.MeshStandardMaterial({ color: 0x20272b, metalness: 0.82, roughness: 0.28 });
    const machined = new THREE.MeshStandardMaterial({ color: 0x9da5a8, metalness: 0.95, roughness: 0.22 });
    const pcb = new THREE.MeshStandardMaterial({ color: 0x16663f, metalness: 0.08, roughness: 0.64 });
    const battery = new THREE.MeshStandardMaterial({ color: 0x11181b, metalness: 0.05, roughness: 0.72 });

    const bracket = new THREE.Mesh(new THREE.BoxGeometry(0.45, 4.6, 2.5), machined);
    bracket.position.set(-4.2, 0, 0);
    this.addPart('mounting-bracket', bracket);

    const frame = new THREE.Mesh(new THREE.BoxGeometry(2.4, 3.8, 0.45), darkMetal);
    frame.position.set(2.8, 0.2, 0);
    this.addPart('frame', frame);

    const solenoid = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(2.1, 1.05, 1.15), machined);
    const plunger = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 1.4, 24), machined);
    plunger.rotation.z = Math.PI / 2;
    plunger.position.x = -1.65;
    solenoid.add(body, plunger);
    solenoid.position.set(-0.7, 0.9, 0);
    this.addPart('solenoid', solenoid);

    const pi = new THREE.Group();
    const board = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.12, 1.9), pcb);
    const soc = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.16, 0.65), darkMetal);
    soc.position.y = 0.14;
    pi.add(board, soc);
    pi.position.set(1.0, -0.35, 0.15);
    this.addPart('raspberry-pi', pi);

    const pack = new THREE.Mesh(new THREE.BoxGeometry(2.4, 1.4, 1.15), battery);
    pack.position.set(4.35, 0.85, 0.2);
    this.addPart('battery', pack);

    const latch = new THREE.Mesh(new THREE.BoxGeometry(1.3, 1.7, 1.5), darkMetal);
    latch.position.set(-2.4, -0.35, 0);
    this.addPart('latch-body', latch);
  }

  private installEvents() {
    this.canvas.addEventListener('pointerdown', this.handlePointerDown);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas);
  }

  private handlePointerDown = (event: PointerEvent) => {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const intersections = this.raycaster.intersectObjects([...this.parts.values()].map((p) => p.object), true);
    const id = intersections[0]?.object.userData.partId as string | undefined;
    this.select(id ?? null);
  };

  select(id: string | null) {
    this.selectedId = id;
    this.transform.detach();
    for (const [partId, part] of this.parts) {
      part.object.traverse((node) => {
        if (node instanceof THREE.Mesh) {
          const materials = Array.isArray(node.material) ? node.material : [node.material];
          for (const material of materials) {
            if (material instanceof THREE.MeshStandardMaterial) {
              material.emissive.set(partId === id ? 0x0f5a32 : 0x000000);
              material.emissiveIntensity = partId === id ? 0.55 : 0;
            }
          }
        }
      });
    }
    const selected = id ? this.parts.get(id)?.object : undefined;
    if (selected && this.explode === 0) this.transform.attach(selected);
    this.events.onSelectionChange?.(id);
  }

  setTransformMode(mode: TransformMode) {
    this.transform.setMode(mode === 'move' ? 'translate' : mode);
  }

  setExplode(percent: number) {
    this.explode = THREE.MathUtils.clamp(percent, 0, 100);
    const amount = this.explode / 100;
    for (const part of this.parts.values()) {
      const direction = part.basePosition.clone();
      direction.y *= 0.35;
      if (direction.lengthSq() < 0.01) direction.set(1, 0.2, 0);
      direction.normalize();
      part.object.position.copy(part.basePosition).addScaledVector(direction, amount * 2.25);
    }
    if (this.explode > 0) this.transform.detach();
    else if (this.selectedId) {
      const selected = this.parts.get(this.selectedId)?.object;
      if (selected) this.transform.attach(selected);
    }
  }

  setAutoRotate(enabled: boolean) {
    this.orbit.autoRotate = enabled;
    this.orbit.autoRotateSpeed = 1.2;
  }

  setCameraPreset(preset: CameraPreset) {
    const distance = 10;
    const positions: Record<CameraPreset, THREE.Vector3> = {
      fit: new THREE.Vector3(7.8, 5.4, 8.6),
      iso: new THREE.Vector3(7.8, 5.4, 8.6),
      top: new THREE.Vector3(0, distance, 0.01),
      front: new THREE.Vector3(0, 0.5, distance),
      right: new THREE.Vector3(distance, 0.5, 0),
    };
    this.camera.position.copy(positions[preset]);
    this.orbit.target.set(0, 0, 0);
    this.orbit.update();
  }

  hideSelected() {
    if (!this.selectedId) return;
    const part = this.parts.get(this.selectedId);
    if (part) part.object.visible = false;
  }

  isolateSelected() {
    if (!this.selectedId) return;
    for (const [id, part] of this.parts) part.object.visible = id === this.selectedId;
  }

  showAll() {
    for (const part of this.parts.values()) part.object.visible = true;
  }

  private fitCamera() {
    this.setCameraPreset('fit');
  }

  private resize() {
    const width = Math.max(1, this.canvas.clientWidth);
    const height = Math.max(1, this.canvas.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  private animate = () => {
    this.frameHandle = requestAnimationFrame(this.animate);
    this.orbit.update();
    this.renderer.render(this.scene, this.camera);
  };

  dispose() {
    cancelAnimationFrame(this.frameHandle);
    this.resizeObserver?.disconnect();
    this.canvas.removeEventListener('pointerdown', this.handlePointerDown);
    this.orbit.dispose();
    this.transform.dispose();
    for (const part of this.parts.values()) {
      part.object.traverse((node) => {
        if (!(node instanceof THREE.Mesh)) return;
        node.geometry.dispose();
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        materials.forEach((material) => material.dispose());
      });
    }
    this.renderer.dispose();
  }
}
