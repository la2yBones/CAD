# 技术架构文档

## 1. 总体架构

```text
DXF/DWG
  │
  ▼
CADParser ──► geometry_data ──► CADProcessor/CADPipeline
  │                                      │
  ├─ preview_cache PNG                   ├─ 平面拉伸路径: PlanarExtrudeModeler
  │                                      │
  └─ DWG: LibreDWG 转换                  └─ 统一智能处理: IntelligentEngineeringAnalyzer
                                             │
                                             ├─ EngineeringViewAnalyzer 本地视图初判
                                             ├─ DimensionExtractor 尺寸提取
                                             ├─ view_decision_payload → LLMViewAnalyzer 视图语义校正
                                             ├─ Shapely STRtree 本地关系分析
                                             └─ src/reconstruction 语义重建内核
                                                ├─ ReconstructionContextBuilder 重建上下文
                                                ├─ SemanticUnderstandingPayloadBuilder → PartSemanticGenerator
                                                ├─ path_contracts 专用路径契约
                                                ├─ path_clarification 路径层追问恢复
                                                ├─ choose_modeling_path 建模路径裁决
                                                └─ ModelingTaskBuilder → FreeCADInstructionGenerator
                                                       │
                                                       ▼
                                      IntelligentModelingExecutor 建模执行分发
                                                       │
                       ┌───────────────────────────────┼───────────────────────────────┐
                       ▼                               ▼                               ▼
            PlanarExtrudeModeler 平面拉伸      revolve_executor 回转体          AIScriptRunner AI 脚本
                                                       │
                                                       ▼
                                             STEP / STL / FCStd / 报告
```

## 2. 模块职责

