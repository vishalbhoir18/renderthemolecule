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
 *
 * A preset view is framed as Molecular Nodes frames it when no camera is sent
 * (framing.js), with Blender's field of view, so it needs no camera: an untouched
 * preset view renders as shown.
 */
const Preview = (() => {
  const SCRIPT = "/static/vendor/molstar/molstar.js";
  const STYLESHEET = "/static/vendor/molstar/molstar.css";

  const BACKBONE_STYLES = new Set(["cartoon", "ribbon"]);
  const LARGE = 150000;  // atoms; above this a faster surface is drawn
  // Everything but water (the atomic styles), and ligands, ions and sugars (overlaid on cartoons),
  // as in app/blender_render.py.
  const NOT_WATER = "(sel.atom.atom-groups :entity-test (not (= atom.entity-type water)))";
  const LIGANDS = "(sel.atom.atom-groups :entity-test (or (= atom.entity-type non-polymer) (= atom.entity-type branched)))";

  const BACKGROUNDS = { white: 0xffffff, black: 0x000000, transparent: 0xffffff };

  // --- Colours, as Blender draws them (app/blender_render.py) ----------------------------
  // Molecular Nodes' colours are linear light; the viewer works in sRGB.
  const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const hexOf = (rgb) => rgb.reduce((n, c) => n * 256 + Math.round(Math.min(1, Math.max(0, c)) * 255), 0);
  const fromLinear = (rgb) => hexOf(rgb.map(toSrgb));
  const linearOf = (hex) => [16, 8, 0].map((shift) => toLinear(((hex >> shift) & 255) / 255));

  // CHAIN_COLORS, RAINBOW_COLORS and NON_POLYMER_RAINBOW_COLOR from app/options.py, via /api/options.
  let chainColors = [0x56b4e9];
  let rainbowColors = [0x3939e6, 0xe63939];
  let nonPolymerColor = 0xcccccc;
  const parseHex = (hex) => parseInt(hex.slice(1), 16);

  // Molecular Nodes' "Color Goodsell" lowers the OKLab lightness of carbon atoms by 0.12.
  function goodsellDarken(hex) {
    const [r, g, b] = linearOf(hex);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    const L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s - 0.12;
    const A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
    const B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
    const l2 = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
    const m2 = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
    const s2 = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3;
    return fromLinear([
      4.0767416621 * l2 - 3.3077115913 * m2 + 0.2309699292 * s2,
      -1.2684380046 * l2 + 2.6097574011 * m2 - 0.3413193965 * s2,
      -0.0041960863 * l2 - 0.7034186147 * m2 + 1.7076147010 * s2,
    ]);
  }

  // Chains take CHAIN_COLORS in the order of their sorted (author) IDs, as in Blender; Mol*
  // numbers chains in file order, so the list is given in that order.
  function chainPalette(adjust = (hex) => hex) {
    const ids = [];
    entry.model.data.properties.structAsymMap.forEach(({ auth_id }) => {
      if (!ids.includes(auth_id)) ids.push(auth_id);
    });
    const sorted = [...ids].sort();
    const colors = ids.map((id) => adjust(chainColors[sorted.indexOf(id) % chainColors.length]));
    return { name: "colors", params: { list: { kind: "set", colors } } };
  }

  // "Rainbow", as Blender computes it (rainbow_colors in app/blender_render.py): along each
  // chain's protein or nucleic acid, by residue number, through RAINBOW_COLORS (blended in
  // sRGB); ligands and water grey. Mol* has no such theme, so it is added here.
  const RAINBOW_THEME = "rtm-rainbow";

  function rainbowAt(t) {
    const x = Math.min(1, Math.max(0, t)) * (rainbowColors.length - 1);
    const i = Math.min(Math.floor(x), rainbowColors.length - 2);
    const f = x - i;
    const [a, b] = [rainbowColors[i], rainbowColors[i + 1]];
    return [16, 8, 0].reduce((n, shift) => {
      const mix = ((a >> shift) & 255) * (1 - f) + ((b >> shift) & 255) * f;
      return n * 256 + Math.round(mix);
    }, 0);
  }

  function registerRainbowTheme(plugin) {
    const { StructureElement, StructureProperties: P, Bond } = window.molstar.lib.structure;
    const provider = {
      name: RAINBOW_THEME,
      label: "Rainbow (as rendered)",
      category: "Residue Property",
      getParams: () => ({}),
      defaultValues: {},
      isApplicable: (ctx) => Boolean(ctx.structure),
      factory(ctx, props) {
        // Lowest and highest residue number of the polymer residues in each chain.
        const ranges = new Map();
        for (const model of ctx.structure.root.models) {
          const h = model.atomicHierarchy;
          for (let r = 0; r < h.residues._rowCount; r++) {
            const c = h.chainAtomSegments.index[h.residueAtomSegments.offsets[r]];
            const entity = model.entities.getEntityIndex(h.chains.label_entity_id.value(c));
            if (model.entities.data.type.value(entity) !== "polymer") continue;
            const chain = h.chains.auth_asym_id.value(c);
            const number = h.residues.auth_seq_id.value(r);
            const [low, high] = ranges.get(chain) || [number, number];
            ranges.set(chain, [Math.min(low, number), Math.max(high, number)]);
          }
        }
        const colorOf = (l) => {
          if (P.entity.type(l) !== "polymer") return nonPolymerColor;
          const [low, high] = ranges.get(P.chain.auth_asym_id(l)) || [0, 0];
          return rainbowAt(high > low ? (P.residue.auth_seq_id(l) - low) / (high - low) : 0);
        };
        const color = (location) => {
          if (StructureElement.Location.is(location)) return colorOf(location);
          if (Bond.isLocation(location)) {
            const { aStructure, aUnit, aIndex } = location;
            return colorOf(StructureElement.Location.create(aStructure, aUnit, aUnit.elements[aIndex]));
          }
          return nonPolymerColor;
        };
        return { factory: provider.factory, granularity: "group", color, props, description: "Rainbow along each chain" };
      },
    };
    plugin.representation.structure.themes.colorThemeRegistry.add(provider);
  }

  // Molecular Nodes' secondary-structure colours: helices green, sheets red, loops blue.
  const HELIX = fromLinear([0.16202937, 0.6239606, 0.19461784]);
  const SHEET = fromLinear([1.0, 0.1499598, 0.1499598]);
  const LOOP = fromLinear([0.17144114, 0.3662526, 0.799103]);
  const OTHER = fromLinear([0.8, 0.8, 0.8]);
  const SECONDARY_STRUCTURE = {
    alphaHelix: HELIX, threeTenHelix: HELIX, piHelix: HELIX, betaStrand: SHEET,
    betaTurn: LOOP, coil: LOOP, bend: LOOP, turn: LOOP, dna: OTHER, rna: OTHER, carbohydrate: OTHER,
  };

  // Carbons by chain, other elements in their usual colours.
  const byElement = () => ({
    color: "element-symbol",
    colorParams: { carbonColor: { name: "chain-id", params: { asymId: "auth", palette: chainPalette() } } },
  });

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
    registerRainbowTheme(viewer.plugin);
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

  const sizeOf = (resolution) => resolution.split("x").map(Number);

  // What Mol* draws, for the framing: mesh vertices, sphere centres and cylinder ends grown by
  // the largest radius (Molecular Nodes grows its spheres by their radius too), anything else
  // by its bounding sphere.
  function addDrawn(fit, { values, state }) {
    if (!state.visible || !values.drawCount.ref.value) return;
    const vertices = values.uVertexCount?.ref.value ?? 0;
    const radius = values.padding?.ref.value ?? 0;
    let sources;  // [coordinates, stride, count]
    switch (values.dGeometryType?.ref.value) {
      case "mesh":
        sources = [[values.aPosition?.ref.value, 3, vertices]];
        break;
      case "spheres":  // one (x, y, z, group) per sphere, six vertices each
        sources = [[values.tPositionGroup?.ref.value?.array, 4, vertices / 6]];
        break;
      case "cylinders":
        sources = [[values.aStart?.ref.value, 3, vertices], [values.aEnd?.ref.value, 3, vertices]];
        break;
      default:
        sources = [];
    }
    sources = sources.filter(([array, stride, count]) => array && array.length >= stride * count);
    if (!sources.length) {
      const { center, radius: r } = values.boundingSphere.ref.value;
      if (r > 0) fit.add(center[0], center[1], center[2], r);
      return;
    }
    const transforms = values.aTransform.ref.value;  // a column-major 4×4 matrix per instance
    for (let k = 0; k < values.instanceCount.ref.value; k++) {
      const m = transforms.subarray(16 * k, 16 * k + 16);
      for (const [array, stride, count] of sources) {
        for (let i = 0, o = 0; i < count; i++, o += stride) {
          const x = array[o];
          const y = array[o + 1];
          const z = array[o + 2];
          fit.add(
            m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14],
            radius,
          );
        }
      }
    }
  }

  // A preset view as Blender renders it with no camera sent: Molecular Nodes' framing of the
  // drawn molecule (framing.js) and Blender's field of view, for an image of this size.
  function frameViewpoint(name, resolution, durationMs = 0) {
    const [width, height] = sizeOf(resolution);
    viewer.plugin.canvas3d.requestCameraReset({
      durationMs,
      snapshot: (scene, camera) => {
        const fit = Framing.fitter(name, width, height);
        for (const renderable of scene.renderables) addDrawn(fit, renderable);
        const view = fit.camera();
        const { center, radius } = scene.boundingSphereVisible;
        if (!view) {
          const { forward, up } = Framing.viewpointAxes(name);
          return camera.getInvariantFocus(center, radius, up, forward);
        }
        const offset = Math.hypot(...view.target.map((x, i) => x - center[i]));
        return {
          position: view.position,
          target: view.target,
          up: [...view.up],
          fov: (view.fov * Math.PI) / 180,
          radius: radius + offset,  // Mol* clips the view to this distance around the target
        };
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
      case "rainbow":
        return { color: RAINBOW_THEME };
      case "secondary_structure":
        return {
          color: "secondary-structure",
          colorParams: { saturation: 0, lightness: 0, colors: { name: "custom", params: SECONDARY_STRUCTURE } },
        };
      case "goodsell": {
        // Each chain in its colour. Blender darkens carbon atoms (most atoms), which shows on
        // spheres, sticks and surfaces but not on cartoons.
        const adjust = BACKBONE_STYLES.has(style) ? undefined : goodsellDarken;
        return { color: "chain-id", colorParams: { asymId: "auth", palette: chainPalette(adjust) } };
      }
      default:  // cartoons and surfaces in the chain colour; spheres and sticks by element
        return BACKBONE_STYLES.has(style) || style === "surface"
          ? { color: "chain-id", colorParams: { asymId: "auth", palette: chainPalette() } }
          : byElement();
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
        await builder.representation.addRepresentation(ligands, { type: "ball-and-stick", ...byElement() });
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
    const [w, h] = sizeOf(resolution);
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
      frameViewpoint(options.viewpoint, options.resolution);
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
    /** Turn to one of Molecular Nodes' preset viewpoints, framed as Blender frames it. */
    frame(viewpoint, durationMs = 400) {
      if (!viewer || !entry || !shown) return;
      frameViewpoint(viewpoint, shown.resolution, durationMs);
      shown.viewpoint = viewpoint;
    },
    /** The colours shared with Blender: the /api/options response. */
    setColors(options) {
      if (options.chain_colors?.length) chainColors = options.chain_colors.map(parseHex);
      if (options.rainbow_colors?.length > 1) rainbowColors = options.rainbow_colors.map(parseHex);
      if (options.non_polymer_rainbow_color) nonPolymerColor = parseHex(options.non_polymer_rainbow_color);
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
  };
})();
