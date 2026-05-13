"""
3D模型生成器

基于解析后的几何数据与智能分析结果，调用 FreeCAD 执行建模并管理输出产物。
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.config import load_config
from ..utils.result import Result
from .freecad_bridge import FreeCADBridge
from .ai_script_runner import AIScriptRunner


class ModelGenerator:
    """
    CAD-3D 模型生成器。

    支持两种模式：
    - 基础模式：基于图层规则自动拉伸
    - 智能模式：AI 驱动的视图分析 + 尺寸提取 + 建模脚本生成

    输出格式：STEP、STL、FCStd
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or load_config()
        self._bridge = FreeCADBridge(self._config)
        self._runner = AIScriptRunner(self._config)

    def generate_basic_model(
        self,
        geometry_data: Dict[str, Any],
        extrude_height: float = 10.0,
        output_dir: Optional[str] = None,
    ) -> Result[Dict[str, Any]]:
        """
        基础模式：基于图层规则生成拉伸模型。

        Args:
            geometry_data: CAD 解析后的几何数据
            extrude_height: 默认拉伸高度（毫米）
            output_dir: 输出目录

        Returns:
            Result[Dict]: Ok 时包含 model_path/output_dir 等信息
        """
        start_time = time.time()

        layers = geometry_data.get("layers", [])
        entities = geometry_data.get("entities", [])

        if not entities:
            return Result.Err("几何数据中无实体，无法生成基础模型。")

        script = self._build_base_script(layers, entities, extrude_height)

        exec_result = self._bridge.execute_script(script)
        if exec_result.is_err():
            return Result.Err(f"基础模型 FreeCAD 执行失败: {exec_result.error}")

        output = self._resolve_output_dir(geometry_data, output_dir)
        elapsed = round(time.time() - start_time, 2)

        return Result.Ok({
            "success": True,
            "model_path": str(output),
            "output_dir": str(output),
            "mode": "basic",
            "entity_count": len(entities),
            "layer_count": len(layers),
            "extrude_height": extrude_height,
            "generation_time_seconds": elapsed,
            "freecad_output": exec_result.value,
        })

    def generate_intelligent_model(
        self,
        geometry_data: Dict[str, Any],
        analysis_result: Dict[str, Any],
        output_dir: Optional[str] = None,
    ) -> Result[Dict[str, Any]]:
        """
        智能模式：基于 AI 分析结果生成模型。

        Args:
            geometry_data: CAD 解析后的几何数据
            analysis_result: 智能分析流水线的输出
            output_dir: 输出目录

        Returns:
            Result[Dict]: Ok 时包含 model_path/output_dir 等信息
        """
        start_time = time.time()

        script = analysis_result.get("freecad_script", "")
        if not script:
            return Result.Err("智能分析结果中未包含 FreeCAD 脚本，无法生成模型。")

        run_result = self._runner.run_script(script)
        if run_result.is_err():
            return Result.Err(f"智能模型执行失败: {run_result.error}")

        output = self._resolve_output_dir(geometry_data, output_dir)
        elapsed = round(time.time() - start_time, 2)

        return Result.Ok({
            "success": True,
            "model_path": str(output),
            "output_dir": str(output),
            "mode": "intelligent",
            "generation_time_seconds": elapsed,
            "script_result": run_result.value,
            "analysis": analysis_result,
        })

    def _build_base_script(
        self,
        layers: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        extrude_height: float,
    ) -> str:
        """构建基础模式 FreeCAD 脚本（基于图层规则拉伸）。"""
        lines = [
            "import FreeCAD as App",
            "import Part",
            "import Draft",
            "",
            "doc = App.newDocument('CAD_Basic_Model')",
            "",
        ]

        layer_map: Dict[str, List[Dict[str, Any]]] = {}
        for e in entities:
            layer_name = e.get("layer", "0")
            layer_map.setdefault(layer_name, []).append(e)

        for layer_name, layer_entities in layer_map.items():
            lines.append(f"# ===== 图层: {layer_name} ({len(layer_entities)} 个实体) =====")
            for entity in layer_entities:
                script_fragment = self._entity_to_fragment(entity, extrude_height)
                lines.append(script_fragment)
            lines.append("")

        lines.extend([
            "doc.recompute()",
            "# 基础模型生成完毕",
        ])

        return "\n".join(lines)

    def _entity_to_fragment(self, entity: Dict[str, Any], extrude_height: float) -> str:
        """将单个实体转换为 FreeCAD 脚本片段。"""
        entity_type = entity.get("type", "")

        if entity_type == "LINE":
            sx, sy = entity.get("start", (0, 0))
            ex, ey = entity.get("end", (0, 0))
            return (
                f"Draft.make_line("
                f"App.Vector({sx}, {sy}, 0), "
                f"App.Vector({ex}, {ey}, 0))"
            )
        elif entity_type == "CIRCLE":
            cx, cy = entity.get("center", (0, 0))
            r = entity.get("radius", 10)
            return (
                f"Draft.make_circle({r}, "
                f"placement=App.Placement(App.Vector({cx}, {cy}, 0), App.Rotation()))"
            )
        else:
            return f"# 未处理类型: {entity_type}"

    def _resolve_output_dir(
        self,
        geometry_data: Dict[str, Any],
        output_dir: Optional[str] = None,
    ) -> Path:
        """解析输出目录。"""
        if output_dir:
            p = Path(output_dir)
        else:
            gen_config = self._config.get("generation", {})
            p = Path(gen_config.get("output_dir", "output"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_bridge(self) -> FreeCADBridge:
        """获取 FreeCAD 桥接器实例。"""
        return self._bridge

    def get_runner(self) -> AIScriptRunner:
        """获取 AI 脚本运行器实例。"""
        return self._runner
