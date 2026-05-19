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

from src.utils.llm_telemetry import default_llm_telemetry_store
from .modeling_constraints import DEFAULT_MODELING_CONSTRAINTS

logger = logging.getLogger(__name__)
MODELING_CONSTRAINTS_PROMPT = DEFAULT_MODELING_CONSTRAINTS.prompt_section()


class FreeCADInstructionGenerator:
    """
    FreeCAD建模指令生成器
    使用大模型分析工程图纸并生成完整的建模流程指令
    """

    MODELING_SYSTEM_PROMPT = """你是专业的 CAD/FreeCAD 建模专家。你的任务是分析输入的标准化工程图纸几何数据，并生成可直接运行的 FreeCAD Python 建模脚本。

【输入要求】
输入必须是结构化 JSON 对象，且至少满足以下任一条件：

1. 包含经解析的 DXF 结构数据：
   - entities: 数组，包含 LINE、CIRCLE、ARC、LWPOLYLINE、TEXT、MTEXT、DIMENSION、ELLIPSE、SPLINE、INSERT 等实体
   - units: 可选，图纸单位
   - version: 可选，DXF 版本

2. 包含工程视图和建模语义数据：
   - views: 数组，包含视图名称、bbox、entity_count 等
   - dimensions: 数组，包含尺寸名称、数值、类型
   - contours: 数组，包含轮廓点、闭合状态、用途
   - units: 可选，图纸单位

若输入缺失关键字段、格式错误、不是 JSON 对象，或只是非结构化自然语言描述，必须返回 INVALID_INPUT JSON，严禁基于模糊描述猜测建模。

【无效输入返回格式】
若输入无效，仍必须返回严格 JSON：

{
  "error_code": "INVALID_INPUT",
  "analysis_summary": "",
  "modeling_strategy": "",
  "freecad_script": "",
  "instructions": [],
  "key_dimensions": [],
  "warnings": ["说明输入无效的具体原因"]
}

【分析目标】
请识别：
1. 视图结构：single_view、two_view、three_view、assembly_drawing、section_view 或 unknown
2. 尺寸标注信息：线性尺寸、直径、半径、孔距、厚度、高度等
3. 零件形状特征：基础体、孔、槽、台阶、凸台、倒角/圆角风险等

【建模原则】
- 采用极简建模策略。
- 优先使用基础原语构造：盒体、圆柱、圆锥。
- 对复杂组合体，先创建基础原语，再分步融合或切割。
- 对二视图/三视图，先把各视图解释为同一零件的正交投影，再开始建模；不得把右视图或俯视图当成附加在主视图旁边的新实体。
- 主视图表达主要轮廓，右视图/左视图表达同一零件的正交投影外形；这些投影视图尺寸不得直接解释为“向右延伸的凸台长度”或未经裁决的深度。
- 只有在至少两个视图或明确尺寸共同支持时，才可新增凸台、槽、台阶等三维特征；单一视图里的线段不得直接推断成额外凸台或开槽。
- 主视图中出现同心圆时，必须结合侧视图隐藏线/尺寸判断其含义；不得默认把所有同心圆都切成贯通孔。若证据不足，应优先生成单一通孔并在 warnings 中说明可能存在沉孔或台阶孔。
- 单个步骤中连续 .fuse() 或 .cut() 不得超过 2 次；若需要更多布尔操作，必须拆分为多个中间变量和多个 try/except 步骤。
- 若需自定义截面，仅允许用直线或圆弧构造 Part.Wire，再通过 Part.Face 和 Shape.extrude() 生成实体；若需要轴对称圆弧面，可用 Part.ArcOfCircle 构造轮廓并通过 Shape.revolve() 绕轴线生成回转曲面或回转切除体。
- 使用 Part.LineSegment 或 Part.ArcOfCircle 构造线框时，传入 Part.Wire 的每一项必须是 Shape；应先调用 `.toShape()`，例如 `edge = Part.LineSegment(...).toShape()`。
- 中间变量若在后续步骤复用，必须在 try/except 外先给出默认值，避免前一步失败后后续引用未定义变量。
- 若轮廓点写成 `(x, y, 0)`，则轮廓位于 XY 平面，拉伸方向必须沿 Z 轴；若需要沿 Y 轴拉伸，则轮廓点必须写成 `(x, 0, z)`，确保拉伸方向垂直于轮廓平面。
- 对板件、法兰、底座这类正视图轮廓，默认优先在 XY 平面构造轮廓，再按深度沿 Z 轴拉伸，除非图纸语义明确要求其他坐标系。
- 若输入包含 semantic_policy.dimension_plan，key_dimensions 只能使用 allowed_dimensions 中已裁决的尺寸；allowed_dimensions 可能包含由标注尺寸链组合得到的派生值，例如 9+39=48。
- segment_dimensions 可作为建模构造步骤的分段尺寸；不得单独当成总长、深度、对边、对角、法兰直径或孔径。
- unresolved_dimensions 不得用于创建关键几何；如果缺少这些尺寸会影响建模，必须在 warnings 中说明并保守降级。
- `1x45°`、`2x45°` 等倒角标注表示外部尖角被削掉形成斜面；实现时只能去除外角材料，不得把它建成向实体内部凹陷的槽、坑、沉孔或内切缺口。
- 若 semantic_policy.dimension_plan.allowed_dimensions 或 part_semantics 中存在 chamfer，且语义里已经定位到外部边，不得因为“FreeCAD 基本 API 限制”直接跳过。必须至少尝试用白名单 API 建出可见斜面。
- 可接受的倒角实现方式：对圆柱端部使用 `Part.makeCone(大半径, 小半径, 倒角轴向长度, FreeCAD.Vector(...), FreeCAD.Vector(...))` 构造 45° 截锥段；对六角头外端倒角，优先用较短的端部过渡体表达外轮廓收缩，必要时用 `Part.Wire`、`Part.Face`、`Shape.extrude` 和 `Shape.cut` 构造外角切除体。
- 对六角头螺栓这类“六角头 + 圆柱杆”零件，若存在 `1x45°`，应在头部外端或头部-杆过渡外角处生成可见倒角斜面；不能在 warnings 中写“倒角未实现”后继续输出成功模型。
- 若无法可靠定位倒角所在的外部边，必须在 warnings 中说明并跳过该倒角；不得为了表现倒角而在实体表面挖内陷特征。
- `R15`、`R2` 等是圆角/圆弧过渡，不是 45° 倒角。对于六角头螺栓主视图左侧头部的 R15 标注，应解释为绕螺栓轴线形成的圆弧面/承面；必须尝试以轴线为中心、半径 15mm 创建圆弧轮廓，并用 Shape.revolve() 或等价回转切除生成该曲面。
- 如果 part_semantics 或 semantic_policy.dimension_plan.allowed_dimensions 中存在 radius/R15，且语义已说明它属于螺栓头部圆弧面/承面，不得在 warnings 中写“R15未实现/圆角未实现”后输出成功模型。
- 不得使用高级拓扑修改、网格建模、草图约束或不在白名单内的 API。
- 每个建模步骤必须用 try/except 包裹。
- except 中不得静默忽略错误，必须将错误信息追加到 runtime_warnings 列表。
- 脚本末尾必须打印 runtime_warnings，便于调试。
- 主体建模必须优先完成并保存；孔、倒角、圆角、槽、螺纹、局部切除等细节特征应逐项尝试，局部失败时写入 skipped_features，不得让细节失败拖垮已经可靠生成的主体模型。
- 脚本中应维护 completed_features、skipped_features 和 partial_completion_reason；若 skipped_features 非空，脚本末尾必须打印一行 `PARTIAL_MODELING_RESULT:` 加 JSON 字符串，包含 completed_features、skipped_features、partial_completion_reason。

{MODELING_CONSTRAINTS_PROMPT}

【FreeCAD 脚本要求】
freecad_script 必须：
- 是严格合法的 Python 代码字符串。
- 包含必要导入：import FreeCAD, import Part。
- 创建文档：doc = FreeCAD.newDocument("GeneratedModel")。
- 使用清晰变量名。
- 缩进、括号、字符串引号必须正确。
- 每一步建模逻辑必须 try/except 包裹。
- 至少尝试生成一个 final_shape。
- 若 final_shape 存在，应执行 Part.show(final_shape, "GeneratedModel")。
- 脚本末尾必须执行 doc.recompute()。
- 如提供输出路径变量 output_path，可尝试 doc.saveAs(output_path)；否则不强制保存。
- 不得依赖不存在的外部文件。
- 不得删除、移动或覆盖输入文件。

【输出要求】
必须只输出一个 JSON 对象，不要输出 Markdown，不要解释 JSON 外的任何内容。

JSON 必须包含以下字段：

{
  "analysis_summary": "字符串，简述图纸特征",
  "modeling_strategy": "字符串，说明采用的几何构建方法",
  "freecad_script": "字符串，合法 Python FreeCAD 脚本",
  "instructions": ["按顺序列出建模步骤"],
  "key_dimensions": [
    {"name": "尺寸名称", "value": 数值}
  ],
  "completed_features": [{"name": "已完成特征", "kind": "base|detail"}],
  "skipped_features": [{"name": "跳过细节", "kind": "hole|chamfer|fillet|slot|thread|cut|other", "reason": "跳过原因", "risk": "风险说明"}],
  "partial_completion_reason": "若存在跳过细节，说明为什么主体模型仍可作为部分建模成果；否则为空字符串",
  "warnings": ["潜在风险、假设或无法确认的信息"]
}

【输出质量要求】
- 如果尺寸缺失，不得编造精确数值；应使用合理默认值并在 warnings 中说明。
- 如果轮廓不闭合，不得强行生成面；应跳过该轮廓并记录 warning。
- 如果检测到二视图或三视图，但无法可靠重建三维结构，应在 warnings 中明确说明，并生成保守脚本或空脚本。
- 主体外形、主要体量、方向或关键尺寸来源不确定时，不得伪装成部分完成；应输出空脚本或保守失败说明。只有主体可靠且可导出时，才允许把细节缺失记录为 skipped_features。
- 不得输出完整思维链，只输出简短分析摘要和建模策略。"""

    def __init__(self, api_key: str, config: Optional[Dict] = None):
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://api.deepseek.com")
        )
        self.model = self.config.get("model", "deepseek-v4-pro")
        self.telemetry_store = default_llm_telemetry_store(self.config)
        self.constraints = DEFAULT_MODELING_CONSTRAINTS

        max_prompt_tokens = self.config.get("max_prompt_tokens", 12000)
        self.MAX_PROMPT_CHARS = max_prompt_tokens * 4

    def generate(self, geometry_data: Dict[str, Any],
                 view_analysis: Optional[Dict] = None,
                 dimension_data: Optional[Dict] = None,
                 extrude_height: float = 10.0,
                 reconstruction_context: Optional[Dict[str, Any]] = None,
                 part_semantics: Optional[Dict[str, Any]] = None,
                 file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        生成FreeCAD建模指令

        ??:
            geometry_data: 几何数据
            view_analysis: 视图分析结果（可选）
            dimension_data: 尺寸标注结果（可选）
            extrude_height: 默认拉伸高度

        ??:
            包含建模指令的结果字典
        """
        logger.info("开始生成FreeCAD建模指令")

        # 构建提示词
        prompt = self._build_prompt(
            geometry_data,
            view_analysis,
            dimension_data,
            extrude_height,
            reconstruction_context=reconstruction_context,
            part_semantics=part_semantics,
        )

        try:
            max_tokens = self.config.get("max_tokens", 8000)
            use_thinking = self.config.get("thinking", True)

            if use_thinking:
                max_tokens = max(max_tokens, 16000)

            extra_body = None
            if use_thinking:
                extra_body = {"thinking": {"type": "enabled", "reasoning_effort": self.config.get("reasoning_effort", "max")}}

            response = self._create_chat_completion(
                file_path=file_path,
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.MODELING_SYSTEM_PROMPT
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
            retry_reason = self.constraints.retry_reason(result, reconstruction_context, part_semantics)
            if retry_reason:
                logger.warning(f"建模指令跳过了已裁决特征，使用强化约束重试: {retry_reason}")
                response = self._create_chat_completion(
                    file_path=file_path,
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": self.MODELING_SYSTEM_PROMPT
                        },
                        {"role": "user", "content": self.constraints.retry_prompt(prompt, retry_reason)}
                    ],
                    max_tokens=max_tokens,
                    extra_body=extra_body
                )
                retry_content = response.choices[0].message.content or ""
                if not retry_content:
                    retry_reasoning = getattr(response.choices[0].message, 'reasoning_content', None)
                    retry_content = retry_reasoning or ""
                if retry_content:
                    result = self._extract_json(retry_content)
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
                "completed_features": [],
                "skipped_features": [],
                "partial_completion_reason": "",
                "warnings": ["使用降级建模方法"]
            }

    def _create_chat_completion(self, file_path: Optional[str] = None, **request_payload):
        call_span = self.telemetry_store.start_call(
            stage="modeling_generation",
            model=str(request_payload.get("model") or self.model),
            provider="deepseek",
            request=request_payload,
            file_path=file_path,
        )
        try:
            response = self.client.chat.completions.create(**request_payload)
            call_span.finish(response=response)
            return response
        except Exception as call_error:
            call_span.finish(error=call_error)
            raise

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
                      extrude_height: float,
                      reconstruction_context: Optional[Dict[str, Any]] = None,
                      part_semantics: Optional[Dict[str, Any]] = None) -> str:
        """构建提示词"""
        entities = geometry_data.get("entities", [])

        entities_summary = self._summarize_entities(entities)

        prompt_parts = [
            "请分析以下工程图纸数据并生成FreeCAD建模脚本：\n",
            "=== 几何实体数据 ===\n",
            entities_summary,
        ]

        modeling_context = reconstruction_context or self._build_modeling_context(
            geometry_data, view_analysis, dimension_data
        )
        prompt_parts.append("\n=== 建模上下文 ===\n")
        prompt_parts.append(json.dumps(modeling_context, ensure_ascii=False, indent=2))
        user_hint_section = self._build_user_modeling_hint_section(
            modeling_context,
            part_semantics,
        )
        if user_hint_section:
            prompt_parts.append(user_hint_section)
        if part_semantics:
            prompt_parts.append("\n=== 零件语义 ===\n")
            prompt_parts.append(json.dumps(part_semantics, ensure_ascii=False, indent=2))

        prompt = "\n".join(prompt_parts)

        if self.MAX_PROMPT_CHARS and len(prompt) > self.MAX_PROMPT_CHARS:
            logger.warning(
                f"Prompt过长 ({len(prompt)}字符, ~{self._estimate_tokens(prompt)} tokens), 进行截断"
            )
            prompt = prompt[:self.MAX_PROMPT_CHARS] + "\n... (内容已截断以适配token限制)"

        estimated_tokens = self._estimate_tokens(prompt)
        logger.info(f"Prompt大小: {len(prompt)}字符, ~{estimated_tokens} tokens")
        return prompt

    def _build_user_modeling_hint_section(
        self,
        modeling_context: Dict[str, Any],
        part_semantics: Optional[Dict[str, Any]],
    ) -> str:
        semantic_policy = modeling_context.get("semantic_policy", {}) or {}
        hint = (
            modeling_context.get("user_modeling_hint")
            or semantic_policy.get("user_modeling_hint")
            or (part_semantics or {}).get("user_modeling_hint")
            or ""
        )
        hint = str(hint).strip()
        if not hint:
            return ""

        conflict_policy = (
            modeling_context.get("user_modeling_hint_policy")
            or semantic_policy.get("user_modeling_hint_policy")
            or (part_semantics or {}).get("user_modeling_hint_policy")
            or "drawing_facts_override_user_hint"
        )
        return "\n".join([
            "\n=== 用户补充建模提示使用规则 ===\n",
            f"用户补充提示: {hint}",
            f"冲突策略: {conflict_policy}",
            (
                "必须遵守：用户补充提示只用于解释建模意图、细节优先级和可接受的跳过范围；"
                "当它与图纸解析事实、已裁决关键尺寸来源、主体方向或主体外形冲突时，"
                "必须以图纸事实和 semantic_policy.dimension_plan 为准。"
            ),
            (
                "如果补充提示要求跳过细节，可把对应细节写入 skipped_features；"
                "不得因此跳过已可靠裁决且影响主体外形或主要体量的特征。"
            ),
        ])

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

    def _build_modeling_context(
        self,
        geometry_data: Dict[str, Any],
        view_analysis: Optional[Dict[str, Any]],
        dimension_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        views = (view_analysis or {}).get("views", []) or []
        dimensions = (dimension_data or {}).get("dimensions", []) or []
        local_relationships = geometry_data.get("_local_relationships") or {}

        return {
            "drawing_type": (view_analysis or {}).get("drawing_type"),
            "view_reason_summary": (view_analysis or {}).get("reason_summary", ""),
            "views": [self._compact_view_for_modeling(view) for view in views],
            "dimensions": [self._compact_dimension_for_modeling(dim) for dim in dimensions],
            "local_relationships": {
                "summary": local_relationships.get("summary"),
                "entity_pairs": local_relationships.get("entity_pairs", []),
            },
        }

    def _compact_view_for_modeling(self, view: Dict[str, Any]) -> Dict[str, Any]:
        entities = view.get("entities", []) or []
        return {
            "name": view.get("name"),
            "type": view.get("type"),
            "bbox": view.get("bbox"),
            "centroid": view.get("centroid"),
            "entity_count": view.get("entity_count", len(entities)),
            "layers": view.get("layers", []),
            "type_count": self._count_entity_types(entities),
            "entities": [self._compact_entity_for_modeling(entity) for entity in entities],
        }

    @staticmethod
    def _count_entity_types(entities: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for entity in entities:
            entity_type = str(entity.get("type", "unknown"))
            result[entity_type] = result.get(entity_type, 0) + 1
        return result

    @staticmethod
    def _compact_entity_for_modeling(entity: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "type",
            "layer",
            "start",
            "end",
            "center",
            "radius",
            "vertices",
            "closed",
            "start_angle",
            "end_angle",
        )
        return {key: entity.get(key) for key in keep_keys if key in entity}

    @staticmethod
    def _compact_dimension_for_modeling(dimension: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = ("text", "value", "type", "position")
        return {key: dimension.get(key) for key in keep_keys if key in dimension}

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


FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT = (
    FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT.replace(
        "{MODELING_CONSTRAINTS_PROMPT}",
        MODELING_CONSTRAINTS_PROMPT,
    )
)
