import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export type TransformMode = 'move' | 'rotate' | 'scale';
export type CameraPreset = 'fit' | 'iso' | 'top' | 'front' | 'right';

interface ScenePartRecord {
  id: string;
  object: THREE.Object3D;
  basePosition: THREE.Vector3;
  explodeVector: THREE.Vector3;
}

export interface SceneControllerEvents {
  onSelectionChange?: (id: string | null) => void;
  onReady?: () => void;
  onError?: (error: Error) => void;
}

export class SceneController {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(38, 1, 0.02, 1000);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly orbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly transformHelper: THREE.Object3D;
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly parts = new Map<string, ScenePartRecord>();
  private readonly flexibleLinks: THREE.Mesh[] = [];
  private resizeObserver?: ResizeObserver;
  private frameHandle = 0;
  private selectedId: string | null = null;
  private explode = 0;

  private static detectSoftwareRenderer(): boolean {
    try {
      // A canvas can only ever bind one rendering context, and its attributes (antialias,
      // alpha, powerPreference) are fixed by whichever getContext() call wins - so probe on a
      // throwaway, never-attached canvas rather than the real one the WebGLRenderer below owns.
      const probe = document.createElement('canvas').getContext('webgl2') ?? document.createElement('canvas').getContext('webgl');
      if (!probe) return false;
      const info = probe.getExtension('WEBGL_debug_renderer_info');
      const rendererString = String(info ? probe.getParameter(info.UNMASKED_RENDERER_WEBGL) : probe.getParameter(probe.RENDERER));
      return /swiftshader|llvmpipe|software|basic render/i.test(rendererString);
    } catch {
      return false;
    }
  }

  constructor(private readonly canvas: HTMLCanvasElement, private readonly events: SceneControllerEvents = {}) {
    // A software GL rasterizer (SwiftShader/llvmpipe - what headless/GPU-less CI runners and
    // some real Windows machines without a working GPU driver fall back to) cannot keep up with
    // per-frame MSAA resolve + soft shadow map passes on this scene: each becomes a blocking
    // "GPU stall due to ReadPixels" that recurs every single animation frame indefinitely,
    // starving the whole tab's main thread (timers, React commits, everything) for minutes at a
    // time. Detect that case and drop to a cheap-but-correct render path; real, hardware-
    // accelerated GPUs (the overwhelming majority of real users) are unaffected.
    const isSoftwareRenderer = SceneController.detectSoftwareRenderer();
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: !isSoftwareRenderer, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = !isSoftwareRenderer;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene.background = new THREE.Color(0x071017);
    this.scene.fog = new THREE.FogExp2(0x071017, 0.012);

    if (!isSoftwareRenderer) {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }

    this.camera.position.set(8.8, 5.6, 9.8);
    this.orbit = new OrbitControls(this.camera, canvas);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.065;
    this.orbit.target.set(0, -0.45, 0);
    this.orbit.minDistance = 3;
    this.orbit.maxDistance = 30;

    this.transform = new TransformControls(this.camera, canvas);
    this.transform.setSpace('local');
    this.transform.setSize(0.72);
    this.transform.addEventListener('dragging-changed', (event) => { this.orbit.enabled = !event.value; });
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);

