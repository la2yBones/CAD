#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCAD建模指令生成器
通过大模型分析工程图纸并生成FreeCAD兼容的建模指令
"""
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from openai import OpenAI

logger = logging.getLogger(__name__)


class FreeCADInstructionGenerator:
    """
    FreeCAD建模指令生成器
    使用大模型分析工程图纸并生成完整的建模流程指令
    """

    def __init__(self, api_key: str, config: Optional[Dict] = None):
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://api.deepseek.com")
        )
        self.model = self.config.get("model", "deepseek-v4-pro")

        max_prompt_tokens = self.config.get("max_prompt_tokens", 12000)
        self.MAX_PROMPT_CHARS = max_prompt_tokens * 4

    def generate(self, geometry_data: Dict[str, Any],
                 view_analysis: Optional[Dict] = None,
                 dimension_data: Optional[Dict] = None,
                 extrude_height: float = 10.0) -> Dict[str, Any]:
        """
        生成FreeCAD建模指令

        Args:
            geometry_data: 几何数据
            view_analysis: 视图分析结果（可选）
            dimension_data: 尺寸标注结果（可选）
            extrude_height: 默认拉伸高度

        Returns:
            包含建模指令的结果字典
        """
        logger.info("开始生成FreeCAD建模指令")

        # 构建提示词
        prompt = self._build_prompt(geometry_data, view_analysis, dimension_data, extrude_height)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """你是专业的CAD/FreeCAD建模专家。请分析输入的工程图纸几何数据，识别：
1. 视图结构（二视图、三视图）
2. 尺寸标注信息
3. 零件形状特征
然后生成可执行的FreeCAD Python建模脚本。

