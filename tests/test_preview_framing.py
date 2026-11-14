"""The 3D preview frames a preset view as Blender renders it (app/static/framing.js).

With no camera sent, app/blender_render.py frames the molecule with Molecular Nodes'
canvas.look_at. The preview runs the same solve on what Mol* draws, so an untouched
preset view renders as shown, and the request (and its cache key) carries no camera.
"""

import importlib.util
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest

from app.blender_render import WORLD_SCALE
from app.options import Resolution, Viewpoint

ROOT = Path(__file__).resolve().parent.parent
FRAMING_JS = ROOT / "app" / "static" / "framing.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

VIEWPOINTS = list(get_args(Viewpoint))
RESOLUTIONS = list(get_args(Resolution))
MARGIN = 0.05  # Molecular Nodes' default in Canvas.look_at

# Runs Framing.fitter on each job: {viewpoint, size, points: [[x, y, z, radius], ...]}.
FIT_JS = """
const Framing = require(process.argv[1]);
const jobs = JSON.parse(require("fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(jobs.map(({ viewpoint, size, points }) => {
  const fit = Framing.fitter(viewpoint, size[0], size[1]);
  for (const [x, y, z, r] of points) fit.add(x, y, z, r);
  return { ...fit.camera(), axes: Framing.viewpointAxes(viewpoint) };
})));
"""


