"use strict";

/*
 * Molecular Nodes' framing of a preset view, so the 3D preview shows a preset view as Blender
 * renders it when no camera is sent. app/blender_render.py calls
 * canvas.look_at(mol, viewpoint=...), which in molecularnodes 520.2.0 (scene/base.py,
 * scene/camera.py, framing.py):
 *
 *   - turns the camera to the preset rotation (Camera.set_viewpoint);
 *   - keeps the camera's lens: 50 mm on Blender's 36 mm sensor, fitted to the image's longer side;
 *   - moves the camera, without turning it, to the closest place from which every point of the
 *     drawn geometry lies inside the frame shrunk by a 5% margin, centred across the frame
 *     (framing.fit_camera_to_points, an exact solve over the points);
 *   - grows a point cloud's points by their radius to the corners of a cube
 *     (blender/utils.py, _component_positions).
 *
 * The preview feeds the same solve with what Mol* draws (preview.js). tests/test_preview_framing.py
 * checks it against Molecular Nodes itself. Coordinates are in ångström, as in the structure file;
 * Blender's are 0.1 times these, which changes nothing here.
 */
const Framing = (() => {
  const LENS_MM = 50;
  const SENSOR_MM = 36;
  const MARGIN = 0.05;
  const MIN_DISTANCE = 0.01;  // Å: Molecular Nodes' 1e-3 Blender units

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

  /** A preset view's camera axes (a Blender camera looks down its -Z, with +Y up). */
  function viewpointAxes(name) {
    const m = eulerMatrix(VIEWPOINT_EULER[name] || VIEWPOINT_EULER.default);
    return { right: apply(m, [1, 0, 0]), up: apply(m, [0, 1, 0]), forward: apply(m, [0, 0, -1]) };
  }

  /** Half the frame's width and height at unit distance (Blender's view frame, sensor fit "AUTO"). */
  function frameHalfSize(width, height) {
    const scale = SENSOR_MM / 2 / LENS_MM / Math.max(width, height);
    return [scale * width, scale * height];
  }

  /** The vertical field of view in degrees (Mol*'s field of view is vertical). */
  function fieldOfView(width, height) {
    return (2 * Math.atan(frameHalfSize(width, height)[1]) * 180) / Math.PI;
  }

  /**
   * Collects the drawn points of a preset view; camera() then gives the view
   * Canvas.look_at would set: { position, target, up, fov }, or null with no points.
   * The target, the point the preview turns about, is on the line of sight
   * halfway through the molecule's depth.
   */
  function fitter(viewpoint, width, height, margin = MARGIN) {
    const { right, up, forward } = viewpointAxes(viewpoint);
    const [halfX, halfY] = frameHalfSize(width, height).map((h) => h * (1 - margin));
    // The binding point for each side of the frame, as in fit_camera_to_points.
    let boundRight = -Infinity;
    let boundLeft = -Infinity;
    let boundTop = -Infinity;
    let boundBottom = -Infinity;
    let near = Infinity;
    let far = -Infinity;
    let count = 0;

    function point(x, y, z) {
      const a = x * right[0] + y * right[1] + z * right[2];
      const b = x * up[0] + y * up[1] + z * up[2];
      const d = x * forward[0] + y * forward[1] + z * forward[2];
      if (a - halfX * d > boundRight) boundRight = a - halfX * d;
      if (-halfX * d - a > boundLeft) boundLeft = -halfX * d - a;
      if (b - halfY * d > boundTop) boundTop = b - halfY * d;
      if (-halfY * d - b > boundBottom) boundBottom = -halfY * d - b;
      if (d < near) near = d;
      if (d > far) far = d;
      count += 1;
    }

    /** A point, or a sphere of this radius (taken as the corners of its cube). */
    function add(x, y, z, radius = 0) {
      if (!(radius > 0)) {
        point(x, y, z);
        return;
      }
      for (let i = 0; i < 8; i++) {
        point(x + (i & 1 ? radius : -radius), y + (i & 2 ? radius : -radius), z + (i & 4 ? radius : -radius));
      }
    }

    function camera() {
      if (!count) return null;
      const depth = Math.min(
        (boundRight + boundLeft) / (-2 * halfX),
        (boundTop + boundBottom) / (-2 * halfY),
        near - MIN_DISTANCE,
      );
      const across = (boundRight - boundLeft) / 2;
      const along = (boundTop - boundBottom) / 2;
      const at = (d) => [0, 1, 2].map((i) => across * right[i] + along * up[i] + d * forward[i]);
      return { position: at(depth), target: at((near + far) / 2), up, fov: fieldOfView(width, height) };
    }

    return { add, camera, get count() { return count; } };
  }

  return { MARGIN, VIEWPOINT_EULER, viewpointAxes, fieldOfView, fitter };
})();

if (typeof module !== "undefined") module.exports = Framing;
