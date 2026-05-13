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
from typing import Dict, Any, Optional, Tuple
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

        candidates = [
            r"D:\FreeCAD 1.0\bin\python.exe",
            r"C:\Program Files\FreeCAD 1.0\bin\python.exe",
            r"D:\FreeCAD 0.21\bin\python.exe",
            r"C:\Program Files\FreeCAD 0.21\bin\python.exe",
        ]
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
            "FreeCAD not available. Install FreeCAD 1.0+ and set 'freecad.bin_path' in config.yaml"
        )

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
        """
        根据几何数据构建 FreeCAD 建模脚本。
        独立于 FreeCAD API，生成纯文本脚本供桥接器执行。
        """
        entities = geometry_data.get("entities", [])

        outline_entities = []
        hole_entities = []
        slot_entities = []

        for e in entities:
            layer = e.get("layer", "").upper()
            if "OUTLINE" in layer or "\u8f6e\u5ed3" in layer:
                outline_entities.append(e)
            elif "HOLE" in layer or "\u5b54" in layer:
                hole_entities.append(e)
            elif "SLOT" in layer or "\u69fd" in layer:
                slot_entities.append(e)

        script = [
            "doc = App.newDocument('CADModel')",
            "",
        ]

        extrude_height_val = float(extrude_height)

        for e in outline_entities:
            wire_code = self._entity_to_freecad_wire(e)
            if wire_code:
                script.append(f"# outline entity: {e.get('type')}")
                script.append(wire_code)
                script.append(f"wire = Part.Wire(edges)")
                script.append(f"if wire.isValid() and wire.isClosed():")
                script.append(f"    face = Part.Face(wire)")
                script.append(f"    solid = face.extrude(App.Vector(0, 0, {extrude_height_val}))")
                script.append(f"    Part.show(solid, 'BaseSolid')")
                script.append(f"")

        for e in hole_entities:
            hole_code = self._entity_to_freecad_wire(e)
            if hole_code:
                script.append(f"# hole entity: {e.get('type')}")
                script.append(hole_code)
                script.append(f"hole_wire = Part.Wire(edges)")
                script.append(f"if hole_wire.isValid() and hole_wire.isClosed():")
                script.append(f"    hole_face = Part.Face(hole_wire)")
                script.append(f"    hole_solid = hole_face.extrude(App.Vector(0, 0, {extrude_height_val}))")
                script.append(f"    for obj in doc.Objects:")
                script.append(f"        if hasattr(obj, 'Shape') and obj.Shape.isValid() and obj.Shape.Volume > 0:")
                script.append(f"            try:")
                script.append(f"                cut_result = obj.Shape.cut(hole_solid)")
                script.append(f"                doc.removeObject(obj.Name)")
                script.append(f"                Part.show(cut_result, 'BaseSolid')")
                script.append(f"                break")
                script.append(f"            except Exception:")
                script.append(f"                pass")
                script.append(f"")

        for e in slot_entities:
            slot_code = self._entity_to_freecad_wire(e)
            if slot_code:
                script.append(f"# slot entity: {e.get('type')}")
                script.append(slot_code)
                script.append(f"slot_wire = Part.Wire(edges)")
                script.append(f"if slot_wire.isValid() and slot_wire.isClosed():")
                script.append(f"    slot_face = Part.Face(slot_wire)")
                script.append(f"    slot_solid = slot_face.extrude(App.Vector(0, 0, {extrude_height_val}))")
                script.append(f"    for obj in doc.Objects:")
                script.append(f"        if hasattr(obj, 'Shape') and obj.Shape.isValid() and obj.Shape.Volume > 0:")
                script.append(f"            try:")
                script.append(f"                cut_result = obj.Shape.cut(slot_solid)")
                script.append(f"                doc.removeObject(obj.Name)")
                script.append(f"                Part.show(cut_result, 'BaseSolid')")
                script.append(f"                break")
                script.append(f"            except Exception:")
                script.append(f"                pass")
                script.append(f"")

        if not outline_entities and not script:
            script.append("# no entities to model")

        script.append("doc.recompute()")
        return "\n".join(script)

    def _entity_to_freecad_wire(self, entity: Dict) -> Optional[str]:
        etype = entity.get("type")
        lines = ["edges = []"]

        if etype == "LWPOLYLINE":
            vertices = entity.get("vertices", [])
            if len(vertices) >= 2:
                for i in range(len(vertices)):
                    nxt = (i + 1) % len(vertices)
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

        return "\n".join(lines)