def fit(jobs: list[dict]) -> list[dict]:
    proc = subprocess.run(
        [NODE, "-e", FIT_JS, str(FRAMING_JS)],
        input=json.dumps(jobs), capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def size(resolution: str) -> list[int]:
    return [int(v) for v in resolution.split("x")]


def molecule(seed: int = 4, n: int = 300, radius: float = 0.0) -> list[list[float]]:
    """An elongated, lopsided cloud of atoms away from the origin, in ångström."""
    rng = random.Random(seed)
    points = []
    for _ in range(n):
        x, y, z = rng.gauss(0, 30), rng.gauss(0, 12), rng.gauss(0, 7)
        points.append([x + 0.4 * y + 15, y - 40 + 0.002 * x * x, z + 25 + 0.3 * x, radius])
    return points


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def unit(v):
    length = math.hypot(*v)
    return [x / length for x in v]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def projected(camera: dict, resolution: str, points) -> tuple[list[float], list[float]]:
    """Where the points land, as fractions of the half-width and half-height of the image."""
    width, height = size(resolution)
    forward = unit(sub(camera["target"], camera["position"]))
    right = unit(cross(forward, camera["up"]))
    up = cross(right, forward)
    tan_y = math.tan(math.radians(camera["fov"]) / 2)
    tan_x = tan_y * width / height
    xs, ys = [], []
    for p in points:
        rel = sub(p[:3], camera["position"])
        depth = dot(rel, forward)
        xs.append(dot(rel, right) / (depth * tan_x))
        ys.append(dot(rel, up) / (depth * tan_y))
    return xs, ys


def test_field_of_view_is_blenders_50_mm_lens_on_a_36_mm_sensor():
    jobs = [{"viewpoint": "default", "size": size(r), "points": molecule(n=5)} for r in RESOLUTIONS]
    for resolution, camera in zip(RESOLUTIONS, fit(jobs)):
        width, height = size(resolution)
        # The sensor spans the longer side: 39.6° across a landscape or square image.
        expected = math.degrees(2 * math.atan(18 / 50 * min(width, height) / width))
        assert camera["fov"] == pytest.approx(expected)


@pytest.mark.parametrize("resolution", RESOLUTIONS)
def test_preset_view_fills_the_frame_up_to_the_margin(resolution):
    points = molecule()
    jobs = [{"viewpoint": v, "size": size(resolution), "points": points} for v in VIEWPOINTS]
    for viewpoint, camera in zip(VIEWPOINTS, fit(jobs)):
        # Looking along the preset direction, with its up direction.
        forward = unit(sub(camera["target"], camera["position"]))
        assert forward == pytest.approx(camera["axes"]["forward"], abs=1e-9), viewpoint
        assert camera["up"] == pytest.approx(camera["axes"]["up"], abs=1e-9), viewpoint
        # Every point in frame; on the tighter axis the molecule reaches the margin on both sides.
        xs, ys = projected(camera, resolution, points)
        edge = 1 - MARGIN
        assert max(map(abs, xs + ys)) == pytest.approx(edge), viewpoint
        tight = xs if max(map(abs, xs)) > max(map(abs, ys)) else ys
        assert (min(tight), max(tight)) == pytest.approx((-edge, edge)), viewpoint
        # The preview turns about a point on the line of sight inside the molecule.
        depths = [dot(sub(p[:3], camera["position"]), forward) for p in points]
        assert dot(sub(camera["target"], camera["position"]), forward) == pytest.approx(
            (min(depths) + max(depths)) / 2)


def test_a_sphere_counts_as_the_corners_of_its_cube():
    spheres = molecule(n=40, radius=1.7)
    corners = [[x + dx, y + dy, z + dz, 0]
               for x, y, z, r in spheres for dx in (-r, r) for dy in (-r, r) for dz in (-r, r)]
    a, b = fit([{"viewpoint": "front", "size": [1280, 720], "points": p} for p in (spheres, corners)])
    assert a["position"] == pytest.approx(b["position"])


# Molecular Nodes itself, in Blender: frame a mesh (atoms) and a point cloud (spheres) with
# canvas.look_at, as app/blender_render.py does, and report the cameras in ångström.
BLENDER_SCRIPT = """
import json, math, sys
import bpy, numpy as np, molecularnodes as mn

jobs = json.load(sys.stdin)
scale = jobs[0]["scale"]
canvas = mn.Canvas(mn.scene.Cycles(samples=1, device="CPU"), resolution=(1280, 720), transparent=True)
out = []
for job in jobs:
    points = np.array(job["points"], dtype=float)
    if points[:, 3].any():
        data = bpy.data.pointclouds.new("framed")
        data.resize(len(points))
        data.attributes["position"].data.foreach_set("vector", (points[:, :3] * scale).ravel())
        data.attributes.new("radius", "FLOAT", "POINT").data.foreach_set("value", points[:, 3] * scale)
    else:
        data = bpy.data.meshes.new("framed")
        data.from_pydata((points[:, :3] * scale).tolist(), [], [])
    obj = bpy.data.objects.new("framed", data)
    canvas.scene.collection.objects.link(obj)
    canvas.scene.render.resolution_x, canvas.scene.render.resolution_y = job["size"]
    canvas.look_at(obj, viewpoint=job["viewpoint"])
    bpy.context.view_layer.update()
    m = canvas.scene.camera.matrix_world
    top = canvas.camera.frame_bounds(canvas.scene)[3]
    out.append({
        "position": [x / scale for x in m.translation],
        "forward": list(-m.col[2].xyz),
        "up": list(m.col[1].xyz),
        "fov": math.degrees(2 * math.atan(top)),
    })
    bpy.data.objects.remove(obj)
print("RESULT" + json.dumps(out))
"""


@pytest.mark.skipif(importlib.util.find_spec("molecularnodes") is None,
                    reason="molecularnodes is not installed")
def test_preview_frames_preset_views_as_molecular_nodes_does():
    atoms, spheres = molecule(), molecule(seed=7, n=120, radius=1.7)
    jobs = [{"viewpoint": v, "size": size(r), "points": p, "scale": WORLD_SCALE}
            for v in VIEWPOINTS for r in ("1280x720", "800x800") for p in (atoms, spheres)]
    proc = subprocess.run([sys.executable, "-c", BLENDER_SCRIPT], input=json.dumps(jobs),
                          capture_output=True, text=True, timeout=600, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT"))
    blender = json.loads(line[len("RESULT"):])
    for job, preview, expected in zip(jobs, fit(jobs), blender):
        case = (job["viewpoint"], job["size"], "spheres" if job["points"][0][3] else "atoms")
        # Blender works in single precision, at 0.1 times these coordinates.
        assert preview["position"] == pytest.approx(expected["position"], abs=0.02), case
        assert preview["axes"]["forward"] == pytest.approx(expected["forward"], abs=1e-5), case
        assert preview["up"] == pytest.approx(expected["up"], abs=1e-5), case
        assert preview["fov"] == pytest.approx(expected["fov"], abs=1e-4), case