    this.installLightingAndGround();
    this.installAssembly();
    this.installEvents();
    this.resize();
    this.setCameraPreset('iso');
    this.animate();
    queueMicrotask(() => this.events.onReady?.());
  }

  private metal(color: number, roughness = 0.24) {
    return new THREE.MeshPhysicalMaterial({ color, metalness: 0.94, roughness, clearcoat: 0.14, clearcoatRoughness: 0.2 });
  }

  private polymer(color: number, roughness = 0.5) {
    return new THREE.MeshPhysicalMaterial({ color, metalness: 0.04, roughness, clearcoat: 0.08 });
  }

  private rounded(size: [number, number, number], radius: number, material: THREE.Material) {
    return new THREE.Mesh(new RoundedBoxGeometry(...size, 5, radius), material);
  }

  private installLightingAndGround() {
    const key = new THREE.DirectionalLight(0xffffff, 3.3);
    key.position.set(7, 10, 9);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = 35;
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x7bd6ff, 1.8);
    rim.position.set(-7, 5, -6);
    this.scene.add(rim);

    const green = new THREE.PointLight(0x54ff9a, 4.2, 7, 2);
    green.position.set(-1.8, 1.4, 2.8);
    this.scene.add(green);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(80, 80),
      new THREE.MeshPhysicalMaterial({ color: 0x081118, roughness: 0.92, metalness: 0.06 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.66;
    floor.receiveShadow = true;
    this.scene.add(floor);

    const grid = new THREE.GridHelper(80, 80, 0x244653, 0x132a33);
    grid.position.y = -1.645;
    (grid.material as THREE.Material).opacity = 0.27;
    (grid.material as THREE.Material).transparent = true;
    this.scene.add(grid);
  }

  private register(id: string, object: THREE.Object3D, explodeVector: THREE.Vector3) {
    object.userData.partId = id;
    object.traverse((node) => {
      node.userData.partId = id;
      if (node instanceof THREE.Mesh) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
    this.scene.add(object);
    this.parts.set(id, { id, object, basePosition: object.position.clone(), explodeVector: explodeVector.clone().normalize() });
  }

  private fastener(parent: THREE.Group, position: THREE.Vector3, length = 0.34) {
    const material = this.metal(0xc9ced1, 0.16);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, length, 18), material);
    const head = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.07, 24), material);
    head.position.y = length / 2 + 0.035;
    const group = new THREE.Group();
    group.add(shaft, head);
    group.position.copy(position);
    parent.add(group);
  }

  private installAssembly() {
    // STRUCTURE: one grounded L-shaped chassis. Every mounted component rests on it.
    const structure = new THREE.Group();
    const base = this.rounded([8.6, 0.20, 4.15], 0.08, this.metal(0x777f84, 0.29));
    base.position.y = -1.52;
    structure.add(base);

    const stop = this.rounded([0.30, 2.50, 3.20], 0.07, this.metal(0xaab1b5, 0.22));
    stop.position.set(3.55, -0.16, 0);
    structure.add(stop);

    for (const z of [-1.35, 1.35]) {
      const foot = this.rounded([0.78, 1.25, 0.18], 0.04, this.metal(0x687177, 0.31));
      foot.position.set(3.18, -0.89, z);
      foot.rotation.z = -0.56;
      structure.add(foot);
    }

    for (const z of [-1.25, 1.25]) {
      const darkInsert = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.035, 28), this.polymer(0x080b0d, 0.75));
      darkInsert.rotation.z = Math.PI / 2;
      darkInsert.position.set(3.39, 0.18, z);
      structure.add(darkInsert);
    }

    this.fastener(structure, new THREE.Vector3(-3.45, -1.34, -1.45));
    this.fastener(structure, new THREE.Vector3(-3.45, -1.34, 1.45));
    this.fastener(structure, new THREE.Vector3(2.85, -1.34, -1.45));
    this.fastener(structure, new THREE.Vector3(2.85, -1.34, 1.45));
    this.register('mounting-bracket', structure, new THREE.Vector3(0, 0, 0));

    // LATCH: seated on the base and aligned with the vertical stop.
    const latch = new THREE.Group();
    const latchBlock = this.rounded([1.25, 1.04, 1.30], 0.11, this.metal(0x252b30, 0.31));
    latch.add(latchBlock);
    const latchShaft = new THREE.Mesh(new THREE.CylinderGeometry(0.20, 0.20, 1.45, 28), this.metal(0xc5c9cb, 0.17));
    latchShaft.rotation.z = Math.PI / 2;
    latchShaft.position.x = 0.95;
    latch.add(latchShaft);
    const latchFace = this.rounded([0.22, 0.66, 0.82], 0.05, this.metal(0x11171b, 0.38));
    latchFace.position.x = -0.72;
    latch.add(latchFace);
    latch.position.set(2.18, -0.82, 0);
    this.register('latch-body', latch, new THREE.Vector3(1, 0.28, 0));

    // SOLENOID: body sits on the same base; plunger points directly into the latch.
    const solenoid = new THREE.Group();
    const cage = this.rounded([1.85, 0.98, 1.12], 0.08, this.metal(0xb5a876, 0.30));
    solenoid.add(cage);
    const coil = this.rounded([1.34, 0.76, 0.92], 0.07, this.polymer(0x183d5d, 0.38));
    coil.position.x = -0.06;
    solenoid.add(coil);
    const plunger = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 1.55, 30), this.metal(0xd1d3d4, 0.13));
    plunger.rotation.z = Math.PI / 2;
    plunger.position.x = 1.28;
    solenoid.add(plunger);
    const springMaterial = this.metal(0xcdd0d2, 0.20);
    for (let i = 0; i < 7; i += 1) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.25, 0.03, 10, 32), springMaterial);
      ring.rotation.y = Math.PI / 2;
      ring.position.x = 0.78 + i * 0.13;
      solenoid.add(ring);
    }
    solenoid.position.set(0.18, -0.84, 0);
    this.register('solenoid', solenoid, new THREE.Vector3(-0.65, 0.36, 0));

    // RASPBERRY PI: horizontal PCB on four real standoffs, not floating in space.
    const pi = new THREE.Group();
    const board = this.rounded([2.70, 0.10, 1.82], 0.055, this.polymer(0x146b43, 0.48));
    pi.add(board);
    const soc = this.rounded([0.70, 0.18, 0.70], 0.05, this.metal(0x222629, 0.34));
    soc.position.set(0, 0.16, 0.08);
    pi.add(soc);
    for (const [x, z, w, d] of [[-1.02, -0.57, 0.50, 0.44], [1.00, -0.55, 0.58, 0.44], [1.00, 0.55, 0.58, 0.44], [-0.86, 0.60, 0.68, 0.30]] as const) {
      const connector = this.rounded([w, 0.22, d], 0.04, this.metal(0xc7c9c9, 0.18));
      connector.position.set(x, 0.17, z);
      pi.add(connector);
    }
    const gpio = this.rounded([1.82, 0.22, 0.21], 0.03, this.polymer(0x111517, 0.38));
    gpio.position.set(-0.10, 0.21, -0.76);
    pi.add(gpio);
    for (let i = 0; i < 20; i += 1) {
      const pin = new THREE.Mesh(new THREE.BoxGeometry(0.032, 0.16, 0.032), this.metal(0xd2ad45, 0.24));
      pin.position.set(-0.98 + i * 0.098, 0.36, -0.76);
      pi.add(pin);
    }
    const standoffMaterial = this.metal(0xd0d4d6, 0.22);
    for (const x of [-1.08, 1.08]) for (const z of [-0.65, 0.65]) {
      const standoff = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.27, 16), standoffMaterial);
      standoff.position.set(x, -0.18, z);
      pi.add(standoff);
    }
    pi.position.set(-2.20, -1.17, -0.78);
    this.register('raspberry-pi', pi, new THREE.Vector3(-0.78, 0.22, -0.72));

    // BATTERY: mounted on the back-left of the same base.
    const battery = new THREE.Group();
    const pack = this.rounded([2.05, 1.06, 1.16], 0.14, this.polymer(0x12181d, 0.43));
    battery.add(pack);
    const strap = this.rounded([0.22, 1.10, 1.20], 0.035, this.polymer(0x30383d, 0.62));
    battery.add(strap);
    const terminal = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.18, 18), this.metal(0xaeb5b8, 0.24));
    terminal.rotation.z = Math.PI / 2;
    terminal.position.set(1.10, 0.20, 0.30);
    battery.add(terminal);
    battery.position.set(-2.45, -0.66, 1.12);
    this.register('battery', battery, new THREE.Vector3(-0.78, 0.25, 0.72));

    // Flexible wiring belongs to the assembled presentation only. Fade it out before
    // exploded components make a static cable path physically misleading.
    const redMaterial = new THREE.MeshPhysicalMaterial({ color: 0xdb2525, roughness: 0.46, metalness: 0.02, transparent: true });
    const redCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-1.45, -0.50, 1.05),
      new THREE.Vector3(-0.95, -0.38, 1.25),
      new THREE.Vector3(-0.45, -0.48, 0.68),
      new THREE.Vector3(-0.55, -0.58, 0.30),
    ]);
    const redWire = new THREE.Mesh(new THREE.TubeGeometry(redCurve, 42, 0.035, 9, false), redMaterial);
    redWire.castShadow = true;
    this.scene.add(redWire);
    this.flexibleLinks.push(redWire);

    const blackMaterial = new THREE.MeshPhysicalMaterial({ color: 0x171b1d, roughness: 0.50, metalness: 0.02, transparent: true });
    const blackCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-1.55, -0.72, 0.88),
      new THREE.Vector3(-1.80, -0.88, 0.25),
      new THREE.Vector3(-2.05, -0.90, -0.15),
      new THREE.Vector3(-2.20, -0.95, -0.45),
    ]);
    const blackWire = new THREE.Mesh(new THREE.TubeGeometry(blackCurve, 36, 0.032, 8, false), blackMaterial);
    this.scene.add(blackWire);
    this.flexibleLinks.push(blackWire);
  }

  private installEvents() {
    this.canvas.addEventListener('pointerdown', this.handlePointerDown);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas);
  }

  private handlePointerDown = (event: PointerEvent) => {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const intersections = this.raycaster.intersectObjects([...this.parts.values()].map((part) => part.object), true);
    const id = intersections[0]?.object.userData.partId as string | undefined;
    this.select(id ?? null);
  };

  select(id: string | null) {
    this.selectedId = id;
    this.transform.detach();
    for (const [partId, part] of this.parts) {
      part.object.traverse((node) => {
        if (!(node instanceof THREE.Mesh)) return;
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        for (const material of materials) {
          if (material instanceof THREE.MeshStandardMaterial) {
            material.emissive.set(partId === id ? 0x0b5e35 : 0x000000);
            material.emissiveIntensity = partId === id ? 0.48 : 0;
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
      part.object.position.copy(part.basePosition).addScaledVector(part.explodeVector, amount * 3.0);
    }
    const wireOpacity = 1 - THREE.MathUtils.smoothstep(this.explode, 4, 30);
    for (const link of this.flexibleLinks) {
      const material = link.material;
      if (material instanceof THREE.Material) material.opacity = wireOpacity;
      link.visible = wireOpacity > 0.02;
    }
    if (this.explode > 0) this.transform.detach();
    else if (this.selectedId) {
      const selected = this.parts.get(this.selectedId)?.object;
      if (selected) this.transform.attach(selected);
    }
  }

  setAutoRotate(enabled: boolean) {
    this.orbit.autoRotate = enabled;
    this.orbit.autoRotateSpeed = 1.0;
  }

  private frameVisible(direction: THREE.Vector3, margin = 1.25) {
    const box = new THREE.Box3();
    let hasVisible = false;
    for (const part of this.parts.values()) {
      if (!part.object.visible) continue;
      box.expandByObject(part.object);
      hasVisible = true;
    }
    if (!hasVisible || box.isEmpty()) return;
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);
    const radius = Math.max(0.8, sphere.radius);
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const distance = (radius / Math.sin(fov / 2)) * margin;
    const dir = direction.clone().normalize();
    this.orbit.target.copy(sphere.center);
    this.camera.position.copy(sphere.center).addScaledVector(dir, distance);
    this.camera.near = Math.max(0.02, distance - radius * 2.4);
    this.camera.far = distance + radius * 6 + 20;
    this.camera.updateProjectionMatrix();
    this.orbit.update();
  }

  setCameraPreset(preset: CameraPreset) {
    const directions: Record<CameraPreset, THREE.Vector3> = {
      fit: this.camera.position.clone().sub(this.orbit.target),
      iso: new THREE.Vector3(1.25, 0.82, 1.35),
      top: new THREE.Vector3(0.001, 1, 0.001),
      front: new THREE.Vector3(0, 0.08, 1),
      right: new THREE.Vector3(1, 0.08, 0),
    };
    this.frameVisible(directions[preset], preset === 'fit' ? 1.16 : 1.24);
  }

  hideSelected() {
    if (!this.selectedId) return;
    const part = this.parts.get(this.selectedId);
    if (part) part.object.visible = false;
    this.transform.detach();
  }

  isolateSelected() {
    if (!this.selectedId) return;
    for (const [id, part] of this.parts) part.object.visible = id === this.selectedId;
    this.setCameraPreset('fit');
  }

  showAll() {
    for (const part of this.parts.values()) part.object.visible = true;
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
    for (const link of this.flexibleLinks) {
      link.geometry.dispose();
      const materials = Array.isArray(link.material) ? link.material : [link.material];
      materials.forEach((material) => material.dispose());
    }
    this.renderer.dispose();
  }
}
