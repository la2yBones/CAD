#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI生成的FreeCAD脚本执行器
支持 direct 和 subprocess 双模式执行
"""
import sys
import os
import re
import tempfile
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AIScriptRunner:
    """
    AI脚本执行器 - 运行AI生成的FreeCAD Python脚本
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.bridge = None
        self.App = None
        self.Part = None
        self._init_freecad()

    def _init_freecad(self):
        from .freecad_bridge import FreeCADBridge
        self.bridge = FreeCADBridge(self.config)
        if self.bridge.mode == "direct":
            self.App = self.bridge.App
            self.Part = self.bridge.Part
            logger.info("FreeCAD 环境就绪（direct 模式）")
        elif self.bridge.mode == "subprocess":
            self.App = None
            self.Part = None
            logger.info("将通过子进程调用 FreeCAD")
        else:
            self.App = None
            self.Part = None
            logger.warning("FreeCAD 不可用")

    def run_script(self, script_content: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        运行AI生成的FreeCAD脚本（双模式自适应）

        ??:
            script_content: Python脚本内容
            output_path: 可选的STEP输出路径

        ??:
            包含执行结果的字典
        """
        if not self.bridge or not self.bridge.freecad_available:
            return {"success": False, "error": "FreeCAD 不可用"}

        script_content = self._normalize_generated_script(script_content)

        if self.bridge.mode == "subprocess":
            return self._run_via_bridge(script_content, output_path)

        return self._run_direct(script_content, output_path)

    def _normalize_generated_script(self, script_content: str) -> str:
        """发送到 FreeCAD 前修正常见 AI 几何脚本问题。"""
        pattern = re.compile(
            r"^(?P<prefix>\s*\w+\s*=\s*Part\.(?:LineSegment|ArcOfCircle)\(.*\))\s*$",
            re.MULTILINE,
        )

        def add_to_shape(match: re.Match[str]) -> str:
            line = match.group("prefix")
            if line.endswith(".toShape()"):
                return line
            return f"{line}.toShape()"

        return pattern.sub(add_to_shape, script_content)

    def _run_via_bridge(self, script_content: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        logger.info("通过子进程桥接执行 AI 脚本")
        requested_step = Path(output_path).resolve() if output_path else None
        if requested_step:
            with tempfile.TemporaryDirectory(prefix="ai_model_") as temp_output_dir:
                result = self.bridge.execute_script(script_content, temp_output_dir)
                return self._normalize_bridge_outputs(result, requested_step)

        output_dir = tempfile.mkdtemp(prefix="ai_model_")
        result = self.bridge.execute_script(script_content, output_dir)
        return self._normalize_bridge_outputs(result, requested_step)

    def _normalize_bridge_outputs(
        self,
        result: Dict[str, Any],
        requested_step: Optional[Path],
    ) -> Dict[str, Any]:

        if result.get("success"):
            step_path = result.get("step_path")
            fcstd_path = result.get("fcstd_path")
            copy_errors = []

            if requested_step and step_path and Path(step_path).exists():
                try:
                    requested_step.parent.mkdir(parents=True, exist_ok=True)
                    if Path(step_path).resolve() != requested_step:
                        shutil.copy2(step_path, requested_step)
                    step_path = str(requested_step)
                except Exception as e:
                    logger.warning(f"复制STEP到目标路径失败: {e}")
                    copy_errors.append(f"copy STEP failed: {e}")

            if requested_step and fcstd_path and Path(fcstd_path).exists():
                try:
                    requested_fcstd = requested_step.with_suffix(".FCStd")
                    if Path(fcstd_path).resolve() != requested_fcstd:
                        shutil.copy2(fcstd_path, requested_fcstd)
                    fcstd_path = str(requested_fcstd)
                except Exception as e:
                    logger.warning(f"复制FCStd到目标路径失败: {e}")
                    copy_errors.append(f"copy FCStd failed: {e}")

            if requested_step and copy_errors:
                return {
                    "success": False,
                    "error": "; ".join(copy_errors),
                    "step_path": step_path,
                    "fcstd_path": fcstd_path,
                    "sandbox_mode": True,
                }

            return {
                "success": True,
                "step_path": step_path,
                "fcstd_path": fcstd_path,
                "sandbox_mode": True,
            }

        return {
            "success": False,
            "error": result.get("error", "未知子进程错误"),
            "stdout": result.get("stdout", ""),
        }

    def _run_direct(self, script_content: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        logger.info("执行 AI 脚本（direct 模式）")

        try:
            # 创建新文档
            doc = self.App.newDocument("AI_Model")
            
            # 准备脚本 - 插入明确的导入语句
            modified_script = """
import FreeCAD as App
import Part

""" + script_content

            # 准备执行环境
            local_vars = {
                "App": self.App,
                "Part": self.Part,
                "FreeCAD": self.App,
                "doc": doc
            }

            # 执行脚本
            logger.info("开始执行AI生成的FreeCAD脚本")
            
            # 在全局命名空间执行，避免列表解析的问题
            global_vars = globals().copy()
            global_vars.update({
                "App": self.App,
                "Part": self.Part,
                "FreeCAD": self.App,
                "doc": doc
            })
            
            exec(modified_script, global_vars, {})
            doc.recompute()
            logger.info("脚本执行完成")

            # 查找最终的形状对象
            result_shape = None
            final_obj = None
            
            # 从执行后的全局变量获取文档（因为脚本可能自己新建了文档）
            if "doc" in global_vars and hasattr(global_vars["doc"], "Objects"):
                doc = global_vars["doc"]
            
            # 也检查ActiveDocument
            if hasattr(self.App, "ActiveDocument") and self.App.ActiveDocument:
                doc = self.App.ActiveDocument

            logger.info(f"文档对象数: {len(doc.Objects)}")
            
            # 先检查全局变量里的solid/final_shape等
            possible_names = ["solid", "final_shape", "result_shape", "body", "part", "extrusion"]
            for name in possible_names:
                if name in global_vars:
                    val = global_vars[name]
                    if hasattr(val, "isValid") and val.isValid() and hasattr(val, "Volume"):
                        result_shape = val
                        logger.info(f"从全局变量找到形状: {name}")
                        break

            # 如果没找到，再检查文档对象
            if not result_shape:
                valid_shapes = []
                for obj in doc.Objects:
                    if hasattr(obj, "Shape") and obj.Shape.isValid():
                        try:
                            if obj.Shape.Volume > 0:
                                valid_shapes.append(obj)
                                logger.debug(f"有效对象: {obj.Name} ({obj.Shape.Volume:.2f} mm^3)")
                        except:
                            pass

                if valid_shapes:
                    # 优先找名称匹配的
                    for obj in valid_shapes:
                        obj_name = obj.Name.lower() if hasattr(obj, "Name") else ""
                        obj_label = obj.Label.lower() if hasattr(obj, "Label") else ""
                        if any(s in obj_name or s in obj_label for s in ["final", "model", "body", "part", "base", "plate"]):
                            final_obj = obj
                            result_shape = obj.Shape
                            logger.info(f"找到匹配名称的对象: {obj.Name}")
                            break
                    
                    # 如果没找到，取最大体积的
                    if not result_shape:
                        valid_shapes.sort(key=lambda o: o.Shape.Volume, reverse=True)
                        final_obj = valid_shapes[0]
                        result_shape = final_obj.Shape
                        logger.info(f"取最大体积对象: {final_obj.Name} ({final_obj.Shape.Volume:.2f} mm^3)")

            result = {
                "success": True,
                "document": doc,
                "shape": result_shape,
                "object": final_obj
            }

            # 导出STEP
            if output_path:
                output_dir = Path(output_path).parent
                output_dir.mkdir(parents=True, exist_ok=True)
                fcstd_path = str(Path(output_path).with_suffix(".FCStd"))
                
                try:
                    # 先保存FCStd，总是有效的
                    doc.saveAs(fcstd_path)
                    logger.info(f"FCStd已保存: {fcstd_path}")
                    result["fcstd_path"] = fcstd_path
                    
                    # 然后尝试导出STEP
                    if result_shape:
                        try:
                            result_shape.exportStep(output_path)
                            if Path(output_path).exists():
                                size = Path(output_path).stat().st_size
                                logger.info(f"STEP已导出: {output_path} ({size} bytes)")
                                result["step_path"] = output_path
                        except Exception as e1:
                            logger.warning(f"直接导出STEP失败: {e1}")
                            # 尝试通过文档对象导出
                            if final_obj:
                                try:
                                    final_obj.Shape.exportStep(output_path)
                                    if Path(output_path).exists():
                                        size = Path(output_path).stat().st_size
                                        logger.info(f"通过对象导出STEP成功: {output_path} ({size} bytes)")
                                        result["step_path"] = output_path
                                except Exception as e2:
                                    logger.warning(f"通过对象导出也失败: {e2}")
                    else:
                        logger.warning("没有找到形状对象，仅保存FCStd")
                        
                except Exception as e:
                    logger.error(f"保存文件出错: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            return result

        except Exception as e:
            logger.error(f"执行AI脚本失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def run_script_from_file(self, script_file: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        从文件运行脚本

        ??:
            script_file: .py脚本文件路径
            output_path: 可选的STEP输出路径

        ??:
            执行结果
        """
        try:
            with open(script_file, 'r', encoding='utf-8') as f:
                script_content = f.read()
            return self.run_script(script_content, output_path)
        except Exception as e:
            logger.error(f"读取脚本文件失败: {e}")
            return {"success": False, "error": str(e)}
