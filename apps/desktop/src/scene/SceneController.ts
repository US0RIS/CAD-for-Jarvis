import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { executeOperation, fetchScene, type ScenePayload } from '../api/engine';

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

function colorForRole(role: string) {
  const value = role.toLowerCase();
  if (value.includes('compute') || value.includes('controller')) return 0x4f7f6d;
  if (value.includes('power')) return 0x9a7c43;
  if (value.includes('solenoid') || value.includes('actuator')) return 0x4c6f92;
  if (value.includes('driver')) return 0x6d6087;
  if (value.includes('structure') || value.includes('mount')) return 0x8b9096;
  return 0x687985;
}

function transformVectors(part: ScenePayload['parts'][number]) {
  const base = part.base_transform ?? { position: [0, 0, 0], rotation_deg: [0, 0, 0], scale: [1, 1, 1] };
  const position = new THREE.Vector3(
    Number(base.position?.[0] ?? 0),
    Number(base.position?.[1] ?? 0),
    Number(base.position?.[2] ?? 0),
  );
  const rotation = new THREE.Euler(
    THREE.MathUtils.degToRad(Number(base.rotation_deg?.[0] ?? 0)),
    THREE.MathUtils.degToRad(Number(base.rotation_deg?.[1] ?? 0)),
    THREE.MathUtils.degToRad(Number(base.rotation_deg?.[2] ?? 0)),
    'XYZ',
  );
  const scale = new THREE.Vector3(
    Number(base.scale?.[0] ?? 1) || 1,
    Number(base.scale?.[1] ?? 1) || 1,
    Number(base.scale?.[2] ?? 1) || 1,
  );
  return { position, rotation, scale };
}

export class SceneController {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly orbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly transformHelper: THREE.Object3D;
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly parts = new Map<string, ScenePartRecord>();
  private readonly assemblyRoot = new THREE.Group();
  private resizeObserver?: ResizeObserver;
  private frameHandle = 0;
  private selectedId: string | null = null;
  private explode = 0;
  private disposed = false;
  private authoritative = false;
  private pointerDownHandler?: (event: PointerEvent) => void;
  private contextMenuHandler?: (event: Event) => void;

  private static detectSoftwareRenderer(): boolean {
    try {
      const probeCanvas = document.createElement('canvas');
      const probe = probeCanvas.getContext('webgl2') ?? probeCanvas.getContext('webgl');
      if (!probe) return false;
      const info = probe.getExtension('WEBGL_debug_renderer_info');
      const rendererString = String(info ? probe.getParameter(info.UNMASKED_RENDERER_WEBGL) : probe.getParameter(probe.RENDERER));
      return /swiftshader|llvmpipe|software|basic render/i.test(rendererString);
    } catch {
      return false;
    }
  }

  constructor(private readonly canvas: HTMLCanvasElement, private readonly events: SceneControllerEvents = {}) {
    const software = SceneController.detectSoftwareRenderer();
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: !software, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = !software;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene.background = new THREE.Color(0x1b1e23);

    if (!software) {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }

    this.camera.up.set(0, 0, 1);
    this.camera.position.set(260, -300, 240);
    this.orbit = new OrbitControls(this.camera, canvas);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.065;
    this.orbit.target.set(0, 0, 0);
    this.orbit.minDistance = 2;
    this.orbit.maxDistance = 5000;

    this.transform = new TransformControls(this.camera, canvas);
    this.transform.setSpace('world');
    this.transform.setSize(0.72);
    this.transform.addEventListener('dragging-changed', (event) => { this.orbit.enabled = !event.value; });
    this.transform.addEventListener('mouseUp', () => { void this.commitTransform(); });
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);

