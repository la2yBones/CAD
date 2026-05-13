#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCAD建模指令生成器
通过大模型分析工程图纸并生成FreeCAD兼容的建模指令
"""
import json
import math
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
            max_tokens = self.config.get("max_tokens", 8000)
            use_thinking = self.config.get("thinking", True)

            if use_thinking:
                max_tokens = max(max_tokens, 16000)

            extra_body = None
            if use_thinking:
                extra_body = {"thinking": {"type": "enabled", "reasoning_effort": self.config.get("reasoning_effort", "max")}}

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

你必须严格按照JSON格式输出，直接返回一个JSON对象，不要包含任何markdown标记或额外文本。
JSON必须包含以下字段：
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
                max_tokens=max_tokens,
                extra_body=extra_body
            )

            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            message = choice.message
            content = message.content
            content_length = len(content) if content else 0
            logger.info(
                f"AI响应已返回: finish_reason={finish_reason}, content长度={content_length}"
            )
            if not content:
                reasoning = getattr(message, 'reasoning_content', None)
                if reasoning:
                    logger.warning(
                        "AI正文为空，尝试从 reasoning_content 中提取建模JSON；"
                        f"reasoning长度={len(reasoning)}"
                    )
                    content = reasoning
                else:
                    raise ValueError("AI响应正文为空，且没有 reasoning_content 可解析")

            result = self._extract_json(content)
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
        entities = geometry_data.get("entities", [])
        contours = self._group_entities_into_contours(entities)

        script_lines = [
            "import FreeCAD as App",
            "import Part",
            "",
            "doc = App.newDocument('GeneratedModel')",
            "",
            f"extrude_height = {extrude_height}",
            "",
        ]

        for ci, contour in enumerate(contours):
            edges = []
            for entity in contour:
                etype = entity.get("type")
                if etype == "LINE":
                    x1, y1 = entity["start"][0], entity["start"][1]
                    x2, y2 = entity["end"][0], entity["end"][1]
                    edges.append(
                        f"Part.LineSegment(App.Vector({x1},{y1},0), App.Vector({x2},{y2},0)).toShape()"
                    )
                elif etype == "CIRCLE":
                    cx, cy = entity["center"][0], entity["center"][1]
                    r = entity["radius"]
                    edges.append(
                        f"Part.Circle(App.Vector({cx},{cy},0), App.Vector(0,0,1), {r}).toShape()"
                    )
                elif etype == "ARC":
                    cx, cy = entity["center"][0], entity["center"][1]
                    r = entity["radius"]
                    sa = entity.get("start_angle", 0)
                    ea = entity.get("end_angle", 0)
                    edges.append(
                        f"Part.ArcOfCircle("
                        f"Part.Circle(App.Vector({cx},{cy},0), App.Vector(0,0,1), {r}), "
                        f"{sa}, {ea}).toShape()"
                    )

            if not edges:
                continue

            script_lines.append(f"# 轮廓 {ci+1}")
            script_lines.append(f"edges_{ci} = [{', '.join(edges)}]")
            script_lines.append(f"wire_{ci} = Part.Wire(edges_{ci})")
            script_lines.append(f"if wire_{ci}.isClosed():")
            script_lines.append(f"    face_{ci} = Part.Face(wire_{ci})")
            script_lines.append(f"    solid_{ci} = face_{ci}.extrude(App.Vector(0, 0, extrude_height))")
            script_lines.append(f"    Part.show(solid_{ci})")
            script_lines.append(f"else:")
            script_lines.append(f"    print('警告: 轮廓 {ci+1} 未闭合, 跳过拉伸')")
            script_lines.append("")

        script_lines.extend([
            "doc.recompute()",
            "",
            "doc.saveAs('model.FCStd')",
            "print('建模完成')",
            f"print('BRIDGE_FEATURE_COUNT:' + str(len(doc.Objects)))",
        ])

        return "\n".join(script_lines)

    @staticmethod
    def _group_entities_into_contours(entities: List[Dict]) -> List[List[Dict]]:
        TOL = 1e-3

        processed = set()
        contours = []

        def get_endpoints(e):
            t = e.get("type")
            if t == "LINE":
                s = tuple(e.get("start", [0, 0]))
                e_pt = tuple(e.get("end", [0, 0]))
                return s, e_pt
            elif t == "ARC":
                cx, cy = e.get("center", [0, 0])
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
                          if e.get("type") in ("LINE", "CIRCLE", "ARC")]

        for i, entity in enumerate(model_entities):
            if i in processed:
                continue
            etype = entity.get("type")
            if etype == "CIRCLE":
                contours.append([entity])
                processed.add(i)
                continue

            start, end = get_endpoints(entity)
            if start is None:
                continue

            remaining = [(j, e) for j, e in enumerate(model_entities) if j != i and j not in processed]
            chain, final_pt = follow_chain(end, remaining)

            contour = [entity] + chain
            for j in range(len(model_entities)):
                for c in chain:
                    if c is model_entities[j]:
                        processed.add(j)

            if pts_close(final_pt, start):
                contours.append(contour)
            elif len(contour) >= 1:
                contours.append(contour)

            processed.add(i)

        logger.info(f"轮廓分组: {len(model_entities)} 个有效实体 -> {len(contours)} 个轮廓")
        return contours

    def _extract_json(self, content: str) -> Dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if len(lines) > 1 and lines[-1].strip() == "```":
                content = "\n".join(lines[1:-1])
            elif len(lines) > 1:
                content = "\n".join(lines[1:])
            else:
                content = content.strip("`").strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        import re
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法从响应中提取有效JSON。内容前200字符: {content[:200]}")

    def save_script(self, script_content: str, output_path: str) -> None:
        """保存生成的脚本到文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            logger.info(f"FreeCAD脚本已保存: {output_path}")
        except Exception as e:
            logger.error(f"保存脚本失败: {e}")
