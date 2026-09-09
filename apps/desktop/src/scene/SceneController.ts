import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export type TransformMode = 'move' | 'rotate' | 'scale';
export type CameraPreset = 'fit' | 'iso' | 'top' | 'front' | 'right';

interface ScenePartRecord { id: string; object: THREE.Object3D; basePosition: THREE.Vector3; }
export interface SceneControllerEvents { onSelectionChange?: (id: string | null) => void; onReady?: () => void; onError?: (error: Error) => void; }

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
  private resizeObserver?: ResizeObserver;
  private frameHandle = 0;
  private selectedId: string | null = null;
  private explode = 0;

  constructor(private readonly canvas: HTMLCanvasElement, private readonly events: SceneControllerEvents = {}) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene.background = new THREE.Color(0x071017);
    this.scene.fog = new THREE.FogExp2(0x071017, 0.018);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();

    this.camera.position.set(8.8, 5.6, 9.8);
    this.orbit = new OrbitControls(this.camera, canvas);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.065;
    this.orbit.target.set(0, 0.2, 0);
    this.orbit.minDistance = 4;
    this.orbit.maxDistance = 28;

    this.transform = new TransformControls(this.camera, canvas);
    this.transform.setSpace('local');
    this.transform.setSize(0.72);
    this.transform.addEventListener('dragging-changed', (event) => { this.orbit.enabled = !event.value; });
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);

    this.installLighting();
    this.installAssembly();
    this.installEvents();
    this.setCameraPreset('iso');
    this.resize();
    this.animate();
    queueMicrotask(() => this.events.onReady?.());
  }

  private metal(color: number, roughness = 0.24) { return new THREE.MeshPhysicalMaterial({ color, metalness: 0.94, roughness, clearcoat: 0.14, clearcoatRoughness: 0.2 }); }
  private polymer(color: number, roughness = 0.5) { return new THREE.MeshPhysicalMaterial({ color, metalness: 0.04, roughness, clearcoat: 0.08 }); }
  private rounded(size: [number, number, number], radius: number, material: THREE.Material) { return new THREE.Mesh(new RoundedBoxGeometry(...size, 5, radius), material); }

  private installLighting() {
    const key = new THREE.DirectionalLight(0xffffff, 3.4); key.position.set(7, 10, 9); key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.camera.near = 0.1; key.shadow.camera.far = 35; this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x7bd6ff, 2.0); rim.position.set(-7, 5, -6); this.scene.add(rim);
    const green = new THREE.PointLight(0x54ff9a, 7, 7, 2); green.position.set(1.2, 1.4, 2.8); this.scene.add(green);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshPhysicalMaterial({ color: 0x081118, roughness: 0.91, metalness: 0.08 })); floor.rotation.x = -Math.PI / 2; floor.position.y = -1.55; floor.receiveShadow = true; this.scene.add(floor);
    const grid = new THREE.GridHelper(80, 80, 0x244653, 0x132a33); grid.position.y = -1.535; (grid.material as THREE.Material).opacity = 0.30; (grid.material as THREE.Material).transparent = true; this.scene.add(grid);
  }

  private register(id: string, object: THREE.Object3D) {
    object.userData.partId = id;
    object.traverse((node) => {
      node.userData.partId = id;
      if (node instanceof THREE.Mesh) { node.castShadow = true; node.receiveShadow = true; }
    });
    this.scene.add(object);
    this.parts.set(id, { id, object, basePosition: object.position.clone() });
  }

  private screw(position: THREE.Vector3, length = 0.7, axis: 'x'|'y'|'z' = 'y') {
    const g = new THREE.Group();
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, length, 20), this.metal(0xc7ccd0, 0.18));
    const head = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.10, 24), this.metal(0xd5d9dc, 0.16)); head.position.y = length / 2 + 0.05;
    g.add(shaft, head); g.position.copy(position);
    if (axis === 'x') g.rotation.z = Math.PI / 2; if (axis === 'z') g.rotation.x = Math.PI / 2;
    this.scene.add(g);
  }

  private installAssembly() {
    const bracket = new THREE.Group();
    const plate = this.rounded([0.42, 4.7, 2.55], 0.09, this.metal(0xb9bec2, 0.20)); bracket.add(plate);
    for (const y of [-1.65, 1.65]) for (const z of [-0.82, 0.82]) { const hole = new THREE.Mesh(new THREE.CylinderGeometry(0.18,0.18,0.52,32), this.polymer(0x05080a)); hole.rotation.z=Math.PI/2; hole.position.set(0,y,z); bracket.add(hole); }
    bracket.position.set(-4.4, 0, 0); this.register('mounting-bracket', bracket);

    const latch = new THREE.Group();
    const latchBlock = this.rounded([1.45, 1.85, 1.65], 0.12, this.metal(0x252b30, 0.29)); latch.add(latchBlock);
    const guide = new THREE.Mesh(new THREE.CylinderGeometry(0.22,0.22,1.65,28), this.metal(0xc5c9cb,0.18)); guide.rotation.z=Math.PI/2; guide.position.x=-1.1; latch.add(guide);
    latch.position.set(-2.45, -0.25, 0); this.register('latch-body', latch);

    const solenoid = new THREE.Group();
    const cage = this.rounded([2.1, 1.1, 1.18], 0.08, this.metal(0xb5a876, 0.30)); solenoid.add(cage);
    const coil = this.rounded([1.55, 0.82, 0.96], 0.08, this.polymer(0x174a7a,0.34)); coil.position.x=0.08; solenoid.add(coil);
    const plunger = new THREE.Mesh(new THREE.CylinderGeometry(0.18,0.18,1.75,30), this.metal(0xd1d3d4,0.13)); plunger.rotation.z=Math.PI/2; plunger.position.x=-1.72; solenoid.add(plunger);
    const springMat = this.metal(0xcdd0d2,0.2); for(let i=0;i<7;i++){ const ring=new THREE.Mesh(new THREE.TorusGeometry(0.28,0.035,10,32),springMat); ring.rotation.y=Math.PI/2; ring.position.x=-1.05-i*0.14; solenoid.add(ring); }
    solenoid.position.set(-0.55, 0.92, 0); this.register('solenoid', solenoid);

    const pi = new THREE.Group();
    const board = this.rounded([2.9, 0.12, 2.05], 0.06, this.polymer(0x146b43,0.48)); pi.add(board);
    const chipMat = this.metal(0x222629,0.34); const soc = this.rounded([0.72,0.18,0.72],0.05,chipMat); soc.position.set(0,0.16,0.1); pi.add(soc);
    for (const [x,z,w,d] of [[-1.08,-0.65,0.55,0.5],[1.08,-0.62,0.62,0.48],[1.08,0.62,0.62,0.48],[-0.95,0.68,0.74,0.32]] as const) { const c=this.rounded([w,0.24,d],0.04,this.metal(0xc7c9c9,0.18)); c.position.set(x,0.18,z); pi.add(c); }
    const gpioMat=this.polymer(0x111517,0.38); const gpio=this.rounded([1.9,0.25,0.24],0.03,gpioMat); gpio.position.set(-0.15,0.22,-0.86); pi.add(gpio);
    for(let i=0;i<20;i++){ const pin=new THREE.Mesh(new THREE.BoxGeometry(0.035,0.18,0.035),this.metal(0xd2ad45,0.24)); pin.position.set(-1.02+i*0.1,0.38,-0.86); pi.add(pin); }
    pi.position.set(1.15,-0.35,0.12); this.register('raspberry-pi', pi);

    const frame = new THREE.Group(); const shell = this.rounded([2.6,3.95,0.48],0.14,this.metal(0x20272c,0.25)); frame.add(shell); frame.position.set(3.15,0.15,0); this.register('frame',frame);
    const pack = this.rounded([2.45,1.45,1.18],0.16,this.polymer(0x12181d,0.44)); pack.position.set(4.75,0.95,0.15); this.register('battery',pack);

    const wireMat = new THREE.MeshPhysicalMaterial({ color:0xdb2525,roughness:0.46,metalness:0.02 });
    const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(0.4,0.8,0.4),new THREE.Vector3(1.6,0.55,0.85),new THREE.Vector3(3.4,1.0,0.6),new THREE.Vector3(4.2,1.1,0.25)]);
    const wire=new THREE.Mesh(new THREE.TubeGeometry(curve,48,0.045,10,false),wireMat); wire.castShadow=true; this.scene.add(wire);
    this.screw(new THREE.Vector3(-3.6,1.2,1.25),0.72,'y'); this.screw(new THREE.Vector3(-3.2,-0.9,-1.2),0.66,'z'); this.screw(new THREE.Vector3(2.45,1.35,0.8),0.7,'y'); this.screw(new THREE.Vector3(3.8,-0.6,-0.75),0.7,'x');
  }

  private installEvents() { this.canvas.addEventListener('pointerdown', this.handlePointerDown); this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(this.canvas); }
  private handlePointerDown = (event: PointerEvent) => {
    const rect=this.canvas.getBoundingClientRect(); this.pointer.x=((event.clientX-rect.left)/rect.width)*2-1; this.pointer.y=-((event.clientY-rect.top)/rect.height)*2+1; this.raycaster.setFromCamera(this.pointer,this.camera);
    const intersections=this.raycaster.intersectObjects([...this.parts.values()].map(p=>p.object),true); const id=intersections[0]?.object.userData.partId as string|undefined; this.select(id??null);
  };

  select(id: string|null) {
    this.selectedId=id; this.transform.detach();
    for(const [partId,part] of this.parts) part.object.traverse(node=>{ if(node instanceof THREE.Mesh){ const mats=Array.isArray(node.material)?node.material:[node.material]; for(const mat of mats){ if(mat instanceof THREE.MeshStandardMaterial){ mat.emissive.set(partId===id?0x0b5e35:0x000000); mat.emissiveIntensity=partId===id?0.55:0; } } } });
    const selected=id?this.parts.get(id)?.object:undefined; if(selected&&this.explode===0)this.transform.attach(selected); this.events.onSelectionChange?.(id);
  }
  setTransformMode(mode:TransformMode){this.transform.setMode(mode==='move'?'translate':mode);}
  setExplode(percent:number){this.explode=THREE.MathUtils.clamp(percent,0,100);const amount=this.explode/100;for(const part of this.parts.values()){const direction=part.basePosition.clone();direction.y*=0.45;if(direction.lengthSq()<0.01)direction.set(1,0.2,0);direction.normalize();part.object.position.copy(part.basePosition).addScaledVector(direction,amount*2.65);}if(this.explode>0)this.transform.detach();else if(this.selectedId){const selected=this.parts.get(this.selectedId)?.object;if(selected)this.transform.attach(selected);}}
  setAutoRotate(enabled:boolean){this.orbit.autoRotate=enabled;this.orbit.autoRotateSpeed=1.0;}
  setCameraPreset(preset:CameraPreset){const positions:Record<CameraPreset,THREE.Vector3>={fit:new THREE.Vector3(8.8,5.6,9.8),iso:new THREE.Vector3(8.8,5.6,9.8),top:new THREE.Vector3(0,12,0.01),front:new THREE.Vector3(0,0.5,12),right:new THREE.Vector3(12,0.5,0)};this.camera.position.copy(positions[preset]);this.orbit.target.set(0,0.15,0);this.orbit.update();}
  hideSelected(){if(this.selectedId){const p=this.parts.get(this.selectedId);if(p)p.object.visible=false;}}
  isolateSelected(){if(this.selectedId)for(const[id,p]of this.parts)p.object.visible=id===this.selectedId;}
  showAll(){for(const p of this.parts.values())p.object.visible=true;}
  private resize(){const width=Math.max(1,this.canvas.clientWidth),height=Math.max(1,this.canvas.clientHeight);this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.renderer.setSize(width,height,false);}
  private animate=()=>{this.frameHandle=requestAnimationFrame(this.animate);this.orbit.update();this.renderer.render(this.scene,this.camera);};
  dispose(){cancelAnimationFrame(this.frameHandle);this.resizeObserver?.disconnect();this.canvas.removeEventListener('pointerdown',this.handlePointerDown);this.orbit.dispose();this.transform.dispose();for(const part of this.parts.values())part.object.traverse(node=>{if(node instanceof THREE.Mesh){node.geometry.dispose();const mats=Array.isArray(node.material)?node.material:[node.material];mats.forEach(m=>m.dispose());}});this.renderer.dispose();}
}
