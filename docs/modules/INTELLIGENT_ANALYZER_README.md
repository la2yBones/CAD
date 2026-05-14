# 智能工程图纸处理系统

版本：2.0.0

## 概述

智能分析模块负责将 CADParser 输出的结构化几何数据转换为可用于建模的工程语义，包括视图结构、尺寸标注、本地几何关系和 FreeCAD 建模脚本。

## 模块结构

```text
src/intelligent_analyzer/
├── pipeline.py              # IntelligentEngineeringAnalyzer
├── view_analyzer.py         # 本地规则视图分析
├── llm_view_analyzer.py     # DeepSeek 视图语义校正
├── view_schema.py           # 视图结果 Schema 与校验
├── dimension_extractor.py   # 尺寸提取
└── modeling_generator.py    # FreeCAD 建模指令生成
```

## 分析流程

1. `EngineeringViewAnalyzer` 进行本地规则视图初判。
2. `DimensionExtractor` 提取文本、尺寸实体和分类统计。
3. `LLMViewAnalyzer` 使用 DeepSeek 校正视图语义。
4. `ViewAnalysisValidator` 校验 JSON Schema、业务规则和可疑内容。
5. `_analyze_local_fallback()` 使用 Shapely STRtree 计算本地关系。
6. `FreeCADInstructionGenerator` 生成建模说明和 FreeCAD Python 脚本。
7. 结果写入分析缓存，并可保存为 JSON、报告和脚本。

## CLI

```powershell
python cad_cli.py --file examples/cad_files/sample.dxf --analysis
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

## 缓存与遥测

- 分析缓存默认 `.cache/analysis`。
- LLM 调用记录默认 `.cache/llm_telemetry/llm_calls.jsonl`。
- `performance.stage_timings_seconds` 记录每个阶段耗时。

## 安全与限制

- LLM 输出校验失败会回退本地规则。
- 建模指令生成失败会生成基础降级脚本。
- 二/三视图场景若只有基础降级脚本，批处理器会阻止普通拉伸。
- AI 生成脚本仍通过执行器运行，尚未实现强沙箱。
