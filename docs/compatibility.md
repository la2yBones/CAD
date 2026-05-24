# 兼容入口冻结清单

本文档记录仍保留的旧入口、推荐替代入口和删除条件。兼容入口只用于历史调用、旧测试或迁移过渡；新代码不应继续扩展这些入口的业务能力。

## 冻结原则

- 新业务流程统一从智能处理进入，再由建模路径裁决选择平面拉伸路径、回转体路径或语义重建路径。
- 兼容入口只做转发或保留旧行为，不新增新的领域判断。
- 内部实现可以继续调用旧执行实现，但对外文档不再把旧入口作为推荐路径。
- 删除兼容入口前必须先用搜索确认无项目内引用，并同步更新测试、文档和迁移说明。

## CLI 兼容参数

| 旧入口 | 当前状态 | 推荐替代 | 删除前条件 |
|---|---|---|---|
| `cad_cli.py --basic` | 已废弃，仍保留旧基础入口 | `cad_cli.py --file <drawing>` | 确认演示、脚本和文档不再依赖基础入口 |
| `cad_cli.py --legacy-analysis` | 已废弃，仍保留旧分析入口 | `cad_cli.py --file <drawing>` 或 `--analysis-only` | 确认旧分析入口没有外部脚本依赖 |
| `cad_cli.py --analysis` | `--legacy-analysis` 的旧别名 | `--analysis-only` | 随 `--legacy-analysis` 一起移除 |
| `cad_cli.py --intelligent` | 兼容别名，与默认处理一致 | 省略该参数 | 确认外部命令示例已全部更新 |

## Python API 兼容入口

| 旧入口 | 当前状态 | 推荐替代 | 删除前条件 |
|---|---|---|---|
| `CADPipeline.process_file(...)` | 兼容转发 | `process_file_intelligent(...)` | 项目内无直接调用，外部迁移说明已发布 |
| `CADPipeline.process_file_basic(...)` | 平面拉伸兼容入口 | `process_file_intelligent(...)` | 平面拉伸路径拥有非 legacy 命名的内部 adapter |
| `CADPipeline.process_file_legacy_analysis(...)` | 旧基础拉伸 + 历史分析入口 | `process_file_intelligent(...)` | CLI 旧参数移除且无测试依赖 |
| `CADPipeline.process_directory_basic(...)` | 批处理兼容入口 | `process_directory_intelligent(...)` | 旧批处理脚本迁移完成 |
| `src.cad_parser.DXFParser` | `CADParser` 别名 | `CADParser` | 兼容测试可删除，外部迁移说明已发布 |
| `src.geometry_analyzer.GeometryAnalyzer` | 旧几何分析兼容导出 | `IntelligentEngineeringAnalyzer` | 无外部导入依赖，旧 AI 几何分析测试不再需要 |
| `src.model_generator.FreeCADModeler` | 平面拉伸 adapter 的兼容别名 | `PlanarExtrudeModeler`，或通过智能处理触发平面拉伸路径 | 确认外部导入已迁移到 `PlanarExtrudeModeler` 或统一智能处理 |

## 保留的内部旧实现

| 实现 | 当前用途 | 后续方向 |
|---|---|---|
| `src/model_generator/planar_extrude.py` | 平面拉伸路径 adapter | 后续可把旧实现迁入该模块，或继续包裹更明确的执行器 |
| `src/legacy/basic_modeling/FreeCADModeler` | 平面拉伸路径当前底层实现 | 只允许由 `PlanarExtrudeModeler` 或兼容层引用，不新增业务能力 |
| `src/legacy/geometry_analyzer/GeometryAnalyzer` | 旧导入兼容 | 不新增功能；确认无引用后删除 |
| `src/compat/*` | 集中承接旧 import 路径 | 只做兼容转发，不承载新业务逻辑 |

## 检查命令

```powershell
Select-String -Path .\*.py,.\src\*.py,.\src\*\*.py,.\src\*\*\*.py,.\tests\unit\*.py,.\docs\*.md,.\docs\*\*.md -Pattern 'DXFParser|GeometryAnalyzer|FreeCADModeler|process_file_legacy_analysis|process_file_basic|process_directory_basic|--basic|--legacy-analysis' -Encoding utf8
```

检查结果应只出现在本清单、兼容 shim、兼容测试、`PlanarExtrudeModeler` adapter 或明确标注为已废弃的入口中。