    this.scene.add(this.assemblyRoot);
    this.installLightingAndGround();
    this.installEvents();
    this.resize();
    this.animate();
  }

  private installLightingAndGround() {
    const key = new THREE.DirectionalLight(0xffffff, 2.6);
    key.position.set(260, -190, 360);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 1;
    key.shadow.camera.far = 1400;
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0xb8d4e8, 1.2);
    fill.position.set(-260, 160, 190);
    this.scene.add(fill);

    const ambient = new THREE.HemisphereLight(0xd7e1e8, 0x202329, 1.45);
    this.scene.add(ambient);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(1600, 1600),
      new THREE.MeshPhysicalMaterial({ color: 0x1a1d22, roughness: 0.96, metalness: 0.02 }),
    );
    floor.position.z = -4;
    floor.receiveShadow = true;
    this.scene.add(floor);

    const grid = new THREE.GridHelper(1600, 80, 0x535b65, 0x343a42);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -3.8;
    (grid.material as THREE.Material).opacity = 0.46;
    (grid.material as THREE.Material).transparent = true;
    this.scene.add(grid);
  }

  private material(role: string, vertexColors: boolean) {
    return new THREE.MeshPhysicalMaterial({
      color: vertexColors ? 0xffffff : colorForRole(role),
      metalness: role.includes('structure') || role.includes('mount') ? 0.64 : 0.22,
      roughness: 0.42,
      clearcoat: 0.04,
      vertexColors,
      side: THREE.DoubleSide,
    });
  }

  private geometryFromPart(part: ScenePayload['parts'][number]): THREE.BufferGeometry | null {
    const mesh = part.mesh;
    if (!mesh.positions?.length || !mesh.triangles?.length) return null;
    const geometry = new THREE.BufferGeometry();
    const hasFaceColors = Array.isArray(mesh.triangle_colors) && mesh.triangle_colors.length === mesh.triangles.length;
    if (hasFaceColors) {
      const positions: number[] = [];
      const colors: number[] = [];
      mesh.triangles.forEach((triangle, index) => {
        const color = new THREE.Color(mesh.triangle_colors?.[index] ?? '#7f8b94');
        triangle.forEach((vertexIndex) => {
          const vertex = mesh.positions[vertexIndex];
          if (!vertex) return;
          positions.push(Number(vertex[0]), Number(vertex[1]), Number(vertex[2]));
          colors.push(color.r, color.g, color.b);
        });
      });
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    } else {
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(mesh.positions.flat().map(Number), 3));
      geometry.setIndex(mesh.triangles.flat().map(Number));
    }

    const { position, rotation, scale } = transformVectors(part);
    const quaternion = new THREE.Quaternion().setFromEuler(rotation);
    const worldMatrix = new THREE.Matrix4().compose(position, quaternion, scale);
    geometry.applyMatrix4(worldMatrix.clone().invert());
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    return geometry;
  }

  async reload(): Promise<void> {
    try {
      const payload = await fetchScene();
      if (this.disposed) return;
      const previousSelected = this.selectedId;
      this.authoritative = Boolean(payload.authoritative);
      this.transform.detach();
      this.parts.clear();
      while (this.assemblyRoot.children.length) {
        const child = this.assemblyRoot.children.pop();
        if (!child) break;
        child.traverse((node) => {
          if (node instanceof THREE.Mesh) {
            node.geometry.dispose();
            const material = node.material;
            if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
            else material.dispose();
          }
        });
      }

      for (const part of payload.parts) {
        const geometry = this.geometryFromPart(part);
        if (!geometry) continue;
        const vertexColors = Boolean(part.mesh.triangle_colors?.length);
        const object = new THREE.Mesh(geometry, this.material(part.semantic_role, vertexColors));
        const { position, rotation, scale } = transformVectors(part);
        object.position.copy(position);
        object.rotation.copy(rotation);
        object.scale.copy(scale);
        object.castShadow = true;
        object.receiveShadow = true;
        object.userData.partId = part.id;
        this.assemblyRoot.add(object);
        const explodeVector = new THREE.Vector3(
          Number(part.explode_vector?.[0] ?? 0),
          Number(part.explode_vector?.[1] ?? 0),
          Number(part.explode_vector?.[2] ?? 1),
        );
        if (explodeVector.lengthSq() < 1e-9) explodeVector.set(0, 0, 1);
        this.parts.set(part.id, { id: part.id, object, basePosition: object.position.clone(), explodeVector: explodeVector.normalize() });
      }
      this.setExplode(this.explode);
      if (this.parts.size) this.setCameraPreset('fit');
      if (previousSelected && this.parts.has(previousSelected)) this.select(previousSelected);
      else this.selectedId = null;
      this.events.onReady?.();
    } catch (error) {
      this.events.onError?.(error instanceof Error ? error : new Error(String(error)));
    }
  }

  private installEvents() {
    this.pointerDownHandler = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (this.transform.dragging || this.transform.axis) return;
      const rect = this.canvas.getBoundingClientRect();
      this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hits = this.raycaster.intersectObjects([...this.parts.values()].map((part) => part.object), true);
      const id = hits[0]?.object.userData.partId as string | undefined;
      this.select(id ?? null);
    };
    this.canvas.addEventListener('pointerdown', this.pointerDownHandler);
    this.canvas.dataset.listenerInstalled = 'true';
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas.parentElement ?? this.canvas);
    this.contextMenuHandler = (event: Event) => event.preventDefault();
    this.canvas.addEventListener('contextmenu', this.contextMenuHandler);
  }

  private select(id: string | null) {
    this.selectedId = id;
    this.transform.detach();
    if (id) {
      const part = this.parts.get(id);
      if (part && this.explode === 0) this.transform.attach(part.object);
    }
    for (const part of this.parts.values()) {
      const selected = part.id === id;
      part.object.traverse((node) => {
        if (!(node instanceof THREE.Mesh)) return;
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        for (const material of materials) {
          if (material instanceof THREE.MeshPhysicalMaterial) material.emissive.setHex(selected ? 0x17324d : 0x000000);
        }
      });
    }
    this.events.onSelectionChange?.(id);
  }

  selectPart(id: string | null) {
    if (id && !this.parts.has(id)) return;
    this.select(id);
  }

  private async commitTransform() {
    if (!this.selectedId || !this.authoritative || this.explode !== 0) return;
    const selectedId = this.selectedId;
    const record = this.parts.get(selectedId);
    if (!record) return;
    const object = record.object;
    const args = {
      id: selectedId,
      position: [object.position.x, object.position.y, object.position.z],
      rotation_deg: [
        THREE.MathUtils.radToDeg(object.rotation.x),
        THREE.MathUtils.radToDeg(object.rotation.y),
        THREE.MathUtils.radToDeg(object.rotation.z),
      ],
      scale: [object.scale.x, object.scale.y, object.scale.z],
    };
    try {
      await executeOperation('transform', args, 'Viewport transform');
      await this.reload();
      this.selectPart(selectedId);
    } catch (error) {
      this.events.onError?.(error instanceof Error ? error : new Error(String(error)));
      await this.reload();
      this.selectPart(selectedId);
    }
  }

  setExplode(value: number) {
    this.explode = Math.max(0, Math.min(100, value));
    if (this.explode !== 0) this.transform.detach();
    const amount = this.explode * 0.9;
    for (const part of this.parts.values()) {
      part.object.position.copy(part.basePosition).addScaledVector(part.explodeVector, amount);
    }
    if (this.explode === 0 && this.selectedId) {
      const part = this.parts.get(this.selectedId);
      if (part) this.transform.attach(part.object);
    }
  }

  setTransformMode(mode: TransformMode) { this.transform.setMode(mode === 'move' ? 'translate' : mode); }
  setAutoRotate(enabled: boolean) { this.orbit.autoRotate = enabled; this.orbit.autoRotateSpeed = 1.0; }
  isolateSelected() { if (this.selectedId) for (const part of this.parts.values()) part.object.visible = part.id === this.selectedId; }
  hideSelected() { if (this.selectedId) { const part = this.parts.get(this.selectedId); if (part) part.object.visible = false; this.transform.detach(); } }
  showAll() { for (const part of this.parts.values()) part.object.visible = true; }

  setCameraPreset(preset: CameraPreset) {
    if (preset === 'fit') {
      const box = new THREE.Box3().setFromObject(this.assemblyRoot);
      if (box.isEmpty()) return;
      const sphere = new THREE.Sphere();
      box.getBoundingSphere(sphere);
      const radius = Math.max(sphere.radius, 1);
      this.orbit.target.copy(sphere.center);
      this.camera.position.copy(sphere.center).add(new THREE.Vector3(radius * 1.7, -radius * 2.0, radius * 1.45));
      this.camera.near = Math.max(0.05, radius / 1000);
      this.camera.far = Math.max(2000, radius * 20);
      this.camera.updateProjectionMatrix();
      this.orbit.update();
      return;
    }
    const center = this.orbit.target.clone();
    const distance = Math.max(this.camera.position.distanceTo(center), 80);
    const direction = preset === 'top' ? new THREE.Vector3(0, 0, 1)
      : preset === 'front' ? new THREE.Vector3(0, -1, 0)
      : preset === 'right' ? new THREE.Vector3(1, 0, 0)
      : new THREE.Vector3(1, -1.2, 0.9).normalize();
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.camera.up.set(0, 0, 1);
    this.orbit.update();
  }

  private resize() {
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private animate = () => {
    this.frameHandle = requestAnimationFrame(this.animate);
    this.orbit.update();
    this.renderer.render(this.scene, this.camera);
  };

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frameHandle);
    this.resizeObserver?.disconnect();
    if (this.pointerDownHandler) this.canvas.removeEventListener('pointerdown', this.pointerDownHandler);
    if (this.contextMenuHandler) this.canvas.removeEventListener('contextmenu', this.contextMenuHandler);
    this.transform.detach();
    this.transform.dispose();
    this.orbit.dispose();
    this.scene.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      node.geometry.dispose();
      const material = node.material;
      if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
      else material.dispose();
    });
    this.renderer.dispose();
  }
}