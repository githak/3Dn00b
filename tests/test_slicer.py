"""Optional end-to-end check: exported STLs must load and slice in a real slicer.

Runs only when PrusaSlicer is installed (e.g. `sudo apt install prusa-slicer`).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from threedn00b import project_io, templates

SLICER = shutil.which("prusa-slicer")
EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.3dn00b"))

pytestmark = pytest.mark.skipif(SLICER is None, reason="PrusaSlicer is not installed")


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_examples_slice_in_prusaslicer(path, tmp_path):
    project = project_io.load_project(path)
    for stl in project_io.export_stl_files(project, tmp_path, path.stem):
        info = subprocess.run([SLICER, "--info", str(stl)], capture_output=True, text=True,
                              timeout=120).stdout
        assert "manifold = yes" in info, info
        assert "number_of_parts =  1" in info, info
        gcode = stl.with_suffix(".gcode")
        result = subprocess.run([SLICER, "--export-gcode", "--center", "100,100", str(stl),
                                 "-o", str(gcode)], capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "estimated printing time" in gcode.read_text()


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_examples_open_as_3mf_in_prusaslicer(path, tmp_path):
    project = project_io.load_project(path)
    out = project_io.export_3mf_file(project, tmp_path, path.stem)
    info = subprocess.run([SLICER, "--info", str(out)], capture_output=True, text=True,
                          timeout=120).stdout
    parts = 2 if project.lid.enabled else 1
    assert info.count("manifold = yes") == parts, info
    gcode = out.with_suffix(".gcode")
    result = subprocess.run([SLICER, "--export-gcode", str(out), "-o", str(gcode)],
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("key", list(templates.TEMPLATES))
def test_templates_slice_in_prusaslicer(key, tmp_path):
    project = templates.from_template(key)
    for stl in project_io.export_stl_files(project, tmp_path, key):
        result = subprocess.run([SLICER, "--export-gcode", "--center", "100,100", str(stl),
                                 "-o", str(stl.with_suffix(".gcode"))],
                                capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stdout + result.stderr
