# 技术架构文档

## 1. 总体架构

```text
DXF/DWG
  │
  ▼
CADParser ──► geometry_data ──► CADProcessor/CADPipeline
  │                                      │
  ├─ preview_cache PNG                   ├─ 基础模式: FreeCADModeler
  │                                      │
  └─ DWG: LibreDWG 转换                  └─ 智能模式: IntelligentEngineeringAnalyzer
                                             │
                                             ├─ EngineeringViewAnalyzer 本地视图初判
                                             ├─ DimensionExtractor 尺寸提取
                                             ├─ LLMViewAnalyzer DeepSeek 视图校正
                                             ├─ Shapely STRtree 本地关系分析
                                             └─ FreeCADInstructionGenerator AI 脚本生成
                                                       │
                                                       ▼
                                             AIScriptRunner / FreeCADBridge
                                                       │
                                                       ▼
                                             STEP / STL / FCStd / 报告
```

## 2. 模块职责

| 模块 | 主要文件 | 职责 |
|---|---|---|
| CAD 解析 | `src/cad_parser/parser.py` | DXF/DWG 解析、块展开、实体标准化、PNG 预览 |
| 几何分析 | `src/geometry_analyzer/analyzer.py` | Shapely 空间索引和实体关系分析 |
| 智能分析 | `src/intelligent_analyzer/` | 视图识别、尺寸提取、LLM 校正、建模指令生成 |
| 模型生成 | `src/model_generator/` | FreeCAD direct/subprocess 建模和 AI 脚本执行 |
| 批处理 | `src/batch_processor/` | 文件扫描、输出结构、处理编排、结果汇总 |
| 工具层 | `src/utils/` | 配置、日志、Result、缓存、预览路径、LLM 遥测 |
| GUI | `gui_example.py` | 桌面界面、缓存管理、AI 调用监控和日志面板 |
| CLI | `cad_cli.py` | 命令行单文件、目录、分析和智能处理 |

## 3. 关键数据结构

### 几何数据

```json
{
  "version": "AC1027",
  "units": "Millimeters",
  "entities": [
    {"type": "LINE", "layer": "0", "start": [0, 0, 0], "end": [100, 0, 0]},
    {"type": "CIRCLE", "layer": "HOLE", "center": [50, 50, 0], "radius": 10}
  ]
}
```

### 智能分析结果

```json
{
  "view_analysis": {},
  "rule_view_analysis": {},
  "dimension_extraction": {},
  "local_relationships": {},
  "modeling_instructions": {},
  "performance": {"stage_timings_seconds": {}, "entity_count": 0, "cache_hit": false},
  "llm_telemetry": []
}
```

`CADProcessResult` 包含 `success`、`input_file`、`geometry_data`、`relationships`、`intelligent_analysis`、`output_paths`、`error_message`、`entity_count`。

## 4. FreeCAD 调用模式

| 模式 | 触发条件 | 说明 |
|---|---|---|
| direct | 当前解释器可导入 FreeCAD/Part | 在 FreeCAD Python 内进程执行 |
| subprocess | 配置或自动发现 `python.exe` | 系统 Python 调用 FreeCAD 自带 Python |
| unavailable | 未安装或路径不可用 | 建模失败并返回明确错误 |

`FreeCADBridge` 优先读取 `freecad.bin_path` 或 `FREECAD_BIN_PATH`，随后扫描 Windows 常见安装目录。

## 5. 智能分析策略

1. 本地规则先给出视图初判，保证无 AI 时也有可解释结果。
2. 尺寸提取从 DIMENSION、TEXT、MTEXT 及周边几何中提取标注。
3. LLM 视图校正输出必须符合 `VIEW_ANALYSIS_SCHEMA`，不合规则回退本地规则。
4. 复杂实体数超过阈值时跳过全量本地关系分析，避免耗时失控。
5. 建模脚本生成失败时生成基础降级脚本；多视图降级脚本不会被直接用于普通拉伸。

## 6. 缓存与遥测

| 类型 | 默认路径 | 说明 |
|---|---|---|
| 分析缓存 | `.cache/analysis` | 以文件属性、拉伸高度和分析参数生成 SHA-256 键 |
| 预览缓存 | `.cache/previews` | 可通过 `CAD_PREVIEW_CACHE_DIR` 覆盖 |
| LLM 遥测 | `.cache/llm_telemetry/llm_calls.jsonl` | 记录调用阶段、耗时、token 和响应摘要 |

## 7. 安全边界

- `.env`、缓存、模型输出和日志文件不应作为源码提交。
- 日志脱敏只覆盖常见密钥形态，不替代最小化日志策略。
- AI 生成脚本应仅在可信图纸和可信环境中运行。
- 缓存删除逻辑只删除明确缓存文件，不进行递归目录批量删除。
