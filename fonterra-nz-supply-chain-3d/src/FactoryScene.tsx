import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { cities, lineNames, productionLines, type Line, type Order, type Selection } from './contract';
import { laneSummary } from './data';

interface SceneProps {
  orders: Order[];
  lines: Line[];
  selection: Selection;
  onSelect: (selection: Selection) => void;
  motion: boolean;
  theme: string;
}
interface SceneHandle {
  update: (props: SceneProps) => void;
  reset: () => void;
  rotate: (direction: number) => void;
  zoom: (direction: number) => void;
  dispose: () => void;
}

function createFactory(host: HTMLDivElement, onFailure: () => void): SceneHandle {
  const style = getComputedStyle(document.documentElement);
  const cp = (token: string) => style.getPropertyValue(`--cp-${token}`).trim();
  const isDark = document.documentElement.dataset.theme === 'dark';
  const palette = {
    bg: cp('bg-elevated'), base: cp(isDark ? 'border' : 'surface-soft'),
    surface: cp(isDark ? 'border-strong' : 'surface'), border: cp(isDark ? 'text-muted' : 'border'),
    edge: cp(isDark ? 'text-soft' : 'border-strong'), text: cp('text'), muted: cp('text-muted'),
    accent: cp('accent'), accentFg: cp('accent-fg'), success: cp('success'),
    light: cp(isDark ? 'text' : 'surface'), labelSurface: cp('surface'),
  };
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(palette.bg);
  const camera = new THREE.OrthographicCamera(-20, 20, 16, -16, 0.1, 200);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(palette.bg);
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', 'Interactive illustrative dairy factory. Four category lanes, silos, cold store and six destination docks. Use the adjacent lane and dock buttons for keyboard selection.');
  renderer.domElement.dataset.testid = 'factory-canvas';
  host.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.enablePan = false;
  controls.minZoom = 0.6;
  controls.maxZoom = 2.8;
  controls.minPolarAngle = Math.PI / 7;
  controls.maxPolarAngle = Math.PI / 2.5;
  controls.enableZoom = false; // Keep page scrolling usable; explicit buttons provide camera zoom.

  const materials: THREE.Material[] = [];
  const geometries: THREE.BufferGeometry[] = [];
  const textures: THREE.Texture[] = [];
  const picks: THREE.Object3D[] = [];
  const movers: { mesh: THREE.Mesh; origin: number; lane: string }[] = [];
  const laneSurfaces = new Map<string, THREE.MeshStandardMaterial>();
  const dockSurfaces = new Map<string, THREE.MeshStandardMaterial>();
  const truckBodies = new Map<string, { body: THREE.Mesh; lamp: THREE.Mesh; label: THREE.Sprite }>();
  const tokens: THREE.Mesh[] = [];
  const selectionRing = new THREE.Group();
  const floor = new THREE.Group();
  scene.add(floor);
  let props: SceneProps | null = null;
  let disposed = false;
  let failed = false;
  let animationId = 0;
  let animationTime = 0;
  let previousTime = 0;
  let lastRenderTime = 0;
  let dirty = true;
  let activeLanes = new Set<string>();
  controls.addEventListener('change', () => { dirty = true; });

  function material(color: string, metalness = 0.1, roughness = 0.72) {
    const value = new THREE.MeshStandardMaterial({ color, metalness, roughness });
    materials.push(value);
    return value;
  }
  const surface = material(palette.surface);
  const base = material(palette.base);
  const border = material(palette.border);
  const steel = material(palette.edge, 0.65, 0.34);
  const dark = material(palette.muted, 0.3, 0.5);
  const accent = material(palette.accent, 0.22, 0.45);
  function box(w: number, h: number, d: number, x: number, y: number, z: number, mat: THREE.Material, parent: THREE.Object3D = floor) {
    const geometry = new THREE.BoxGeometry(w, h, d);
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }
  function cylinder(r: number, h: number, x: number, y: number, z: number, mat: THREE.Material, parent: THREE.Object3D = floor) {
    const geometry = new THREE.CylinderGeometry(r, r, h, 24);
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }
  function label(text: string, x: number, y: number, z: number, width = 3.2, important = false) {
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 112;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Cannot create factory labels.');
    context.fillStyle = important ? palette.accent : palette.labelSurface;
    context.fillRect(0, 0, 640, 112);
    context.fillStyle = important ? palette.accentFg : palette.text;
    context.font = '600 36px "Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, 320, 58, 600);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    textures.push(texture);
    const mat = new THREE.SpriteMaterial({ map: texture, depthTest: false });
    materials.push(mat);
    const sprite = new THREE.Sprite(mat);
    sprite.position.set(x, y, z);
    sprite.scale.set(width, width * 112 / 640, 1);
    sprite.renderOrder = 2;
    floor.add(sprite);
    return sprite;
  }
  function selectable(object: THREE.Object3D, selection: NonNullable<Selection>) {
    object.userData.selection = selection;
    picks.push(object);
  }
  scene.add(new THREE.HemisphereLight(palette.light, palette.edge, 2.5));
  const key = new THREE.DirectionalLight(palette.light, 3.5);
  key.position.set(-12, 28, 16);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -24;
  key.shadow.camera.right = 24;
  key.shadow.camera.top = 24;
  key.shadow.camera.bottom = -24;
  key.shadow.bias = -0.0005;
  key.shadow.normalBias = 0.04;
  scene.add(key);
  const fill = new THREE.DirectionalLight(palette.light, 1.8);
  fill.position.set(18, 10, -8);
  scene.add(fill);

  box(30, 0.4, 27, 0, -0.5, 0, border);
  box(29.7, 0.1, 26.7, 0, -0.24, 0, surface);
  const grid = new THREE.GridHelper(28, 28, palette.border, palette.border);
  grid.position.y = -0.17;
  scene.add(grid);
  box(25.5, 0.25, 16.3, -0.3, 0, -3.2, base);
  box(25.5, 4.2, 0.2, -0.3, 2.1, -11.2, border);
  box(0.2, 4.2, 16, -13, 2.1, -3.2, border);
  box(25.5, 0.2, 1.4, -0.3, 4.3, -10.5, surface);
  box(0.15, 0.26, 16, -12.9, 4.3, -3.2, steel);
  for (const x of [-12.5, -6.4, 1.2, 8.7, 12.2]) {
    box(0.16, 4.4, 0.16, x, 2.2, -10.7, steel);
    box(0.16, 4.4, 0.16, x, 2.2, 4.4, steel);
    box(0.13, 0.2, 15.5, x, 4.4, -3.2, steel);
  }
  box(25, 0.16, 0.18, -0.2, 4.4, 4.4, steel);
  box(25, 0.16, 0.18, -0.2, 4.4, -10.7, steel);
  label('NZ / CATEGORY ASSEMBLY', -0.5, 5.3, -10.9, 7.8, true);

  for (const z of [-7.2, -2.8, 1.6]) {
    cylinder(1.2, 3.8, -10.6, 2.1, z, steel);
    cylinder(1.26, 0.13, -10.6, 0.65, z, border);
    cylinder(1.26, 0.13, -10.6, 3.6, z, border);
    cylinder(0.45, 0.3, -10.6, 4.15, z, steel);
    box(0.25, 0.28, 1.9, -10.6, 4.24, z + 1.15, steel);
    box(0.15, 3.7, 0.15, -11.6, 2.1, z + 0.6, border);
    for (let rung = 0; rung < 9; rung++) box(0.5, 0.06, 0.1, -11.5, 0.5 + rung * 0.39, z + 0.7, steel);
  }
  label('01 / INTAKE SILOS', -10.6, 5.1, -5, 4.5);
  box(0.23, 0.23, 13, -8.8, 0.9, -3.4, steel);
  box(17, 0.23, 0.23, -0.2, 0.9, -7.8, steel);

  const laneXs = [-5.5, -1.6, 2.3, 6.2];
  productionLines.forEach((lane, index) => {
    const x = laneXs[index];
    const mat = material(palette.border);
    laneSurfaces.set(lane, mat);
    const pad = box(3.45, 0.04, 11.5, x, 0.16, -1.8, mat);
    selectable(pad, { kind: 'lane', id: lane });
    for (const side of [-1, 1]) box(0.055, 0.04, 11.3, x + side * 1.65, 0.2, -1.8, steel);
    const labelMesh = label(`${String(index + 2).padStart(2, '0')} / ${lineNames[lane].toUpperCase()}`, x, 3.9, -4.2, 3.9);
    selectable(labelMesh, { kind: 'lane', id: lane });

    if (lane === 'dairy' || lane === 'cultured') {
      for (const offset of [-0.65, 0.65]) {
        const vat = cylinder(0.57, lane === 'dairy' ? 2.8 : 2.1, x + offset, 1.8, -5.2, surface);
        selectable(vat, { kind: 'lane', id: lane });
        cylinder(0.62, 0.12, x + offset, 2.8, -5.2, steel);
        box(0.09, 1.0, 0.09, x + offset, 3.2, -5.2, steel);
      }
      box(1.4, 0.13, 0.13, x, 3.6, -5.2, steel);
    } else {
      const machine = box(2.1, 1.6, 2.3, x, 1.2, -5.0, surface);
      selectable(machine, { kind: 'lane', id: lane });
      box(2.2, 0.15, 2.4, x, 2.07, -5, steel);
      for (const offset of [-0.7, 0, 0.7]) box(0.36, 0.12, 1.5, x + offset, 2.2, -5.0, border);
      box(0.6, 0.4, 0.06, x + 0.8, 1.5, -3.82, accent);
    }
    const belt = box(1.55, 0.25, 6.3, x, 0.85, -0.6, dark);
    selectable(belt, { kind: 'lane', id: lane });
    for (const offset of [-0.84, 0.84]) {
      box(0.1, 0.17, 6.5, x + offset, 1.04, -0.6, steel);
      for (const z of [-3.0, 1.7]) box(0.12, 0.7, 0.12, x + offset, 0.45, z, steel);
    }
    for (let roll = 0; roll < 17; roll++) box(1.35, 0.06, 0.065, x, 1.0, -3.35 + roll * 0.34, border);
    for (let index = 0; index < 3; index++) {
      const crate = box(0.65, 0.43, 0.65, x, 1.25, -2.5 + index * 1.55, surface);
      box(0.67, 0.06, 0.67, 0, 0.02, 0, border, crate);
      movers.push({ mesh: crate, origin: crate.position.z, lane });
      selectable(crate, { kind: 'lane', id: lane });
    }
    for (let index = 0; index < 3; index++) {
      const token = box(0.42, 0.12, 0.42, x + 1.1, 0.3, 0.8 + index * 0.6, accent);
      token.visible = false;
      tokens.push(token);
      picks.push(token);
    }
    box(2.0, 0.12, 1.0, x, 0.28, 3.7, steel);
  });

  box(3.9, 2.8, 4.5, 10.3, 1.5, -7.6, surface);
  box(4.1, 0.18, 4.7, 10.3, 2.99, -7.6, border);
  box(2.25, 2.15, 0.06, 10.3, 1.22, -5.33, steel);
  for (let stripe = 0; stripe < 7; stripe++) box(2.2, 0.045, 0.07, 10.3, 0.35 + stripe * 0.29, -5.28, border);
  label('06 / COLD STORE', 10.3, 4.0, -8.4, 4.4);
  for (const z of [-1.8, 0.6, 3]) {
    for (const y of [0.4, 1.2]) {
      box(2.0, 0.12, 1.7, 10.5, y, z, steel);
      for (const x of [9.95, 10.85]) box(0.72, 0.58, 1.3, x, y + 0.35, z, border);
    }
  }

  box(27, 0.02, 5.8, 0, -0.14, 9.5, border);
  for (let index = 0; index < 15; index++) box(0.8, 0.025, 0.08, -13 + index * 1.8, -0.1, 12.3, surface);
  cities.forEach((city, index) => {
    const x = -10.6 + index * 4.2;
    const dockMat = material(palette.base);
    dockSurfaces.set(city, dockMat);
    const dock = box(3.3, 0.35, 2.0, x, 0.11, 5.8, dockMat);
    selectable(dock, { kind: 'dock', id: city });
    box(0.13, 0.8, 0.13, x - 1.3, 0.55, 6.45, accent);
    box(0.13, 0.8, 0.13, x + 1.3, 0.55, 6.45, accent);
    const truck = new THREE.Group();
    floor.add(truck);
    const body = box(1.7, 1.5, 3.0, x, 1.13, 8.45, material(palette.surface), truck);
    selectable(body, { kind: 'dock', id: city });
    const cab = box(1.72, 1.3, 1.1, x, 1.02, 10.5, surface, truck);
    selectable(cab, { kind: 'dock', id: city });
    box(1.4, 0.43, 0.06, x, 1.32, 11.08, steel, truck);
    box(1.8, 0.2, 0.12, x, 0.45, 11.13, dark, truck);
    for (const side of [-0.9, 0.9]) {
      for (const z of [7.5, 9.1, 10.55]) {
        const wheel = cylinder(0.35, 0.19, x + side, 0.36, z, dark, truck);
        wheel.rotation.z = Math.PI / 2;
      }
      box(0.03, 0.12, 2.6, x + side * 0.96, 1.42, 8.45, accent, truck);
    }
    const lamp = box(0.23, 0.12, 0.2, x, 1.76, 10.5, material(palette.edge), truck);
    const sign = label(`${String(index + 1).padStart(2, '0')} ${city.toUpperCase()}`, x, 0.9, 13.1, 3.6);
    selectable(sign, { kind: 'dock', id: city });
    const truckLabel = label('NO ORDER SELECTED', x, 2.7, 9.0, 3.2);
    truckLabel.visible = false;
    truckBodies.set(city, { body, lamp, label: truckLabel });
  });
  label('DISPATCH / SCHEMATIC DESTINATIONS', 0, 0.45, 6.9, 7.3);
  floor.add(selectionRing);
  for (const side of [-1, 1]) {
    box(0.08, 0.08, 1.25, side * 0.68, 0, 0, accent, selectionRing);
    box(1.44, 0.08, 0.08, 0, 0, side * 0.62, accent, selectionRing);
  }
  selectionRing.visible = false;

  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    const aspect = width / height;
    const span = Math.max(15.6, 21.8 / aspect);
    camera.left = -span * aspect;
    camera.right = span * aspect;
    camera.top = span;
    camera.bottom = -span;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    dirty = true;
  }
  function reset() {
    camera.position.set(29, 29, 36);
    camera.zoom = 1;
    controls.target.set(0, 0.5, 0);
    camera.updateProjectionMatrix();
    controls.update();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  reset();
  resize();
  const raycaster = new THREE.Raycaster();
  let pointerStart = { x: 0, y: 0 };
  function pointerDown(event: PointerEvent) { pointerStart = { x: event.clientX, y: event.clientY }; }
  function pointerUp(event: PointerEvent) {
    if (Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 6) return;
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(
      (event.clientX - rect.left) / rect.width * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    ), camera);
    const hit = raycaster.intersectObjects(picks, false).find((result) => result.object.visible && result.object.userData.selection);
    if (hit) props?.onSelect(hit.object.userData.selection as Selection);
  }
  function contextLost(event: Event) {
    event.preventDefault();
    failed = true;
    cancelAnimationFrame(animationId);
    onFailure();
  }
  renderer.domElement.addEventListener('pointerdown', pointerDown);
  renderer.domElement.addEventListener('pointerup', pointerUp);
  renderer.domElement.addEventListener('webglcontextlost', contextLost);

  function draw(time: number) {
    if (disposed || failed) return;
    animationId = requestAnimationFrame(draw);
    const elapsed = previousTime ? Math.min((time - previousTime) / 1000, 0.06) : 0;
    previousTime = time;
    if (document.hidden) return;
    try {
      controls.update();
      if (props?.motion) {
        animationTime += elapsed;
        for (const mover of movers) {
          const active = activeLanes.has(mover.lane);
          mover.mesh.position.z = active ? ((mover.origin + 3.5 + animationTime * 0.48) % 4.7) - 3.5 : mover.origin;
        }
        dirty = true;
        renderer.shadowMap.needsUpdate = true;
      }
      if (dirty && time - lastRenderTime >= 1000 / 30) {
        renderer.render(scene, camera);
        dirty = false;
        lastRenderTime = time;
      }
    } catch { failed = true; onFailure(); }
  }
  animationId = requestAnimationFrame(draw);

  return {
    update(next) {
      const changed = !props || props.orders !== next.orders || props.lines !== next.lines ||
        props.selection !== next.selection || props.motion !== next.motion;
      props = next;
      if (!changed) return;
      dirty = true;
      const receivedIds = new Set(next.orders.filter((order) => order.status === 'Received').map((order) => order.id));
      activeLanes = new Set(next.lines.filter((line) => receivedIds.has(line.orderId)).map((line) => line.productionLine));
      for (const [lane, mat] of laneSurfaces) {
        const selected = next.selection?.kind === 'lane' && next.selection.id === lane;
        mat.color.set(selected ? palette.accent : palette.border);
      }
      for (const [city, mat] of dockSurfaces) {
        mat.color.set(next.selection?.kind === 'dock' && next.selection.id === city ? palette.accent : palette.base);
      }
      for (const [city, truck] of truckBodies) {
        const dispatched = next.orders.find((order) => order.city === city && order.status === 'Dispatched');
        (truck.body.material as THREE.MeshStandardMaterial).color.set(dispatched ? palette.accent : palette.surface);
        (truck.lamp.material as THREE.MeshStandardMaterial).color.set(dispatched ? palette.success : palette.edge);
        truck.body.userData.selection = dispatched ? { kind: 'order', id: dispatched.id } : { kind: 'dock', id: city };
        truck.label.visible = false;
      }
      selectionRing.visible = false;
      productionLines.forEach((lane, index) => {
        const assigned = laneSummary(lane, next.orders, next.lines).orders;
        const displayed = [...assigned.filter((order) => order.status === 'Received'), ...assigned.filter((order) => order.status !== 'Received')].slice(0, 3);
        for (let offset = 0; offset < 3; offset++) {
          const token = tokens[index * 3 + offset];
          const order = displayed[offset];
          token.visible = !!order;
          token.userData.selection = order ? { kind: 'order', id: order.id } : null;
          if (order && next.selection?.kind === 'order' && next.selection.id === order.id) {
            selectionRing.visible = true;
            selectionRing.position.copy(token.position).add(new THREE.Vector3(0, 0.15, 0));
          }
        }
      });
    },
    reset,
    rotate(direction) {
      const offset = camera.position.clone().sub(controls.target);
      offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), direction * Math.PI / 8);
      camera.position.copy(controls.target).add(offset);
      controls.update();
    },
    zoom(direction) {
      camera.zoom = THREE.MathUtils.clamp(camera.zoom * (direction > 0 ? 1.2 : 1 / 1.2), 0.6, 2.8);
      camera.updateProjectionMatrix();
      dirty = true;
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(animationId);
      observer.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener('pointerdown', pointerDown);
      renderer.domElement.removeEventListener('pointerup', pointerUp);
      renderer.domElement.removeEventListener('webglcontextlost', contextLost);
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((mat) => mat.dispose());
      textures.forEach((texture) => texture.dispose());
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}

