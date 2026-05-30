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
            logger.info("FreeCAD direct 模式：导入成功")
            return
        except ImportError:
            pass

        for candidate in self._find_project_freecad_candidates():
            if Path(candidate).exists():
                self.freecad_python = candidate
                self.freecad_available = True
                self.mode = "subprocess"
                logger.info(f"FreeCAD subprocess 模式（项目增强包）: {candidate}")
                return

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
                logger.info(f"FreeCAD subprocess 路径: {self.freecad_python}")
                return

        candidates = self._find_freecad_candidates()
        for c in candidates:
            if Path(c).exists():
                self.freecad_python = c
                self.freecad_available = True
                self.mode = "subprocess"
                logger.info(f"FreeCAD subprocess 模式（自动发现）: {c}")
                return

        self.freecad_available = False
        self.mode = "unavailable"
        logger.warning(
            "FreeCAD 不可用。请将 FreeCAD 增强包放入 tools/freecad/，"
            "或安装 FreeCAD 1.0+ 并在 .env 中设置 'FREECAD_BIN_PATH'"
        )

    @staticmethod
    def _find_project_freecad_candidates(project_root: Optional[Path] = None) -> list:
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        bundle_root = root / "tools" / "freecad"
        if not bundle_root.exists():
            return []
        candidates = [
            path
            for path in bundle_root.glob("*/bin/python.exe")
            if path.is_file()
        ]
        candidates.sort(key=lambda path: path.parent.parent.name, reverse=True)
        return [str(path) for path in candidates]

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

        参数:
            script_content: FreeCAD Python 脚本内容
            output_dir: 输出文件目录
            timeout: 超时秒数

        返回:
            {success, outputs, step_path, fcstd_path, stdout, stderr}
        """
        if not self.freecad_available:
            return {"success": False, "error": "FreeCAD 不可用"}

        output_dir = str(Path(output_dir).resolve())

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
            logger.error(f"direct 执行失败: {e}")
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

            logger.debug(f"启动 FreeCAD 子进程脚本: {script_file}")
            proc = subprocess.run(
                [self.freecad_python, script_file],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=output_dir or tempfile.gettempdir(),
                env={
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "OMP_NUM_THREADS": "1",
                },
            )

            combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            result = self._parse_marker_output(combined_output, output_dir)
            result["stdout"] = combined_output[-4000:]

            if proc.returncode == 0 and result.get("success"):
                return result

            if "BRIDGE_SUCCESS" not in combined_output:
                result["success"] = False
                result["error"] = result.get("error") or f"exit code {proc.returncode}"
                result["stdout"] = combined_output[-4000:]
            return result

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"执行超时: {timeout}s"}
        except Exception as e:
            logger.error(f"子进程执行失败: {e}")
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

    def _valid_shape(shape):
        try:
            return shape is not None and shape.isValid() and shape.Volume > 0
        except Exception:
            return False

    def _shape_from_value(value):
        if _valid_shape(value):
            return value
        try:
            shape = getattr(value, "Shape", None)
            if _valid_shape(shape):
                return shape
        except Exception:
            pass
        return None

    def _select_result_shape():
        preferred_vars = ["final_shape", "result_shape", "solid", "body", "part", "model"]
        for name in preferred_vars:
            val = globals().get(name)
            shape = _shape_from_value(val)
            if shape:
                print(f"BRIDGE_SELECTED:VAR:{{name}}", flush=True)
                return shape

        candidates = []
        if doc:
            for obj in doc.Objects:
                if hasattr(obj, "Shape") and _valid_shape(obj.Shape):
                    name = str(getattr(obj, "Name", "")).lower()
                    label = str(getattr(obj, "Label", "")).lower()
                    score = 0
                    if any(token in name or token in label for token in ["final", "result", "model", "body", "part", "plate", "flange"]):
                        score += 1000000000
                    try:
                        score += float(obj.Shape.Volume)
                    except Exception:
                        pass
                    candidates.append((score, obj))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            obj = candidates[0][1]
            print(f"BRIDGE_SELECTED:OBJ:{{obj.Name}}", flush=True)
            return obj.Shape

        return None

    exported = False
    result_shape = None
    if doc:
        try:
            doc.recompute()
        except Exception as recompute_error:
            print(f"BRIDGE_WARNING:DOC_RECOMPUTE_FAILED:{{recompute_error}}", flush=True)

        result_shape = _select_result_shape()
        if result_shape:
            try:
                result_shape.exportStep(step_path)
                print(f"BRIDGE_EXPORT:STEP:{{step_path}}", flush=True)
                exported = True
            except Exception as export_error:
                print(f"BRIDGE_WARNING:STEP_EXPORT_FAILED:{{export_error}}", flush=True)

        try:
            doc.saveAs(fcstd_path)
            print(f"BRIDGE_EXPORT:FCStd:{{fcstd_path}}", flush=True)
        except Exception:
            pass

    if not exported and doc:
        doc.saveAs(fcstd_path)
        print(f"BRIDGE_EXPORT:FCStd:{{fcstd_path}}", flush=True)

    if not result_shape:
        print("BRIDGE_ERROR:NO_VALID_SHAPE", flush=True)
        sys.exit(1)

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
            elif "PARTIAL_MODELING_RESULT:" in line:
                payload = line.split("PARTIAL_MODELING_RESULT:", 1)[1].strip()
                try:
                    metadata = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for key in ("completed_features", "skipped_features", "partial_completion_reason"):
                    if metadata.get(key):
                        result[key] = metadata[key]

        if not result["outputs"] and output_dir:
            for ext in (".step", ".STEP", ".FCStd"):
                for f in Path(output_dir).glob(f"*{ext}"):
                    result["outputs"].append(str(f))

        return result

    def build_geometry_script(self, geometry_data: Dict[str, Any],
                              extrude_height: float) -> str:
        from .script_builder import (
            group_entities_into_contours,
            contour_edges_to_code,
        )
        entities = geometry_data.get("entities", [])
        contours = group_entities_into_contours(entities)

        script = [
            "doc = App.newDocument('CADModel')",
            "",
        ]

        extrude_height_val = float(extrude_height)

        total_solids = 0
        for ci, contour in enumerate(contours):
            edges_code = contour_edges_to_code(contour)
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


