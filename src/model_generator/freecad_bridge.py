#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCAD 进程桥接层
支持双模式：
  1. direct 模式 - FreeCAD Python 环境中直接导入
  2. subprocess 模式 - 系统 Python 通过子进程调用 FreeCAD Python
"""

import json
import subprocess
import sys
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class FreeCADBridge:
    """
    FreeCAD 桥接器
    自动检测运行环境并选择最佳调用方式。
    在 FreeCAD 自带 Python 中运行时使用 direct 模式，
    在系统 Python 中运行时自动通过 subprocess 调用 FreeCAD Python。
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.App = None
        self.Part = None
        self.freecad_available = False
        self.freecad_python = None
        self.mode = "unavailable"
        self._detect_environment()

    def _detect_environment(self):
        try:
            import FreeCAD as App
            import Part
            self.App = App
            self.Part = Part
            self.freecad_available = True
            self.mode = "direct"
            logger.info("FreeCAD direct mode: imported successfully")
            return
        except ImportError:
            pass

        fc_config = self.config.get("freecad", {})
        if not isinstance(fc_config, dict):
            fc_config = {}
        fc_path = fc_config.get("bin_path", "") or self.config.get("bin_path", "")

        if fc_path:
            python_path = Path(fc_path) / "python.exe"
            if python_path.exists():
                self.freecad_python = str(python_path)
                self.freecad_available = True
                self.mode = "subprocess"
                logger.info(f"FreeCAD subprocess mode: {self.freecad_python}")
                return

        candidates = self._find_freecad_candidates()
        for c in candidates:
            if Path(c).exists():
                self.freecad_python = c
                self.freecad_available = True
                self.mode = "subprocess"
                logger.info(f"FreeCAD subprocess mode (auto-detected): {c}")
                return

        self.freecad_available = False
        self.mode = "unavailable"
        logger.warning(
            "FreeCAD not available. Install FreeCAD 1.0+ and set 'FREECAD_BIN_PATH' in .env"
        )

    @staticmethod
    def _find_freecad_candidates() -> list:
        candidates = []
        if os.name == "nt":
            drives = ["D:\\", "C:\\"]
            versions = ["FreeCAD 1.0", "FreeCAD 0.21", "FreeCAD 0.20"]
            for drive in drives:
                for ver in versions:
                    candidates.append(rf"{drive}\{ver}\bin\python.exe")
                    base = rf"{drive}\Program Files\{ver}\bin\python.exe"
                    if base not in candidates:
                        candidates.append(base)
        return candidates

    def execute_script(self, script_content: str, output_dir: str,
                       timeout: int = 300) -> Dict[str, Any]:
        """
        执行 FreeCAD Python 脚本（根据模式自动选择执行方式）

        Args:
            script_content: FreeCAD Python 脚本内容
            output_dir: 输出文件目录
            timeout: 超时秒数

        Returns:
            {success, outputs, step_path, fcstd_path, stdout, stderr}
        """
        if not self.freecad_available:
            return {"success": False, "error": "FreeCAD not available"}

        if self.mode == "direct":
            return self._execute_direct(script_content, output_dir)
        return self._execute_subprocess(script_content, output_dir, timeout)

    def _execute_direct(self, script_content: str, output_dir: str) -> Dict[str, Any]:
        try:
            doc = self.App.newDocument("BridgeModel")
            local_vars = {
                "App": self.App,
                "Part": self.Part,
                "FreeCAD": self.App,
                "doc": doc,
            }
            exec(script_content, {"__builtins__": __builtins__}, local_vars)
            doc.recompute()

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            results = {"success": True, "outputs": []}

            step_path = out / "model.step"
            fcstd_path = out / "model.FCStd"
            exported_step = False

            for obj in doc.Objects:
                if hasattr(obj, "Shape") and obj.Shape.isValid() and obj.Shape.Volume > 0:
                    try:
                        obj.Shape.exportStep(str(step_path))
                        results["step_path"] = str(step_path)
                        results["outputs"].append(str(step_path))
                        exported_step = True
                        break
                    except Exception:
                        pass

            if not exported_step:
                try:
                    doc.saveAs(str(fcstd_path))
                    results["fcstd_path"] = str(fcstd_path)
                    results["outputs"].append(str(fcstd_path))
                except Exception:
                    pass
            else:
                try:
                    doc.saveAs(str(fcstd_path))
                    results["fcstd_path"] = str(fcstd_path)
                    results["outputs"].append(str(fcstd_path))
                except Exception:
                    pass

            self.App.closeDocument(doc.Name)
            return results

        except Exception as e:
            logger.error(f"Direct execution failed: {e}")
            return {"success": False, "error": str(e)}

    def _execute_subprocess(self, script_content: str, output_dir: str,
                            timeout: int) -> Dict[str, Any]:
        full_script = self._build_subprocess_script(script_content, output_dir)

        script_file = None
        try:
            fd, script_path = tempfile.mkstemp(suffix=".py", prefix="cad_bridge_")
            os.close(fd)
            script_file = script_path
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(full_script)

            logger.debug(f"Launching FreeCAD subprocess with script: {script_file}")
            proc = subprocess.run(
                [self.freecad_python, script_file],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=output_dir or tempfile.gettempdir(),
                env={**os.environ, "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1"},
            )

            combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            result = self._parse_marker_output(combined_output, output_dir)

            if proc.returncode == 0 and result.get("success"):
                return result

            if "BRIDGE_SUCCESS" not in combined_output:
                result["success"] = False
                result["error"] = result.get("error") or f"exit code {proc.returncode}"
                result["stdout"] = combined_output[-4000:]
            return result

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"timeout after {timeout}s"}
        except Exception as e:
            logger.error(f"Subprocess execution failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if script_file:
                try:
                    os.unlink(script_file)
                except Exception:
                    pass

    def _build_subprocess_script(self, script: str, output_dir: str) -> str:
        fc_bin_dir = str(Path(self.freecad_python).parent) if self.freecad_python else ""
        indented_script = "\n".join("    " + line if line.strip() else "" for line in script.splitlines())
        return f'''# -*- coding: utf-8 -*-
import sys, os, json, traceback
from pathlib import Path

OUTPUT_DIR = Path(r"{output_dir}")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, r"{fc_bin_dir}")

print("BRIDGE_START", flush=True)

try:
    import FreeCAD as App
    import Part

{indented_script}

    doc = App.ActiveDocument
    if doc is None:
        for d in App.listDocuments().values():
            doc = d
            break

    step_path = str(OUTPUT_DIR / "model.step")
    fcstd_path = str(OUTPUT_DIR / "model.FCStd")

    exported = False
    if doc:
        for obj in doc.Objects:
            if hasattr(obj, "Shape") and obj.Shape.isValid() and obj.Shape.Volume > 0:
                try:
                    obj.Shape.exportStep(step_path)
                    print(f"BRIDGE_EXPORT:STEP:{{step_path}}", flush=True)
                    exported = True
                    break
                except Exception:
                    pass

        try:
            doc.saveAs(fcstd_path)
            print(f"BRIDGE_EXPORT:FCStd:{{fcstd_path}}", flush=True)
        except Exception:
            pass

    if not exported and doc:
        doc.saveAs(fcstd_path)
        print(f"BRIDGE_EXPORT:FCStd:{{fcstd_path}}", flush=True)

    print("BRIDGE_SUCCESS", flush=True)
    sys.exit(0)

except Exception as e:
    print(f"BRIDGE_ERROR:{{str(e)}}", flush=True)
    traceback.print_exc()
    sys.exit(1)
'''

    def _parse_marker_output(self, output: str, output_dir: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"success": False, "outputs": []}
        for line in output.splitlines():
            line = line.strip()
            if "BRIDGE_SUCCESS" in line:
                result["success"] = True
            elif "BRIDGE_ERROR:" in line:
                result["error"] = line.split("BRIDGE_ERROR:", 1)[1].strip()
            elif "BRIDGE_EXPORT:STEP:" in line:
                p = line.split("BRIDGE_EXPORT:STEP:", 1)[1].strip()
                result["step_path"] = p
                result["outputs"].append(p)
            elif "BRIDGE_EXPORT:FCStd:" in line:
                p = line.split("BRIDGE_EXPORT:FCStd:", 1)[1].strip()
                result["fcstd_path"] = p
                result["outputs"].append(p)

        if not result["outputs"] and output_dir:
            for ext in (".step", ".STEP", ".FCStd"):
                for f in Path(output_dir).glob(f"*{ext}"):
                    result["outputs"].append(str(f))

        return result

    def build_geometry_script(self, geometry_data: Dict[str, Any],
                              extrude_height: float) -> str:
        entities = geometry_data.get("entities", [])
        contours = self._group_contours(entities)

        script = [
            "doc = App.newDocument('CADModel')",
            "",
        ]

        extrude_height_val = float(extrude_height)

        total_solids = 0
        for ci, contour in enumerate(contours):
            edges_code = self._contour_edges_to_code(contour)
            if not edges_code:
                continue
            script.append(f"# 轮廓 {ci+1} ({len(contour)} 个实体)")
            for line in edges_code:
                script.append(line)
            script.append(f"wire = Part.Wire(edges)")
            script.append(f"if wire.isValid() and wire.isClosed():")
            script.append(f"    face = Part.Face(wire)")
            script.append(f"    solid = face.extrude(App.Vector(0, 0, {extrude_height_val}))")
            script.append(f"    Part.show(solid, 'Solid_{ci+1}')")
            script.append(f"else:")
            script.append(f"    print('BRIDGE_WARNING: 轮廓 {ci+1} 未闭合, 跳过')")
            script.append("")
            total_solids += 1

        if total_solids == 0:
            script.append("print('BRIDGE_WARNING: 没有有效的闭合轮廓可建模')")

        script.append("doc.recompute()")
        return "\n".join(script)

    @staticmethod
    def _group_contours(entities: List[Dict]) -> List[List[Dict]]:
        import math

        TOL = 1e-3
        processed = set()
        contours = []

        def get_endpoints(e):
            t = e.get("type")
            if t == "LINE":
                s = tuple(e.get("start", [0, 0]))[:2]
                e_pt = tuple(e.get("end", [0, 0]))[:2]
                return s, e_pt
            elif t == "LWPOLYLINE":
                v = e.get("vertices", [])
                if len(v) >= 2:
                    return tuple(v[0])[:2], tuple(v[-1])[:2]
                return None, None
            elif t == "ARC":
                center = e.get("center", [0, 0])
                cx, cy = center[0], center[1]
                r = e.get("radius", 0)
                sa = math.radians(e.get("start_angle", 0))
                ea = math.radians(e.get("end_angle", 0))
                sx, sy = cx + r * math.cos(sa), cy + r * math.sin(sa)
                ex, ey = cx + r * math.cos(ea), cy + r * math.sin(ea)
                return (sx, sy), (ex, ey)
            return None, None

        def pts_close(p1, p2):
            return abs(p1[0] - p2[0]) < TOL and abs(p1[1] - p2[1]) < TOL

        def follow_chain(start_pt, remaining):
            chain = []
            current_pt = start_pt
            while True:
                found = None
                found_idx = -1
                for ri, (_, entity) in enumerate(remaining):
                    s, e = get_endpoints(entity)
                    if s is None:
                        continue
                    if pts_close(current_pt, s):
                        found = entity
                        found_idx = ri
                        next_pt = e
                        break
                    elif pts_close(current_pt, e):
                        found = entity
                        found_idx = ri
                        next_pt = s
                        break
                if found is None:
                    break
                chain.append(found)
                remaining.pop(found_idx)
                current_pt = next_pt
                if pts_close(current_pt, start_pt):
                    break
            return chain, current_pt

        model_entities = [e for e in entities
                          if e.get("type") in ("LINE", "CIRCLE", "ARC", "LWPOLYLINE")]

        for i, entity in enumerate(model_entities):
            if i in processed:
                continue
            etype = entity.get("type")
            if etype == "CIRCLE":
                contours.append([entity])
                processed.add(i)
                continue
            if etype == "LWPOLYLINE" and entity.get("closed", False):
                contours.append([entity])
                processed.add(i)
                continue

            start, end = get_endpoints(entity)
            if start is None:
                continue

            remaining = [(j, e) for j, e in enumerate(model_entities) if j != i and j not in processed]
            chain, final_pt = follow_chain(end, remaining)

            contour = [entity] + (chain or [])
            for j in range(len(model_entities)):
                for c in (chain or []):
                    if c is model_entities[j]:
                        processed.add(j)

            if chain and pts_close(final_pt, start):
                contours.append(contour)
            elif chain:
                contours.append(contour)
            else:
                contours.append([entity])

            processed.add(i)

        logger.info(f"轮廓分组: {len(model_entities)} 个实体 -> {len(contours)} 个轮廓")
        return contours

    @staticmethod
    def _contour_edges_to_code(contour: List[Dict]) -> Optional[List[str]]:
        lines = ["edges = []"]
        for entity in contour:
            etype = entity.get("type")
            if etype == "LWPOLYLINE":
                vertices = entity.get("vertices", [])
                if len(vertices) >= 2:
                    for i in range(len(vertices)):
                        nxt = (i + 1) % len(vertices)
                        if not entity.get("closed") and i == len(vertices) - 1:
                            break
                        lines.append(
                            f"edges.append(Part.LineSegment("
                            f"App.Vector({vertices[i][0]}, {vertices[i][1]}, 0), "
                            f"App.Vector({vertices[nxt][0]}, {vertices[nxt][1]}, 0)).toShape())"
                        )
                else:
                    return None
            elif etype == "ELLIPSE":
                vertices = entity.get("vertices", [])
                if len(vertices) >= 3:
                    for i in range(len(vertices) - 1):
                        lines.append(
                            f"edges.append(Part.LineSegment("
                            f"App.Vector({vertices[i][0]}, {vertices[i][1]}, 0), "
                            f"App.Vector({vertices[i+1][0]}, {vertices[i+1][1]}, 0)).toShape())"
                        )
                    if entity.get("closed", False):
                        lines.append(
                            f"edges.append(Part.LineSegment("
                            f"App.Vector({vertices[-1][0]}, {vertices[-1][1]}, 0), "
                            f"App.Vector({vertices[0][0]}, {vertices[0][1]}, 0)).toShape())"
                        )
                else:
                    return None
            elif etype == "SPLINE":
                vertices = entity.get("vertices", [])
                if len(vertices) >= 2:
                    for i in range(len(vertices) - 1):
                        lines.append(
                            f"edges.append(Part.LineSegment("
                            f"App.Vector({vertices[i][0]}, {vertices[i][1]}, 0), "
                            f"App.Vector({vertices[i+1][0]}, {vertices[i+1][1]}, 0)).toShape())"
                        )
                    if entity.get("closed", False):
                        lines.append(
                            f"edges.append(Part.LineSegment("
                            f"App.Vector({vertices[-1][0]}, {vertices[-1][1]}, 0), "
                            f"App.Vector({vertices[0][0]}, {vertices[0][1]}, 0)).toShape())"
                        )
                else:
                    return None
            elif etype == "LINE":
                x1, y1 = entity["start"][0], entity["start"][1]
                x2, y2 = entity["end"][0], entity["end"][1]
                lines.append(
                    f"edges.append(Part.LineSegment("
                    f"App.Vector({x1}, {y1}, 0), App.Vector({x2}, {y2}, 0)).toShape())"
                )
            elif etype == "CIRCLE":
                cx, cy = entity["center"][0], entity["center"][1]
                r = entity["radius"]
                lines.append(
                    f"circle = Part.Circle(App.Vector({cx}, {cy}, 0), App.Vector(0, 0, 1), {r})"
                )
                lines.append("edges.append(circle.toShape())")
            elif etype == "ARC":
                cx, cy = entity["center"][0], entity["center"][1]
                r = entity["radius"]
                sa = entity.get("start_angle", 0) * 3.14159265 / 180.0
                ea = entity.get("end_angle", 360) * 3.14159265 / 180.0
                lines.append(
                    f"circle = Part.Circle(App.Vector({cx}, {cy}, 0), App.Vector(0, 0, 1), {r})"
                )
                lines.append(f"arc = Part.ArcOfCircle(circle, {sa}, {ea})")
                lines.append("edges.append(arc.toShape())")
            else:
                return None
        return lines
