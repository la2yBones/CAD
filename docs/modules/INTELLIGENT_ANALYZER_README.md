# 智能工程图纸处理系统

版本：2.0.0

## 概述

智能处理编排层负责把 CADParser 输出的结构化几何数据组织为后续处理可消费的智能分析结果。  
其中，“智能分析”是内部子过程，负责视图结构、尺寸标注、本地几何关系和语义结果生成；“语义重建内核”负责语义裁决、零件语义、建模路径选择以及建模指令或平面拉伸路由产出。

## 模块结构

```text
src/intelligent_analyzer/
├── pipeline.py              # 智能处理编排器（保留 IntelligentEngineeringAnalyzer 旧类名）
├── view_analyzer.py         # 本地规则视图分析
├── llm_view_analyzer.py     # DeepSeek 视图语义校正
├── view_schema.py           # 视图结果 Schema 与校验
└── dimension_extractor.py   # 尺寸提取

src/reconstruction/
├── context.py               # 统一三维重建上下文
├── semantics.py             # 结构化零件语义生成
├── semantic_schema.py       # 零件语义校验
├── instruction_generator.py # FreeCAD 建模指令生成
├── modeling_path.py         # 建模路径裁决
└── pipeline.py              # 语义重建内核主链

兼容说明：

- `src/intelligent_analyzer/reconstruction_context.py`
- `src/intelligent_analyzer/semantic_generator.py`
- `src/intelligent_analyzer/semantic_schema.py`
- `src/intelligent_analyzer/modeling_generator.py`

以上文件当前仅保留为旧路径入口；兼容导出集中在 `src/compat/intelligent_analyzer.py`，主实现已迁入 `src/reconstruction/`。
```

## 处理编排流程

1. `EngineeringViewAnalyzer` 进行本地规则视图初判。
2. `DimensionExtractor` 提取文本、尺寸实体和分类统计。
3. `LLMViewAnalyzer` 使用 DeepSeek 校正视图语义。
4. `ViewAnalysisValidator` 校验 JSON Schema、业务规则和可疑内容。
5. `_analyze_local_fallback()` 使用 Shapely STRtree 计算本地几何证据。
6. `SemanticReconstructionPipeline` 作为语义重建内核接管后续主链。
7. `ReconstructionContextBuilder` 将图元、视图、尺寸和关系整理为统一重建上下文。
8. `PartSemanticGenerator` 先生成结构化零件语义。
9. `choose_modeling_path()` 根据结构化语义选择 `planar_extrude` 或 `semantic_reconstruction`。
10. 若需要语义重建，`FreeCADInstructionGenerator` 基于统一上下文和零件语义生成建模说明与 FreeCAD Python 脚本。
11. 智能分析结果写入分析缓存，并可保存为 JSON、报告和脚本。

## CLI

```powershell
python cad_cli.py --file examples/cad_files/sample.dxf --intelligent
python cad_cli.py --file examples/cad_files/sample.dxf --analysis-only
```

## Python API

```python
from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
from src.utils import load_config

config = load_config()
api_cfg = config["api"]["deepseek"]
analyzer = IntelligentEngineeringAnalyzer(api_cfg["api_key"], api_cfg)
result = analyzer.analyze_full(geometry_data, extrude_height=10.0, file_path="sample.dxf")
analyzer.save_results(result, "examples/output/sample", "sample")
```

## 视图 Schema

LLM 视图校正结果必须包含 `analysis_id`、`timestamp`、`drawing_type`、`views`、`relationships`、`confidence`、`evidence`、`reason_summary`、`warnings`。

`drawing_type` 支持 `single_view`、`two_view`、`three_view`、`assembly_drawing`、`section_view`、`unknown`。

## 建模输出

`modeling_instructions` 包含 `analysis_summary`、`modeling_strategy`、`freecad_script`、`instructions`、`key_dimensions`、`warnings`。

## 重建上下文

`reconstruction_context` 是智能分析子过程到语义重建内核之间的统一消息协议，包含图纸元数据、视图摘要、尺寸列表、本地几何证据和紧凑图元集合。  
本地检测负责提供证据，不在该层硬编码具体零件语义；三维结构解释交由建模模型完成。

## 零件语义

`part_semantics` 是建模前的结构化解释层，包含基础体、增材特征、减材特征、坐标约定、关键尺寸、不确定项、候选解释、证据和置信度。  
先输出语义、再输出脚本，可以把“理解错误”和“脚本错误”分开诊断；当语义置信度低于阈值时，系统会停止自动建模而不是生成高风险模型。

## 结果边界

- `智能分析结果` 包含视图、尺寸、本地关系、语义结果和 `modeling_path_decision`。
- `智能处理结果` 由外层任务负责，包含最终 `modeling_path`、执行分支、产物和任务状态。

## 缓存与遥测

- 分析缓存默认 `.cache/analysis`。
- LLM 调用记录默认 `.cache/llm_telemetry/llm_calls.jsonl`。
- `performance.stage_timings_seconds` 记录每个阶段耗时。

## 安全与限制

- LLM 输出校验失败会回退本地规则。
- 智能模式会依据 `modeling_path_decision` 选择平面拉伸或语义重建路径。
- AI 生成脚本仍通过执行器运行，尚未实现强沙箱。
