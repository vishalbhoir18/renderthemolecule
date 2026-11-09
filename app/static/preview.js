"use strict";

/*
 * Interactive 3D preview with Mol* (https://molstar.org, MIT licence), loaded the
 * first time a PDB ID is entered. The camera set here can be sent with a render:
 * Blender then renders exactly this view.
 *
 * Mol* and Molecular Nodes both keep the structure file's coordinates (Blender
 * scales them by 0.1), so a camera's position, target and up direction carry over
 * unchanged. Mol*'s field of view is vertical, which Blender matches whatever the
 * image width; the viewer is kept at the image's aspect ratio so the framing agrees.
 */
const Preview = (() => {
  const SCRIPT = "/static/vendor/molstar/molstar.js";
  const STYLESHEET = "/static/vendor/molstar/molstar.css";

  // Molecular Nodes' preset camera rotations (Blender XYZ Euler angles, degrees).
  const VIEWPOINT_EULER = {
    default: [70.402, 0, 0],
    front: [90, 0, 0],
    back: [90, 0, -180],
    top: [0, 0, 0],
    bottom: [-180, 0, 0],
    left: [-270, 0, -90],
    right: [-270, 0, -270],
  };

  const BACKBONE_STYLES = new Set(["cartoon", "ribbon"]);
  const LARGE = 150000;  // atoms; above this a faster surface is drawn
  // Everything but water (the atomic styles), and ligands, ions and sugars (overlaid on cartoons),
  // as in app/blender_render.py.
  const NOT_WATER = "(sel.atom.atom-groups :entity-test (not (= atom.entity-type water)))";
  const LIGANDS = "(sel.atom.atom-groups :entity-test (or (= atom.entity-type non-polymer) (= atom.entity-type branched)))";

  const BACKGROUNDS = { white: 0xffffff, black: 0x000000, transparent: 0xffffff };

  let viewer = null;
  let loading = null;
  let element = null;
  let shown = null;        // options currently on screen
  let entry = null;        // { code, model, structure, assemblyMissing, components: [] }
  let wanted = null;       // latest requested options, applied in order
  let running = null;
  let moved = false;       // the visitor has turned or zoomed the view since it was last framed
  let refit = false;       // go back to the preset view at the next update
  let pendingCamera = null;
  const listeners = { move: [], status: [], note: [] };

  function emit(kind, ...args) { for (const fn of listeners[kind]) fn(...args); }

  function supported() {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(window.WebGLRenderingContext && (canvas.getContext("webgl2") || canvas.getContext("webgl")));
    } catch {
      return false;
    }
  }

  function loadLibrary() {
    if (window.molstar) return Promise.resolve();
    loading ??= new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = STYLESHEET;
      document.head.append(link);
      const script = document.createElement("script");
      script.src = SCRIPT;
      script.onload = resolve;
      script.onerror = () => { loading = null; reject(new Error("The 3D viewer could not be loaded.")); };
      document.head.append(script);
    });
    return loading;
  }

  async function createViewer() {
    await loadLibrary();
    viewer = await window.molstar.Viewer.create(element, {
      extensions: [],
      layoutIsExpanded: false,
      layoutShowControls: false,
      layoutShowRemoteState: false,
      layoutShowSequence: false,
      layoutShowLog: false,
      layoutShowLeftPanel: false,
      collapseLeftPanel: true,
      viewportShowExpand: false,
      viewportShowControls: false,
      viewportShowSettings: false,
      viewportShowSelectionMode: false,
      viewportShowAnimation: false,
      viewportShowTrajectoryControls: false,
      viewportShowScreenshotControls: false,
      viewportShowToggleFullscreen: false,
      viewportShowReset: false,
      viewportFocusBehavior: "disabled",  // clicking an atom must not move the camera
      pdbProvider: "rcsb",
      config: [
        [window.molstar.lib.plugin.PluginConfig.Viewport.ShowIllumination, false],
        [window.molstar.lib.plugin.PluginConfig.Viewport.ShowXR, "never"],
      ],
    });
    viewer.plugin.canvas3d.setProps({
      camera: { mode: "perspective", helper: { axes: { name: "off", params: {} } } },
      cameraFog: { name: "off", params: {} },  // Blender adds no fog either
    });
    watchInteraction();
  }

  // Turning, zooming or moving the view (not just clicking) counts as choosing it.
  function watchInteraction() {
    let down = null;
    const markMoved = () => {
      if (!moved) {
        moved = true;
        emit("move");
      }
    };
    element.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    element.addEventListener("pointermove", (e) => {
      if (down && e.buttons && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 3) markMoved();
    });
    window.addEventListener("pointerup", () => { down = null; });
    element.addEventListener("wheel", markMoved, { passive: true });
  }

  // Rotation matrix for Blender XYZ Euler angles: R = Rz · Ry · Rx.
  function eulerMatrix([x, y, z]) {
    const [a, b, c] = [x, y, z].map((deg) => (deg * Math.PI) / 180);
    const [ca, sa, cb, sb, cc, sc] = [Math.cos(a), Math.sin(a), Math.cos(b), Math.sin(b), Math.cos(c), Math.sin(c)];
    return [
      [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
      [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa],
      [-sb, cb * sa, cb * ca],
    ];
  }
  const apply = (m, v) => m.map((row) => row[0] * v[0] + row[1] * v[1] + row[2] * v[2]);

  // Direction a preset looks in, and its up direction (a Blender camera looks down -Z, with +Y up).
  function viewpointAxes(name) {
    const m = eulerMatrix(VIEWPOINT_EULER[name] || VIEWPOINT_EULER.default);
    return { forward: apply(m, [0, 0, -1]), up: apply(m, [0, 1, 0]) };
  }

  function frameViewpoint(name, durationMs = 0) {
    const { forward, up } = viewpointAxes(name);
    viewer.plugin.canvas3d.requestCameraReset({
      durationMs,
      snapshot: (scene, camera) => {
        const { center, radius } = scene.boundingSphereVisible;
        return camera.getInvariantFocus(center, radius, up, forward);
      },
    });
    moved = false;
  }

  function setCameraNow(cam) {
    viewer.plugin.canvas3d.requestCameraReset({
      durationMs: 0,
      snapshot: { position: [...cam.position], target: [...cam.target], up: [...cam.up], fov: (cam.fov * Math.PI) / 180 },
    });
  }

  async function fetchStructure(code) {
    const resp = await fetch(`/api/structure/${encodeURIComponent(code)}`);
    if (!resp.ok) {
      let message = `The structure could not be downloaded (error ${resp.status}).`;
      try { message = (await resp.json()).error || message; } catch { /* keep the generic message */ }
      throw new Error(message);
    }
    const bytes = new Uint8Array(await resp.arrayBuffer());
    // Normally BinaryCIF; a text mmCIF file starts with "data_" or a comment.
    return bytes[0] === 0x64 || bytes[0] === 0x23 ? new TextDecoder().decode(bytes) : bytes;
  }

  async function loadEntry(code) {
    const plugin = viewer.plugin;
    emit("status", `Downloading ${code.toUpperCase()}…`);
    const content = await fetchStructure(code);
    emit("status", "Building the 3D view…");
    await plugin.clear();
    const data = await plugin.builders.data.rawData({ data: content, label: code.toUpperCase() });
    const trajectory = await plugin.builders.structure.parseTrajectory(data, "mmcif");
    const model = await plugin.builders.structure.createModel(trajectory);
    entry = { code, model, structure: null, assemblyMissing: false, components: [] };
  }

  async function buildStructure(assembly) {
    const plugin = viewer.plugin;
    if (entry.structure) await plugin.build().delete(entry.structure.ref).commit();
    entry.components = [];
    // An empty id picks the first assembly, normally "1", as Molecular Nodes does.
    const params = assembly ? { name: "assembly", params: { id: "" } } : { name: "model", params: {} };
    entry.structure = await plugin.builders.structure.createStructure(entry.model, params);
    // Without assembly information Mol* falls back to the deposited model.
    entry.assemblyMissing = assembly && !/^Assembly/i.test(entry.structure.cell?.obj?.label || "");
  }

  function representation(style, atoms) {
    switch (style) {
      case "ribbon": return { type: "putty", size: "uniform", sizeParams: { value: 0.6 } };
      case "surface": return { type: atoms > LARGE ? "gaussian-surface" : "molecular-surface" };
      case "spheres": return { type: "spacefill" };
      case "ball_and_stick": return { type: "ball-and-stick" };
      case "sticks": return { type: "ball-and-stick", typeParams: { sizeFactor: 0.12, sizeAspectRatio: 1 } };
      default: return { type: "cartoon" };
    }
  }

  function colouring(color, style) {
    switch (color) {
      case "rainbow": return { color: "sequence-id" };
      case "secondary_structure": return { color: "secondary-structure" };
      case "goodsell": return { color: "illustrative" };
      // By chain; spheres and sticks also show other elements in their usual colours.
      default: return { color: BACKBONE_STYLES.has(style) || style === "surface" ? "chain-id" : "element-symbol" };
    }
  }

  // Mol* reuses a component that has the same key, so every rebuild gets new keys:
  // the new drawing is added first and the old one removed after, without a blank frame.
  let generation = 0;

  async function component(type, key) {
    return viewer.plugin.builders.structure.tryCreateComponent(
      entry.structure, { type, nullIfEmpty: true, label: key }, `${key}-${generation}`,
    );
  }

  const script = (expression) => ({ name: "script", params: { language: "mol-script", expression } });

  async function buildRepresentations(options) {
    const plugin = viewer.plugin;
    const builder = plugin.builders.structure;
    const old = entry.components;
    const atoms = entry.structure.data?.elementCount || 0;
    const backbone = BACKBONE_STYLES.has(options.style);
    const made = [];
    generation += 1;
    const main = backbone
      ? await component({ name: "static", params: "polymer" }, "polymer")
      : await component(script(NOT_WATER), "not-water");
    if (main) {
      made.push(main);
      await builder.representation.addRepresentation(main, {
        ...representation(options.style, atoms), ...colouring(options.color, options.style),
      });
    }
    if (backbone && options.ligands) {
      const ligands = await component(script(LIGANDS), "ligands");
      if (ligands) {
        made.push(ligands);
        await builder.representation.addRepresentation(ligands, { type: "ball-and-stick", color: "element-symbol" });
      }
    }
    // Remove the previous drawing only now, so the view does not jump.
    if (old.length) {
      const update = plugin.build();
      for (const c of old) update.delete(c.ref);
      await update.commit();
    }
    entry.components = made;
  }

  function applyLook(options) {
    viewer.plugin.canvas3d.setProps({
      renderer: { backgroundColor: BACKGROUNDS[options.background] ?? 0xffffff },
      transparentBackground: options.background === "transparent",
    });
    element.closest(".viewer-frame")?.classList.toggle("transparent", options.background === "transparent");
  }

  function setAspect(resolution) {
    const [w, h] = resolution.split("x").map(Number);
    const frame = element.closest(".viewer-frame");
    if (frame) frame.style.aspectRatio = `${w} / ${h}`;
    viewer?.plugin.canvas3d?.handleResize();
  }

  async function applyOptions(options) {
    if (!viewer) {
      emit("status", "Loading the 3D viewer…");
      await createViewer();
    }
    const before = shown;
    const newEntry = !entry || entry.code !== options.pdb_id;
    setAspect(options.resolution);
    applyLook(options);
    if (newEntry) {
      shown = null;
      moved = false;
      await loadEntry(options.pdb_id);
    }
    const newStructure = newEntry || before.assembly !== options.assembly;
    const keep = moved || pendingCamera;
    const saved = keep && !newEntry ? viewer.plugin.canvas3d.camera.getSnapshot() : null;
    if (newStructure) await buildStructure(options.assembly);
    if (newStructure || ["style", "color", "ligands"].some((k) => before[k] !== options[k])) {
      emit("status", "Building the 3D view…");
      await buildRepresentations(options);
    }
    if (pendingCamera) {
      setCameraNow(pendingCamera);
      pendingCamera = null;
      moved = true;
    } else if (saved) {
      viewer.plugin.canvas3d.requestCameraReset({ durationMs: 0, snapshot: saved });
    } else if (!moved && (refit || newStructure || !before || before.resolution !== options.resolution
                          || before.style !== options.style || before.viewpoint !== options.viewpoint)) {
      frameViewpoint(options.viewpoint);
    }
    refit = false;
    shown = { ...options };
    emit("status", "");
    emit("note", entry.assemblyMissing
      ? "This entry has no biological assembly information, so the deposited model is shown." : "");
  }

  async function drain() {
    while (wanted) {
      const options = wanted;
      wanted = null;
      try {
        await applyOptions(options);
      } catch (err) {
        if (!wanted) emit("status", err.message || "The 3D preview failed.", true);
        if (entry && entry.code === options.pdb_id && !shown) entry = null;  // retry the download next time
      }
    }
    running = null;
  }

  return {
    supported,
    /** Show `options` (form values) in `container`; later calls update what changed. */
    show(container, options) {
      element = container;
      wanted = { ...options };
      running ??= drain();
      return running;
    },
    /** Turn to one of Molecular Nodes' preset viewpoints. */
    frame(viewpoint, durationMs = 400) {
      if (!viewer || !entry) return;
      frameViewpoint(viewpoint, durationMs);
      if (shown) shown.viewpoint = viewpoint;
    },
    /** Drop the visitor's view: the next update shows the preset view again. */
    forgetView() {
      moved = false;
      refit = true;
      pendingCamera = null;
    },
    /** Use this camera (from a shared link) once the entry is shown. */
    useCamera(camera) {
      pendingCamera = camera;
      if (viewer && entry && !running) {
        setCameraNow(camera);
        pendingCamera = null;
        moved = true;
      }
    },
    /** The current view, rounded as the server stores it; null before anything is shown. */
    camera() {
      if (!viewer || !shown) return null;
      const s = viewer.plugin.canvas3d.camera.getSnapshot();
      const round = (values, digits) => Array.from(values, (x) => Number(x.toFixed(digits)) + 0);
      return {
        position: round(s.position, 2),
        target: round(s.target, 2),
        up: round(s.up, 4),
        fov: Number(((s.fov * 180) / Math.PI).toFixed(2)),
      };
    },
    /** Call after the viewer's box was hidden or changed size. */
    resize() { viewer?.plugin.canvas3d?.handleResize(); },
    get busy() { return Boolean(running); },
    get shownId() { return shown?.pdb_id ?? null; },
    on(kind, fn) { listeners[kind].push(fn); },
    viewpointAxes,
  };
})();