输出格式要求：JSON格式，包含以下字段：
- analysis_summary: 图纸分析总结
- modeling_strategy: 建模策略说明
- freecad_script: 完整的FreeCAD Python脚本（字符串形式）
- instructions: 建模步骤说明列表
- key_dimensions: 关键尺寸列表
- warnings: 警告或注意事项列表
                        """
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.config.get("max_tokens", 8000),
                extra_body={"thinking": {"type": "enabled", "reasoning_effort": self.config.get("reasoning_effort", "max")}} if self.config.get("thinking", True) else None,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            logger.info("建模指令生成成功")
            return result

        except Exception as e:
            logger.error(f"建模指令生成失败: {e}")
            return {
                "analysis_summary": f"分析失败: {str(e)}",
                "modeling_strategy": "使用基础建模方法",
                "freecad_script": self._generate_fallback_script(geometry_data, extrude_height),
                "instructions": ["创建草图", "拉伸实体"],
                "key_dimensions": [],
                "warnings": ["使用降级建模方法"]
            }

    MAX_ENTITIES_IN_PROMPT = 20
    MAX_ENTITY_JSON_CHARS = 500

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _truncate_entity_json(self, entity: Dict) -> str:
        raw = json.dumps(entity, ensure_ascii=False)
        if len(raw) > self.MAX_ENTITY_JSON_CHARS:
            raw = raw[:self.MAX_ENTITY_JSON_CHARS] + "..."
        return raw

    def _build_prompt(self, geometry_data: Dict[str, Any],
                      view_analysis: Optional[Dict],
                      dimension_data: Optional[Dict],
                      extrude_height: float) -> str:
        """构建提示词"""
        entities = geometry_data.get("entities", [])

        entities_summary = self._summarize_entities(entities)

        prompt_parts = [
            "请分析以下工程图纸数据并生成FreeCAD建模脚本：\n",
            "=== 几何实体数据 ===\n",
            entities_summary,
            f"\n默认拉伸高度: {extrude_height} mm\n"
        ]

        if view_analysis:
            view_json = json.dumps(view_analysis, ensure_ascii=False, indent=2)
            if len(view_json) > 3000:
                view_json = view_json[:3000] + "\n... (视图分析内容已截断)"
            prompt_parts.append("\n=== 视图分析 ===\n")
            prompt_parts.append(view_json)

        if dimension_data:
            dim_json = json.dumps(dimension_data, ensure_ascii=False, indent=2)
            if len(dim_json) > 3000:
                dim_json = dim_json[:3000] + "\n... (尺寸标注内容已截断)"
            prompt_parts.append("\n=== 尺寸标注 ===\n")
            prompt_parts.append(dim_json)

        prompt = "\n".join(prompt_parts)

        if len(prompt) > self.MAX_PROMPT_CHARS:
            logger.warning(
                f"Prompt过长 ({len(prompt)}字符, ~{self._estimate_tokens(prompt)} tokens), 进行截断"
            )
            prompt = prompt[:self.MAX_PROMPT_CHARS] + "\n... (内容已截断以适配token限制)"

        estimated_tokens = self._estimate_tokens(prompt)
        logger.info(f"Prompt大小: {len(prompt)}字符, ~{estimated_tokens} tokens")
        return prompt

    def _summarize_entities(self, entities: List[Dict]) -> str:
        """总结实体信息"""
        type_count = {}
        for entity in entities:
            t = entity.get("type", "unknown")
            type_count[t] = type_count.get(t, 0) + 1

        summary = f"总计 {len(entities)} 个实体\n"
        summary += f"类型分布: {json.dumps(type_count, ensure_ascii=False)}\n\n"

        for i, entity in enumerate(entities[:self.MAX_ENTITIES_IN_PROMPT]):
            summary += f"[{i}] {self._truncate_entity_json(entity)}\n"

        if len(entities) > self.MAX_ENTITIES_IN_PROMPT:
            summary += f"... 还有 {len(entities) - self.MAX_ENTITIES_IN_PROMPT} 个实体\n"

        return summary

    def _generate_fallback_script(self, geometry_data: Dict[str, Any],
                                  extrude_height: float) -> str:
        """生成降级版本的脚本（当AI分析失败时使用）"""
        entities = geometry_data.get("entities", [])

        script_lines = [
            "import FreeCAD as App",
            "import Part",
            "import Sketcher",
            "",
            "doc = App.newDocument('GeneratedModel')",
            "",
            "# 创建草图",
            "sketch = doc.addObject('Sketcher::SketchObject', 'BaseSketch')",
            "sketch.Placement = App.Placement(App.Vector(0,0,0), App.Rotation(0,0,0,1))",
            ""
        ]

        line_count = 0
        circle_count = 0

        for entity in entities:
            etype = entity.get("type")
            if etype == "LWPOLYLINE" and entity.get("closed", False):
                # 添加多段线
                vertices = entity.get("vertices", [])
                if len(vertices) >= 3:
                    script_lines.append(f"# 添加闭合轮廓")
                    for i in range(len(vertices)):
                        x1, y1 = vertices[i][0], vertices[i][1]
                        x2, y2 = vertices[(i+1)%len(vertices)][0], vertices[(i+1)%len(vertices)][1]
                        script_lines.append(
                            f"sketch.addGeometry(Part.LineSegment("
                            f"App.Vector({x1}, {y1}, 0), "
                            f"App.Vector({x2}, {y2}, 0)), False)"
                        )
            elif etype == "LINE":
                x1, y1 = entity["start"][0], entity["start"][1]
                x2, y2 = entity["end"][0], entity["end"][1]
                script_lines.append(
                    f"sketch.addGeometry(Part.LineSegment("
                    f"App.Vector({x1}, {y1}, 0), "
                    f"App.Vector({x2}, {y2}, 0)), False)"
                )
                line_count += 1
            elif etype == "CIRCLE":
                cx, cy = entity["center"][0], entity["center"][1]
                r = entity["radius"]
                script_lines.append(
                    f"sketch.addGeometry(Part.Circle("
                    f"App.Vector({cx}, {cy}, 0), "
                    f"App.Vector(0,0,1), {r}), False)"
                )
                circle_count += 1

        script_lines.extend([
            "",
            "doc.recompute()",
            "",
            "# 拉伸",
            f"pad = doc.addObject('PartDesign::Pad', 'Pad')",
            "pad.Profile = sketch",
            f"pad.Length = {extrude_height}",
            "doc.recompute()",
            "",
            f"# 保存",
            "doc.saveAs('model.FCStd')",
            "print('建模完成')"
        ])

        return "\n".join(script_lines)

    def save_script(self, script_content: str, output_path: str) -> None:
        """保存生成的脚本到文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            logger.info(f"FreeCAD脚本已保存: {output_path}")
        except Exception as e:
            logger.error(f"保存脚本失败: {e}")
