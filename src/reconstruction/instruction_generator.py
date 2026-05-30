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

from src.utils.deepseek_options import (
    STAGE_MODELING_GENERATION,
    apply_stage_request_options,
    client_timeout,
    stage_thinking_enabled,
)
from src.utils.llm_telemetry import default_llm_telemetry_store
from src.utils.stage_self_correction import SelfCorrectionRequest
from .modeling_constraints import DEFAULT_MODELING_CONSTRAINTS
from .modeling_instruction_postprocessor import ModelingInstructionPostprocessor
from .modeling_task import ModelingTaskBuilder

logger = logging.getLogger(__name__)
MODELING_CONSTRAINTS_PROMPT = DEFAULT_MODELING_CONSTRAINTS.prompt_section()


class FreeCADInstructionGenerator:
    """
    FreeCAD建模指令生成器
    使用大模型分析工程图纸并生成完整的建模流程指令
    """

    MODELING_SYSTEM_PROMPT = """你是专业的 CAD/FreeCAD 建模专家。你的任务是分析输入的建模任务载荷，并生成可直接运行的 FreeCAD Python 建模脚本。

【输入要求】
输入必须是结构化 JSON 对象，顶层必须包含 object、modeling_operations、dimensions、constraints。
modeling_operations 是已裁决的建模操作序列，每项包含 operation 类型、description 和 dimensions 参数；你必须严格按照 modeling_operations 中的操作序列和尺寸参数生成 FreeCAD 脚本。
features 字段是原始语义数据，仅作为参考上下文，不得直接用于推断建模步骤或尺寸。
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
- `outer_diameter`、`外径`、`外圆`、`revolve_profile` 中的直径表示主体外轮廓尺寸，不是孔径；只有 modeling_operations 中明确为 `subtract_feature` 且语义为通孔/盲孔/沉孔的 diameter 才能生成切除圆柱。例如外径64、内径/孔径32的回转件，只能切除32孔，不得再切除64外径。
- 单个步骤中连续 .fuse() 或 .cut() 不得超过 2 次；若需要更多布尔操作，必须拆分为多个中间变量和多个 try/except 步骤。
- 若需自定义截面，仅允许用直线或圆弧构造 Part.Wire，再通过 Part.Face 和 Shape.extrude() 生成实体；若需要轴对称圆弧面，可用 Part.ArcOfCircle 构造轮廓并通过 Shape.revolve() 绕轴线生成回转曲面或回转切除体。
- 使用 Part.LineSegment 或 Part.ArcOfCircle 构造线框时，传入 Part.Wire 的每一项必须是 Shape 或 Edge/Shape。为兼容不同 FreeCAD 版本，脚本中必须先定义 `as_edge(obj): return obj.toShape() if hasattr(obj, "toShape") else obj`，然后写 `edge = as_edge(Part.LineSegment(...))` 或 `edge = as_edge(Part.ArcOfCircle(...))`；不得直接链式写 `.toShape()` 后假设所有版本返回同一类型。
- `Part.ArcOfCircle` 只能写 3 个位置参数：`Part.ArcOfCircle(Part.Circle(center, FreeCAD.Vector(0,0,1), radius), start_angle, end_angle).toShape()` 或 `Part.ArcOfCircle(p1, p2, p3).toShape()`；不得写成 `Part.ArcOfCircle(center, radius, start_angle, end_angle)`。
- 中间变量若在后续步骤复用，必须在 try/except 外先给出默认值，避免前一步失败后后续引用未定义变量。
- 若轮廓点写成 `(x, y, 0)`，则轮廓位于 XY 平面，拉伸方向必须沿 Z 轴；若需要沿 Y 轴拉伸，则轮廓点必须写成 `(x, 0, z)`，确保拉伸方向垂直于轮廓平面。
- 对板件、法兰、底座这类正视图轮廓，默认优先在 XY 平面构造轮廓，再按深度沿 Z 轴拉伸，除非图纸语义明确要求其他坐标系。
- 若 dimensions.modeling_dimensions 存在，它是唯一的已裁决建模尺寸池，每项包含 role、value 和 source；dimensions.semantic_adjudication 中已不含 dimension_roles 和 derived_dimensions（已合并到 modeling_dimensions）。semantic_adjudication 仅保留 feature_roles、view_roles 等非尺寸参考。
- dimensions.modeling_dimensions 中每项都必须保留原始 evidence_ids/source，不得新增未裁决尺寸值。
- 只有 dimensions.modeling_dimensions 缺失时，才允许把 dimensions.allowed_dimensions / construction_dimensions / unresolved_dimensions 当作兼容兜底。
- allowed_dimensions 中 binding_status=adjudicated 的项可作为已裁决的主体关键尺寸；construction_dimensions 只可作为局部分段、局部特征或重复特征尺寸，写入 key_dimensions 时必须保留具体构造语义，不得单独当成总长、深度、对边、对角、法兰直径或孔径。
- candidate_dimensions 来自本地兼容候选规则，仅可作为语义参考和风险提示；其中 binding_status=candidate 的尺寸未被 semantic_adjudication 或用户澄清确认前，不得单独当成最终建模权限。
- unresolved_dimensions 不得用于创建关键几何；如果缺少这些尺寸会影响建模，必须在 warnings 中说明并保守降级。
- features 中不再包含 key_dimensions；所有可用于建模的尺寸只能来自 dimensions 节。不得从 recovery_hints.uncertainties、recovery_hints.warnings 或自然语言摘要中提取新尺寸或新特征。
- recovery_hints 只用于说明恢复背景、风险和用户偏好，不是建模许可；其中的 warnings/uncertainties 不得被当作图纸事实、不得补充 dimensions 中不存在的尺寸。
- features.subtractive、features.planar_modeling.cut_features 或特征 evidence 中若包含来自 CIRCLE 实体的 center/radius/diameter/bbox，这些字段是可执行孔位几何证据；对板件、基板、法兰、底座等平面拉伸模型，应优先用这些圆生成贯穿孔切除。不得因为缺少孔距、定位尺寸或额外文本标注就跳过已经给出圆心和半径的孔。
- 若 CIRCLE 孔特征同时提供 center_relative_to_profile，且主体基体以外轮廓中心为原点建模，应优先使用该相对坐标作为 FreeCAD 孔圆柱中心；不要再把绝对 CAD 图纸坐标当作模型坐标直接使用。
- CIRCLE 孔位几何只能用于对应孔/切除的局部几何，不得写入 key_dimensions 伪装成主体关键标注尺寸；若孔位来自解析几何而非标注尺寸，应在 warnings 中说明来源。
- 点划线、中心线、构造线或隐藏线图层上的 CIRCLE 默认视为定位/节圆/辅助圆，不得直接切孔；只有语义中明确裁决为 actual through_hole/blind_hole/counterbore 时才可切除。
- `1x45°`、`2x45°` 等倒角标注表示外部尖角被削掉形成斜面；实现时只能去除外角材料，不得把它建成向实体内部凹陷的槽、坑、沉孔或内切缺口。
- 若 dimensions.modeling_dimensions 或 dimensions.allowed_dimensions 中存在 chamfer，且语义里已经定位到外部边，不得因为\u201cFreeCAD 基本 API 限制\u201d直接跳过。必须至少尝试用白名单 API 建出可见斜面。
- 可接受的倒角实现方式：对圆柱端部使用 `Part.makeCone(大半径, 小半径, 倒角轴向长度, FreeCAD.Vector(...), FreeCAD.Vector(...))` 构造 45° 截锥段；对六角头外端倒角，优先用较短的端部过渡体表达外轮廓收缩，必要时用 `Part.Wire`、`Part.Face`、`Shape.extrude` 和 `Shape.cut` 构造外角切除体。
- 对六角头螺栓这类“六角头 + 圆柱杆”零件，若存在 `1x45°`，应在头部外端或头部-杆过渡外角处生成可见倒角斜面；不能在 warnings 中写“倒角未实现”后继续输出成功模型。
- 若无法可靠定位倒角所在的外部边，必须在 warnings 中说明并跳过该倒角；不得为了表现倒角而在实体表面挖内陷特征。
- `R15`、`R2` 等是圆角/圆弧过渡，不是 45° 倒角。对于六角头螺栓主视图左侧头部的 R15 标注，应解释为绕螺栓轴线形成的圆弧面/承面；必须尝试以轴线为中心、半径 15mm 创建圆弧轮廓，并用 Shape.revolve() 或等价回转切除生成该曲面。
- 如果 dimensions.modeling_dimensions 或 dimensions.allowed_dimensions 中存在 radius/R15，且语义已说明它属于螺栓头部圆弧面/承面，不得在 warnings 中写"R15未实现/圆角未实现"后输出成功模型。
- 不得使用高级拓扑修改、网格建模、草图约束或不在白名单内的 API。
- 每个建模步骤必须用 try/except 包裹。
- except 中不得静默忽略错误，必须将错误信息追加到 runtime_warnings 列表。
- 脚本末尾必须打印 runtime_warnings，便于调试。
- 主体建模必须优先完成并保存；孔、倒角、圆角、槽、螺纹、局部切除等细节特征应逐项尝试，局部失败时写入 skipped_features，不得让细节失败拖垮已经可靠生成的主体模型。
- 脚本中应维护 completed_features、skipped_features 和 partial_completion_reason；若脚本使用 json.dumps 打印 `PARTIAL_MODELING_RESULT:` 元数据，必须显式 `import json`。

{MODELING_CONSTRAINTS_PROMPT}

【FreeCAD 脚本要求】
freecad_script 必须：
- 是严格合法的 Python 代码字符串。
- 包含必要导入：import FreeCAD, import Part；若使用 json.dumps 输出元数据，必须包含 import json。
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
- 如果主体厚度、拉伸深度、主体外形或关键建模尺寸缺失，不得编造默认值，也不得输出会生成无效实体的线框脚本；应输出空脚本或保守失败说明，并通过 warnings/skipped_features 明确需要用户补充。
- 只有局部细节尺寸缺失且主体模型已经可靠可导出时，才允许跳过该局部细节并写入 skipped_features。
- 如果轮廓不闭合，不得强行生成面；应跳过该轮廓并记录 warning。
- 如果检测到二视图或三视图，但无法可靠重建三维结构，应在 warnings 中明确说明，并生成保守脚本或空脚本。
- 主体外形、主要体量、方向或关键尺寸来源不确定时，不得伪装成部分完成；应输出空脚本或保守失败说明。只有主体可靠且可导出时，才允许把细节缺失记录为 skipped_features。
- 不得输出完整思维链，只输出简短分析摘要和建模策略。"""

    def __init__(self, api_key: str, config: Optional[Dict] = None):
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://api.deepseek.com"),
            timeout=client_timeout(self.config),
        )
        self.model = self.config.get("model", "deepseek-v4-pro")
        self.telemetry_store = default_llm_telemetry_store(self.config)
        self.constraints = DEFAULT_MODELING_CONSTRAINTS
        self.modeling_task_builder = ModelingTaskBuilder()
        self.postprocessor = ModelingInstructionPostprocessor()

        max_prompt_tokens = self.config.get("max_prompt_tokens", 12000)
        self.MAX_PROMPT_CHARS = max_prompt_tokens * 4

    def generate(self, geometry_data: Dict[str, Any],
                 view_analysis: Optional[Dict] = None,
                 dimension_data: Optional[Dict] = None,
                 extrude_height: float = 10.0,
                 reconstruction_context: Optional[Dict[str, Any]] = None,
                 part_semantics: Optional[Dict[str, Any]] = None,
                 modeling_task_payload: Optional[Dict[str, Any]] = None,
                 file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        生成FreeCAD建模指令

        参数:
            geometry_data: 几何数据
            view_analysis: 视图分析结果（可选）
            dimension_data: 尺寸标注结果（可选）
            extrude_height: 默认拉伸高度

        返回:
            包含建模指令的结果字典
        """
        logger.info("开始生成FreeCAD建模指令")

        if modeling_task_payload is None:
            builder = getattr(self, "modeling_task_builder", None) or ModelingTaskBuilder()
            modeling_task_payload = builder.build(
                part_semantics=part_semantics,
                reconstruction_context=reconstruction_context,
            )

        prompt = self._build_prompt(modeling_task_payload)

        try:
            use_thinking = stage_thinking_enabled(
                self.config,
                STAGE_MODELING_GENERATION,
                default=bool(self.config.get("modeling_json_thinking", False)),
            )

            request_payload = apply_stage_request_options(
                {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": self.MODELING_SYSTEM_PROMPT
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                },
                self.config,
                stage=STAGE_MODELING_GENERATION,
                default_thinking=bool(self.config.get("modeling_json_thinking", False)),
                default_effort="max",
                legacy_thinking_keys=("modeling_json_thinking",),
            )
            response = self._create_chat_completion(
                file_path=file_path,
                **request_payload,
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
            postprocessor = getattr(self, "postprocessor", None) or ModelingInstructionPostprocessor()
            result = postprocessor.normalize(
                result,
                reconstruction_context,
                modeling_task_payload=modeling_task_payload,
            )
            retry_reason = self.constraints.retry_reason(result, reconstruction_context, part_semantics)
            if retry_reason:
                logger.info(
                    "建模指令检测到已裁决特征被跳过，不再触发强化约束重试: %s",
                    retry_reason,
                )
            logger.info("建模指令生成成功")
            return result

        except ValueError as ve:
            logger.error(f"建模指令生成失败: {ve}")
            return {
                "analysis_summary": f"分析失败: {str(ve)}",
                "modeling_strategy": "使用基础建模方法",
                "freecad_script": self._generate_fallback_script(geometry_data, extrude_height),
                "instructions": ["创建草图", "拉伸实体"],
                "key_dimensions": [],
                "completed_features": [],
                "skipped_features": [],
                "partial_completion_reason": "",
                "warnings": ["使用降级建模方法"]
            }

        except Exception as exc:
            logger.error(f"建模指令生成失败: {exc}")
            return {
                "analysis_summary": f"分析失败: {str(exc)}",
                "modeling_strategy": "使用基础建模方法",
                "freecad_script": self._generate_fallback_script(geometry_data, extrude_height),
                "instructions": ["创建草图", "拉伸实体"],
                "key_dimensions": [],
                "completed_features": [],
                "skipped_features": [],
                "partial_completion_reason": "",
                "warnings": ["使用降级建模方法"]
            }

    def generate_from_self_correction(
        self,
        correction_request: SelfCorrectionRequest,
        *,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """基于阶段内自纠请求重新生成建模指令。"""
        logger.info(
            "开始建模指令模型自纠: stage=%s round=%s/%s",
            correction_request.stage,
            correction_request.round_index,
            correction_request.max_rounds,
        )
        prompt = self._build_self_correction_prompt(correction_request)

        use_thinking = stage_thinking_enabled(
            self.config,
            STAGE_MODELING_GENERATION,
            default=bool(self.config.get("modeling_json_thinking", False)),
        )

        request_payload = apply_stage_request_options(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": self.MODELING_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            },
            self.config,
            stage=STAGE_MODELING_GENERATION,
            default_thinking=bool(self.config.get("modeling_json_thinking", False)),
            default_effort="max",
            legacy_thinking_keys=("modeling_json_thinking",),
        )
        response = self._create_chat_completion(
            file_path=file_path,
            **request_payload,
        )
        choice = response.choices[0]
        message = choice.message
        content = message.content
        if not content:
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                logger.warning("模型自纠正文为空，尝试从 reasoning_content 中提取 JSON")
                content = reasoning
            else:
                raise ValueError("模型自纠响应正文为空")

        result = self._extract_json(content)
        postprocessor = getattr(self, "postprocessor", None) or ModelingInstructionPostprocessor()
        return postprocessor.normalize(result, None)

    def _create_chat_completion(self, file_path: Optional[str] = None, **request_payload):
        call_span = self.telemetry_store.start_call(
            stage=STAGE_MODELING_GENERATION,
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

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _build_prompt(self, modeling_task_payload: Dict[str, Any]) -> str:
        """构建提示词"""
        retained = modeling_task_payload.get("retained_items")
        retained_instruction = ""
        if retained:
            retained_instruction = (
                "\n用户已确认以下部分成果，你必须遵守这些已确认结果，"
                "只重新生成未确认的部分：\n"
                + json.dumps(retained, ensure_ascii=False, indent=2)
            )
        operations = modeling_task_payload.get("modeling_operations") or []
        operations_section = ""
        if operations:
            operations_section = (
                "\n\n=== 建模操作序列 ===\n"
                "请按以下操作序列逐步构建模型。每个操作包含 operation 类型、描述和具体尺寸参数。\n"
                + json.dumps(operations, ensure_ascii=False, indent=2)
            )
        prompt = "\n".join([
            "请基于以下建模任务载荷生成FreeCAD建模脚本。",
            "只使用载荷中的 modeling_operations、dimensions、constraints；不要使用 features 中的原始语义数据。",
            "不要要求或假设存在原始图元明细。",
            retained_instruction,
            operations_section,
            "",
            "=== 建模任务载荷 ===",
            json.dumps(modeling_task_payload, ensure_ascii=False, indent=2),
        ])
        estimated_tokens = self._estimate_tokens(prompt)
        logger.info(f"Prompt大小: {len(prompt)}字符, ~{estimated_tokens} tokens")
        return prompt

    def _build_self_correction_prompt(
        self,
        correction_request: SelfCorrectionRequest,
    ) -> str:
        parts = [
            "请基于以下阶段内模型自纠请求，重新生成 FreeCAD 建模指令 JSON。",
            "你必须修复 validation_issues 中列出的脚本质量问题。",
            "只能使用 self_correction_request.stage_payload 中的建模任务载荷作为图纸事实来源。",
            "不要从 previous_output、risk_notes 或错误消息中新增尺寸、新特征或新图纸事实。",
            "不要重复输出同类脚本形态；必须满足 output_contract。",
        ]
        if correction_request.correction_goal:
            parts.append(f"【自纠目标】{correction_request.correction_goal}")
        parts.extend([
            "",
            "=== self_correction_request JSON ===",
            json.dumps(correction_request.to_dict(), ensure_ascii=False, indent=2),
        ])
        estimated_tokens = self._estimate_tokens("\n".join(parts))
        logger.info(f"模型自纠Prompt大小: {len(''.join(parts))}字符, ~{estimated_tokens} tokens")
        return "\n".join(parts)

    def _generate_fallback_script(self, geometry_data: Dict[str, Any],
                                  extrude_height: float) -> str:
        from src.model_generator.script_builder import build_fallback_script
        return build_fallback_script(geometry_data, extrude_height)

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