function SceneFallback({ onRetry }: { onRetry?: () => void }) {
  return <div className="scene-fallback" role="status">
    <span className="fallback-mark" aria-hidden="true">3D</span>
    <h3>3D view unavailable</h3>
    <p>Your browser could not render this WebGL scene. Orders, lane selection, dispatch details and the event feed remain available below.</p>
    {onRetry && <button onClick={onRetry}>Retry 3D view</button>}
  </div>;
}

export class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <SceneFallback /> : this.props.children; }
}

export function FactoryScene(props: SceneProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneHandle | null>(null);
  const latestProps = useRef(props);
  latestProps.current = props;
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [help, setHelp] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let scene: SceneHandle | null = null;
    try {
      scene = createFactory(host, () => setFailed(true));
      sceneRef.current = scene;
      scene.update(latestProps.current);
    } catch {
      host.replaceChildren();
      setFailed(true);
    }
    return () => { scene?.dispose(); sceneRef.current = null; };
  }, [props.theme, attempt]);
  useEffect(() => { sceneRef.current?.update(props); }, [props]);

  return <div className="scene-frame">
    <div ref={hostRef} className={`scene-canvas ${failed ? 'is-hidden' : ''}`} />
    {failed ? <SceneFallback onRetry={() => { setFailed(false); setAttempt((value) => value + 1); }} /> : <>
      <div className="scene-caption">
        <span className="micro-label">Isometric / cutaway</span>
        <span>Schematic site · not an actual plant</span>
      </div>
      <div className="scene-legend"><span className="legend-chip" />Category assignments · not measured production</div>
      <div className="camera-controls" aria-label="3D camera controls">
        <button onClick={() => sceneRef.current?.rotate(-1)} aria-label="Rotate camera left" title="Rotate left">↶</button>
        <button onClick={() => sceneRef.current?.rotate(1)} aria-label="Rotate camera right" title="Rotate right">↷</button>
        <span className="control-rule" />
        <button onClick={() => sceneRef.current?.zoom(1)} aria-label="Zoom camera in" title="Zoom in">+</button>
        <button onClick={() => sceneRef.current?.zoom(-1)} aria-label="Zoom camera out" title="Zoom out">−</button>
        <button onClick={() => sceneRef.current?.reset()} className="fit-button" title="Fit and reset camera">Fit view</button>
        <button aria-label="3D navigation help" aria-expanded={help} onClick={() => setHelp(!help)}>?</button>
      </div>
      {help && <p className="scene-help">Drag to orbit. Select a lane, dock or small order marker. Use the camera buttons and the lane / destination buttons below for keyboard access. Trucks indicate recorded dispatch status, not GPS movement.</p>}
    </>}
  </div>;
}
