import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { executeOperation, fetchScene, type ScenePayload } from '../api/engine';
import { fetchSimulationGraph } from '../api/simulation';

export type TransformMode = 'move' | 'rotate' | 'scale';
export type CameraPreset = 'fit' | 'iso' | 'top' | 'front' | 'right';

interface ScenePartRecord {
  id: string;
  object: THREE.Object3D;
  basePosition: THREE.Vector3;
  baseRotation: THREE.Euler;
  baseScale: THREE.Vector3;
  explodeVector: THREE.Vector3;
}

interface SimulationPreviewTransform {
  position?: number[];
  rotation_deg?: number[];
  scale?: number[];
}

interface SimulationPreviewFrame {
  time_s?: number;
  transforms?: Record<string, SimulationPreviewTransform>;
  collisions?: Array<{ a_id?: string; b_id?: string }>;
}

interface SimulationPreviewEventDetail {
  frames?: SimulationPreviewFrame[];
  duration_s?: number;
}

interface RichMaterialDescriptor {
  color?: string | number;
  metalness?: number;
  roughness?: number;
  clearcoat?: number;
  clearcoatRoughness?: number;
  opacity?: number;
  transmission?: number;
  emissive?: string | number;
}

interface RichMeshGroup {
  name?: string;
  triangle_start: number;
  triangle_count: number;
  material_class?: string;
  material?: RichMaterialDescriptor;
}

type RichSceneMesh = ScenePayload['parts'][number]['mesh'] & {
  groups?: RichMeshGroup[];
  geometry_fidelity?: string;
  geometry_source?: string;
  authoritative_cad?: boolean;
  asset_sha256?: string | null;
  subpart_count?: number;
  triangle_count?: number;
};

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

function finiteNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clamp01(value: unknown, fallback: number): number {
  return Math.max(0, Math.min(1, finiteNumber(value, fallback)));
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
  private readonly userHiddenIds = new Set<string>();
  private readonly kinematicChildren = new Map<string, string[]>();
  private readonly kinematicParent = new Map<string, string>();
  private optimisticHiddenIds = new Set<string>();
  private isolatedId: string | null = null;
  private resizeObserver?: ResizeObserver;
  private frameHandle = 0;
  private selectedId: string | null = null;
  private explode = 0;
  private disposed = false;
  private authoritative = false;
  private pointerDownHandler?: (event: PointerEvent) => void;
  private contextMenuHandler?: (event: Event) => void;
  private simulationPreviewHandler?: EventListener;
  private reloadGeneration = 0;
  private hasFramedScene = false;
  private dragRootStartMatrix: THREE.Matrix4 | null = null;
  private readonly dragDescendantStartMatrices = new Map<string, THREE.Matrix4>();
  private simulationPreviewHandle = 0;
  private simulationPreviewRestoreTimer = 0;
  private simulationPreviewGeneration = 0;
  private simulationPreviewActive = false;

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
    this.transform.addEventListener('mouseDown', () => this.beginConstraintDrag());
    this.transform.addEventListener('objectChange', () => this.propagateConstraintDrag());
    this.transform.addEventListener('mouseUp', () => { void this.commitTransform(); });
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);

    this.scene.add(this.assemblyRoot);
    this.installLightingAndGround();
    this.installEvents();
    this.installSimulationPreviewEvents();
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

  private material(role: string, vertexColors: boolean, descriptor?: RichMaterialDescriptor) {
    const opacity = clamp01(descriptor?.opacity, 1);
    const transmission = clamp01(descriptor?.transmission, 0);
    return new THREE.MeshPhysicalMaterial({
      color: descriptor?.color ?? (vertexColors ? 0xffffff : colorForRole(role)),
      metalness: clamp01(descriptor?.metalness, role.includes('structure') || role.includes('mount') ? 0.64 : 0.22),
      roughness: clamp01(descriptor?.roughness, 0.42),
      clearcoat: clamp01(descriptor?.clearcoat, 0.04),
      clearcoatRoughness: clamp01(descriptor?.clearcoatRoughness, 0.25),
      opacity,
      transparent: opacity < 0.999 || transmission > 0.001,
      transmission,
      emissive: descriptor?.emissive ?? 0x000000,
      vertexColors,
      side: THREE.DoubleSide,
    });
  }

  private geometryFromPart(part: ScenePayload['parts'][number]): THREE.BufferGeometry | null {
    const mesh = part.mesh as RichSceneMesh;
    if (!mesh.positions?.length || !mesh.triangles?.length) return null;
    const geometry = new THREE.BufferGeometry();
    const groups = Array.isArray(mesh.groups)
      ? mesh.groups.filter((group) => Number.isFinite(Number(group.triangle_start)) && Number(group.triangle_count) > 0)
      : [];
    const hasGroups = groups.length > 0;
    const hasFaceColors = !hasGroups && Array.isArray(mesh.triangle_colors) && mesh.triangle_colors.length === mesh.triangles.length;

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
      if (hasGroups) {
        geometry.clearGroups();
        groups.forEach((group, materialIndex) => {
          geometry.addGroup(Number(group.triangle_start) * 3, Number(group.triangle_count) * 3, materialIndex);
        });
      }
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

  private materialsFromPart(part: ScenePayload['parts'][number]): THREE.Material | THREE.Material[] {
    const mesh = part.mesh as RichSceneMesh;
    const groups = Array.isArray(mesh.groups)
      ? mesh.groups.filter((group) => Number.isFinite(Number(group.triangle_start)) && Number(group.triangle_count) > 0)
      : [];
    if (groups.length) {
      return groups.map((group) => {
        const material = this.material(part.semantic_role, false, group.material);
        material.name = group.material_class || group.name || 'ForgeCAD component material';
        return material;
      });
    }
    const vertexColors = Boolean(mesh.triangle_colors?.length);
    return this.material(part.semantic_role, vertexColors);
  }

  private applyVisibility() {
    for (const part of this.parts.values()) {
      part.object.visible = !this.optimisticHiddenIds.has(part.id)
        && !this.userHiddenIds.has(part.id)
        && (this.isolatedId == null || part.id === this.isolatedId);
    }
  }

  private rebuildKinematicGraph(edges: Array<{ parent_id?: string; child_id?: string }> = []) {
    this.kinematicChildren.clear();
    this.kinematicParent.clear();
    for (const edge of edges) {
      const parent = String(edge.parent_id ?? '');
      const child = String(edge.child_id ?? '');
      if (!parent || !child || parent === child || !this.parts.has(parent) || !this.parts.has(child)) continue;
      const children = this.kinematicChildren.get(parent) ?? [];
      children.push(child);
      this.kinematicChildren.set(parent, children);
      this.kinematicParent.set(child, parent);
    }
  }

  private descendants(rootId: string): string[] {
    const result: string[] = [];
    const stack = [...(this.kinematicChildren.get(rootId) ?? [])].reverse();
    const seen = new Set<string>();
    while (stack.length) {
      const current = stack.pop();
      if (!current || seen.has(current)) continue;
      seen.add(current);
      result.push(current);
      stack.push(...(this.kinematicChildren.get(current) ?? []).slice().reverse());
    }
    return result;
  }

  private beginConstraintDrag() {
    this.dragRootStartMatrix = null;
    this.dragDescendantStartMatrices.clear();
    if (!this.selectedId || this.explode !== 0 || this.simulationPreviewActive) return;
    if (this.kinematicParent.has(this.selectedId)) return;
    const root = this.parts.get(this.selectedId);
    if (!root) return;
    root.object.updateMatrix();
    this.dragRootStartMatrix = root.object.matrix.clone();
    for (const id of this.descendants(this.selectedId)) {
      const part = this.parts.get(id);
      if (!part) continue;
      part.object.updateMatrix();
      this.dragDescendantStartMatrices.set(id, part.object.matrix.clone());
    }
  }

  private propagateConstraintDrag() {
    if (!this.selectedId || !this.dragRootStartMatrix || !this.dragDescendantStartMatrices.size) return;
    const root = this.parts.get(this.selectedId);
    if (!root) return;
    root.object.updateMatrix();
    const delta = root.object.matrix.clone().multiply(this.dragRootStartMatrix.clone().invert());
    for (const [id, startMatrix] of this.dragDescendantStartMatrices) {
      const part = this.parts.get(id);
      if (!part) continue;
      const matrix = delta.clone().multiply(startMatrix);
      matrix.decompose(part.object.position, part.object.quaternion, part.object.scale);
    }
  }

  private clearConstraintDrag() {
    this.dragRootStartMatrix = null;
    this.dragDescendantStartMatrices.clear();
  }

  private updateBaseTransform(record: ScenePartRecord) {
    record.basePosition.copy(record.object.position);
    record.baseRotation.copy(record.object.rotation);
    record.baseScale.copy(record.object.scale);
  }

  async reload(): Promise<void> {
    const generation = ++this.reloadGeneration;
    this.cancelSimulationPreview(false);
    this.clearConstraintDrag();
    try {
      const [payload, graph] = await Promise.all([
        fetchScene(),
        fetchSimulationGraph().catch(() => null),
      ]);
      if (this.disposed || generation !== this.reloadGeneration) return;
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
        const object = new THREE.Mesh(geometry, this.materialsFromPart(part));
        const { position, rotation, scale } = transformVectors(part);
        object.position.copy(position);
        object.rotation.copy(rotation);
        object.scale.copy(scale);
        object.castShadow = true;
        object.receiveShadow = true;
        object.userData.partId = part.id;
        const richMesh = part.mesh as RichSceneMesh;
        object.userData.componentSubpartCount = richMesh.groups?.length ?? 0;
        object.userData.authoritativeCad = Boolean(richMesh.authoritative_cad);
        object.userData.geometryFidelity = richMesh.geometry_fidelity ?? null;
        object.userData.componentAssetSha256 = richMesh.asset_sha256 ?? null;
        this.assemblyRoot.add(object);
        const explodeVector = new THREE.Vector3(
          Number(part.explode_vector?.[0] ?? 0),
          Number(part.explode_vector?.[1] ?? 0),
          Number(part.explode_vector?.[2] ?? 1),
        );
        if (explodeVector.lengthSq() < 1e-9) explodeVector.set(0, 0, 1);
        this.parts.set(part.id, {
          id: part.id,
          object,
          basePosition: object.position.clone(),
          baseRotation: object.rotation.clone(),
          baseScale: object.scale.clone(),
          explodeVector: explodeVector.normalize(),
        });
      }

      this.rebuildKinematicGraph(graph?.ok ? graph.edges : []);
      for (const hiddenId of [...this.userHiddenIds]) {
        if (!this.parts.has(hiddenId)) this.userHiddenIds.delete(hiddenId);
      }
      if (this.isolatedId && !this.parts.has(this.isolatedId)) this.isolatedId = null;
      if (!this.parts.size) this.hasFramedScene = false;

      this.setExplode(this.explode);
      this.applyVisibility();
      if (!this.hasFramedScene && this.parts.size) {
        this.setCameraPreset('fit');
        this.hasFramedScene = true;
      }
      if (previousSelected && this.parts.has(previousSelected) && !this.optimisticHiddenIds.has(previousSelected)) this.select(previousSelected);
      else if (previousSelected) this.select(null);
      this.events.onReady?.();
    } catch (error) {
      if (generation === this.reloadGeneration) this.events.onError?.(error instanceof Error ? error : new Error(String(error)));
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
      const visible = [...this.parts.values()].filter((part) => part.object.visible).map((part) => part.object);
      const hits = this.raycaster.intersectObjects(visible, true);
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

  private installSimulationPreviewEvents() {
    this.simulationPreviewHandler = ((event: Event) => {
      const detail = (event as CustomEvent<SimulationPreviewEventDetail>).detail;
      if (!detail || !Array.isArray(detail.frames) || !detail.frames.length) return;
      this.playSimulationPreview(detail.frames, finiteNumber(detail.duration_s, 0));
    }) as EventListener;
    window.addEventListener('forgecad:simulation-preview', this.simulationPreviewHandler);
  }

  private updateEmissive(collidingIds: ReadonlySet<string> = new Set()) {
    for (const part of this.parts.values()) {
      const selected = part.id === this.selectedId;
      const colliding = collidingIds.has(part.id);
      part.object.traverse((node) => {
        if (!(node instanceof THREE.Mesh)) return;
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        for (const material of materials) {
          if (!(material instanceof THREE.MeshPhysicalMaterial)) continue;
          material.emissive.setHex(colliding ? 0x5f1717 : selected ? 0x17324d : 0x000000);
        }
      });
    }
  }

  private select(id: string | null) {
    this.selectedId = id;
    this.transform.detach();
    if (id && !this.simulationPreviewActive) {
      const part = this.parts.get(id);
      if (part && part.object.visible && this.explode === 0) this.transform.attach(part.object);
    }
    this.updateEmissive();
    this.events.onSelectionChange?.(id);
  }

  selectPart(id: string | null) {
    if (id && !this.parts.has(id)) return;
    this.select(id);
  }

  setOptimisticHidden(ids: Iterable<string>) {
    this.optimisticHiddenIds = new Set(ids);
    if (this.selectedId && this.optimisticHiddenIds.has(this.selectedId)) this.select(null);
    this.applyVisibility();
  }

  private async commitTransform() {
    if (!this.selectedId || !this.authoritative || this.explode !== 0 || this.simulationPreviewActive) {
      this.clearConstraintDrag();
      return;
    }
    const selectedId = this.selectedId;
    const record = this.parts.get(selectedId);
    if (!record) {
      this.clearConstraintDrag();
      return;
    }
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
      this.updateBaseTransform(record);
      for (const id of this.dragDescendantStartMatrices.keys()) {
        const descendant = this.parts.get(id);
        if (descendant) this.updateBaseTransform(descendant);
      }
    } catch (error) {
      this.events.onError?.(error instanceof Error ? error : new Error(String(error)));
      await this.reload();
      this.selectPart(selectedId);
    } finally {
      this.clearConstraintDrag();
    }
  }

  private restoreCanonicalPose() {
    for (const part of this.parts.values()) {
      part.object.position.copy(part.basePosition);
      part.object.rotation.copy(part.baseRotation);
      part.object.scale.copy(part.baseScale);
    }
    this.updateEmissive();
    if (this.explode !== 0) {
      const amount = this.explode * 0.9;
      for (const part of this.parts.values()) part.object.position.copy(part.basePosition).addScaledVector(part.explodeVector, amount);
    }
    if (this.explode === 0 && this.selectedId) {
      const selected = this.parts.get(this.selectedId);
      if (selected?.object.visible) this.transform.attach(selected.object);
    }
  }

  private cancelSimulationPreview(restore = true) {
    this.simulationPreviewGeneration += 1;
    if (this.simulationPreviewHandle) cancelAnimationFrame(this.simulationPreviewHandle);
    if (this.simulationPreviewRestoreTimer) window.clearTimeout(this.simulationPreviewRestoreTimer);
    this.simulationPreviewHandle = 0;
    this.simulationPreviewRestoreTimer = 0;
    this.simulationPreviewActive = false;
    if (restore) this.restoreCanonicalPose();
  }

  private applyPreviewFrame(a: SimulationPreviewFrame, b: SimulationPreviewFrame, mix: number) {
    const transformsA = a.transforms ?? {};
    const transformsB = b.transforms ?? transformsA;
    const ids = new Set([...Object.keys(transformsA), ...Object.keys(transformsB)]);
    for (const id of ids) {
      const part = this.parts.get(id);
      if (!part) continue;
      const ta = transformsA[id] ?? transformsB[id];
      const tb = transformsB[id] ?? ta;
      if (!ta || !tb) continue;
      const pa = new THREE.Vector3(finiteNumber(ta.position?.[0]), finiteNumber(ta.position?.[1]), finiteNumber(ta.position?.[2]));
      const pb = new THREE.Vector3(finiteNumber(tb.position?.[0]), finiteNumber(tb.position?.[1]), finiteNumber(tb.position?.[2]));
      part.object.position.copy(pa.lerp(pb, mix));

      const ea = new THREE.Euler(
        THREE.MathUtils.degToRad(finiteNumber(ta.rotation_deg?.[0])),
        THREE.MathUtils.degToRad(finiteNumber(ta.rotation_deg?.[1])),
        THREE.MathUtils.degToRad(finiteNumber(ta.rotation_deg?.[2])),
        'XYZ',
      );
      const eb = new THREE.Euler(
        THREE.MathUtils.degToRad(finiteNumber(tb.rotation_deg?.[0])),
        THREE.MathUtils.degToRad(finiteNumber(tb.rotation_deg?.[1])),
        THREE.MathUtils.degToRad(finiteNumber(tb.rotation_deg?.[2])),
        'XYZ',
      );
      const qa = new THREE.Quaternion().setFromEuler(ea);
      const qb = new THREE.Quaternion().setFromEuler(eb);
      part.object.quaternion.copy(qa.slerp(qb, mix));

      const sa = new THREE.Vector3(finiteNumber(ta.scale?.[0], 1), finiteNumber(ta.scale?.[1], 1), finiteNumber(ta.scale?.[2], 1));
      const sb = new THREE.Vector3(finiteNumber(tb.scale?.[0], 1), finiteNumber(tb.scale?.[1], 1), finiteNumber(tb.scale?.[2], 1));
      part.object.scale.copy(sa.lerp(sb, mix));
    }
    const collisionIds = new Set<string>();
    for (const collision of [...(a.collisions ?? []), ...(b.collisions ?? [])]) {
      if (collision.a_id) collisionIds.add(String(collision.a_id));
      if (collision.b_id) collisionIds.add(String(collision.b_id));
    }
    this.updateEmissive(collisionIds);
  }

  playSimulationPreview(frames: SimulationPreviewFrame[], requestedDurationS = 0) {
    if (!frames.length || this.disposed) return;
    this.cancelSimulationPreview(true);
    this.simulationPreviewActive = true;
    this.transform.detach();
    const sorted = [...frames].sort((a, b) => finiteNumber(a.time_s) - finiteNumber(b.time_s));
    const lastTime = Math.max(0, finiteNumber(sorted.at(-1)?.time_s));
    const durationS = requestedDurationS > 0 ? requestedDurationS : lastTime > 0 ? lastTime : 1;
    const sourceDuration = lastTime > 0 ? lastTime : durationS;
    const generation = ++this.simulationPreviewGeneration;
    const start = performance.now();

    const step = (now: number) => {
      if (this.disposed || generation !== this.simulationPreviewGeneration) return;
      const elapsed = Math.min(durationS, Math.max(0, (now - start) / 1000));
      const sourceTime = durationS > 0 ? (elapsed / durationS) * sourceDuration : sourceDuration;
      let upperIndex = sorted.findIndex((frame) => finiteNumber(frame.time_s) >= sourceTime);
      if (upperIndex < 0) upperIndex = sorted.length - 1;
      const lowerIndex = Math.max(0, upperIndex - 1);
      const lower = sorted[lowerIndex] ?? sorted[0];
      const upper = sorted[upperIndex] ?? lower;
      if (!lower || !upper) return;
      const t0 = finiteNumber(lower.time_s);
      const t1 = finiteNumber(upper.time_s, t0);
      const mix = t1 > t0 ? Math.max(0, Math.min(1, (sourceTime - t0) / (t1 - t0))) : 0;
      this.applyPreviewFrame(lower, upper, mix);
      if (elapsed < durationS) {
        this.simulationPreviewHandle = requestAnimationFrame(step);
        return;
      }
      this.simulationPreviewHandle = 0;
      this.simulationPreviewRestoreTimer = window.setTimeout(() => {
        if (generation !== this.simulationPreviewGeneration) return;
        this.simulationPreviewRestoreTimer = 0;
        this.simulationPreviewActive = false;
        this.restoreCanonicalPose();
      }, 650);
    };
    this.simulationPreviewHandle = requestAnimationFrame(step);
  }

  setExplode(value: number) {
    this.explode = Math.max(0, Math.min(100, value));
    if (this.simulationPreviewActive) {
      this.transform.detach();
      return;
    }
    if (this.explode !== 0) this.transform.detach();
    const amount = this.explode * 0.9;
    for (const part of this.parts.values()) {
      part.object.position.copy(part.basePosition).addScaledVector(part.explodeVector, amount);
    }
    if (this.explode === 0 && this.selectedId) {
      const part = this.parts.get(this.selectedId);
      if (part?.object.visible) this.transform.attach(part.object);
    }
  }

  setTransformMode(mode: TransformMode) { this.transform.setMode(mode === 'move' ? 'translate' : mode); }
  setAutoRotate(enabled: boolean) { this.orbit.autoRotate = enabled; this.orbit.autoRotateSpeed = 1.0; }
  isolateSelected() {
    if (!this.selectedId) return;
    this.isolatedId = this.selectedId;
    this.applyVisibility();
  }
  hideSelected() {
    if (!this.selectedId) return;
    this.userHiddenIds.add(this.selectedId);
    this.transform.detach();
    this.applyVisibility();
  }
  showAll() {
    this.isolatedId = null;
    this.userHiddenIds.clear();
    this.applyVisibility();
  }

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
      this.hasFramedScene = true;
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
    this.reloadGeneration += 1;
    this.cancelSimulationPreview(false);
    this.clearConstraintDrag();
    cancelAnimationFrame(this.frameHandle);
    this.resizeObserver?.disconnect();
    if (this.pointerDownHandler) this.canvas.removeEventListener('pointerdown', this.pointerDownHandler);
    if (this.contextMenuHandler) this.canvas.removeEventListener('contextmenu', this.contextMenuHandler);
    if (this.simulationPreviewHandler) window.removeEventListener('forgecad:simulation-preview', this.simulationPreviewHandler);
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