| 模块 | 主要文件 | 职责 |
|---|---|---|
| CAD 解析 | `src/cad_parser/parser.py` | DXF/DWG 解析、块展开、实体标准化、PNG 预览 |
| 旧几何分析 | `src/legacy/geometry_analyzer/analyzer.py` | 已废弃兼容层，保留旧入口 |
| 兼容导出 | `src/compat/` | 集中承接旧 import 路径，避免兼容 shim 分散在主路径 |
| 语义重建内核 | `src/reconstruction/` | 重建上下文、零件语义、建模路径裁决和脚本生成 |
| 智能处理编排 | `src/intelligent_analyzer/` | 串联分析子过程并调用语义重建内核 |
| 建模执行分发 | `src/batch_processor/modeling_execution.py` | 消费建模路径裁决并分发到平面拉伸、回转体或 AI 脚本执行 |
| 平面拉伸执行 | `src/model_generator/planar_extrude.py` | `PlanarExtrudeModeler` 平面拉伸路径 adapter，当前复用旧实现 |
| 模型执行 | `src/model_generator/` | AI 脚本运行和 FreeCAD direct/subprocess 桥接 |
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
  "part_semantics": {},
  "modeling_path_decision": {},
  "modeling_instructions": {},
}
```

`CADProcessResult` 属于智能处理结果，包含 `success`、`mode`、`modeling_path`、`input_file`、`geometry_data`、`intelligent_analysis`、`output_paths`、`error_message`、`entity_count`。

## 4. FreeCAD 调用模式

| 模式 | 触发条件 | 说明 |
|---|---|---|
| direct | 当前解释器可导入 FreeCAD/Part | 在 FreeCAD Python 内进程执行 |
| subprocess | 配置或自动发现 `python.exe` | 系统 Python 调用 FreeCAD 自带 Python |
| unavailable | 未安装或路径不可用 | 建模失败并返回明确错误 |

`FreeCADBridge` 优先读取 `freecad.bin_path` 或 `FREECAD_BIN_PATH`，随后扫描 Windows 常见安装目录。

## 5. 智能处理策略

1. 本地规则先给出视图初判，保证无 AI 时也有可解释结果。
2. 尺寸提取从 DIMENSION、TEXT、MTEXT 及周边几何中提取标注。
3. LLM 视图校正只接收视图判定载荷，输出必须符合视图结果合同，不合规则回退本地规则。
4. 复杂实体数超过阈值时跳过全量本地关系分析，避免耗时失控。
5. 语义重建内核先依据路径契约筛选合法候选；若候选路径语义未闭合，则生成追问而不是静默回退；若多条路径同时闭合但缺少 `preferred_modeling_path`，同样进入路径优选追问；只有同时满足契约且已有执行器的专用路径才可被真正选中。当前 `planar_extrude` 可执行，`revolve` 已支持“轴线 + 闭合母线点列”的受约束回转体。
6. 统一智能处理只缓存智能分析结果；最终执行路径和产物属于智能处理结果。

三个大模型调用阶段均通过专用载荷隔离职责：视图语义校正使用视图判定载荷，零件语义生成使用语义理解载荷，建模指令生成使用建模任务载荷。全量 `geometry_data.entities`、完整视图实体列表、`source_entities` 和局部关系明细只供本地分析、裁决和校验使用，不作为 LLM 输入兜底。

`PartSemanticGenerator` 输出的零件语义必须显式包含 `planar_modeling_semantics`、`revolve_modeling_semantics` 和 `preferred_modeling_path`。当某条专用路径不适用时，对应语义字段应为 `null`；字段缺失表示模型输出未满足语义交接合同，不应被解释为“路径不适用”。

路径契约只消费这些显式建模语义字段，不再从 `base_features`、`coordinate_system` 或 `key_dimensions` 反推出平面拉伸语义。这样可以避免旧兼容字段绕过语义合同，使缺字段输出被误判为可执行。

专用建模路径通过 `ModelingPathRegistry` 注册到路径裁决侧。注册项包含路径 ID、展示标签、路径契约评估器、路径层追问构造器和路由建模结果构造器。该注册表不承接 FreeCAD 执行器、输出路径收集或 `CADProcessResult` 状态变更；这些属于建模执行分发职责。

路径层追问属于语义生成之后的局部恢复：用户补充拉伸深度、拉伸方向或路径优选后，系统把答案写回已有零件语义并重新执行路径契约裁决，不重新触发视图分析或零件语义生成。该恢复逻辑集中在 `src/reconstruction/path_clarification.py`，负责判断是否暂停、构造待澄清建模结果、附加路径层恢复上下文，以及把用户回答写回显式建模语义。`revolve` 被选中后直接交给确定性回转执行器，不再额外生成 AI FreeCAD 脚本。

建模执行分发集中在 `src/batch_processor/modeling_execution.py`。`CADProcessor` 只把智能分析结果、几何数据、输出结构和处理结果对象交给 `IntelligentModelingExecutor`；具体选择平面拉伸、回转体执行器或 AI 脚本运行器由执行分发模块负责。执行分发通过路径 handler 表承接专用建模路径，未注册路径才进入 AI 脚本执行。这样批处理代理不再持有每条建模路径的执行细节。

## 6. 平面拉伸路径边界

平面拉伸路径是统一智能处理内部的一条专用建模路径。它只在图纸已经被判定为可平面拉伸图、且相关语义满足执行条件时承接建模任务。

它的限制同样明确：

- 不负责视图类型裁决。
- 不承担复杂特征理解。
- 不承担多视图或复杂图纸的语义重建。

## 7. 缓存与遥测

| 类型 | 默认路径 | 说明 |
|---|---|---|
| 分析缓存 | `.cache/analysis` | 以文件属性和分析参数生成 SHA-256 键 |
| 预览缓存 | `.cache/previews` | 可通过 `CAD_PREVIEW_CACHE_DIR` 覆盖 |
| LLM 遥测 | `.cache/llm_telemetry/llm_calls.jsonl` | 记录调用阶段、耗时、token 和响应摘要 |

## 8. 安全边界

- `.env`、缓存、模型输出和日志文件不应作为源码提交。
- 日志脱敏只覆盖常见密钥形态，不替代最小化日志策略。
- AI 生成脚本应仅在可信图纸和可信环境中运行。
- 缓存删除逻辑只删除明确缓存文件，不进行递归目录批量删除。
