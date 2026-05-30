# 兼容入口冻结清单

本文档记录仍保留的旧入口、推荐替代入口和删除条件。兼容入口只用于历史调用、旧测试或迁移过渡；新代码不应继续扩展这些入口的业务能力。

## 冻结原则

- 新业务流程统一从智能处理进入，再由建模路径裁决选择平面拉伸路径、回转体路径或语义重建路径。
- 兼容入口只做转发或保留旧行为，不新增新的领域判断。
- 删除兼容入口前必须先用搜索确认无项目内引用，并同步更新测试、文档和迁移说明。

## Python API 兼容入口

| 旧入口 | 当前状态 | 推荐替代 | 删除前条件 |
|---|---|---|---|
| `src.model_generator.FreeCADModeler` | `PlanarExtrudeModeler` 的包级别名 | `PlanarExtrudeModeler`，或通过智能处理触发平面拉伸路径 | 确认外部导入已迁移到 `PlanarExtrudeModeler` 或统一智能处理 |

## 已删除的兼容层

以下兼容入口已在架构清理中移除，不再可用：

### CLI 参数

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `cad_cli.py --basic` | `cad_cli.py --file <drawing>` | 废弃的基础入口已移除 |
| `cad_cli.py --legacy-analysis` / `--analysis` | `cad_cli.py --file <drawing>` | 废弃的旧分析入口已移除 |
| `cad_cli.py --intelligent` | 省略该参数（默认即智能处理） | 兼容别名已移除 |
| `cad_cli.py --analysis-only` | `cad_cli.py --file <drawing>` | 仅分析模式已移除 |

### Pipeline 方法

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `CADPipeline.process_file(...)` | `process_file_intelligent(...)` | 兼容转发已移除 |
| `CADPipeline.process_file_basic(...)` | `process_file_intelligent(...)` | 平面拉伸兼容入口已移除 |
| `CADPipeline.process_file_legacy_analysis(...)` | `process_file_intelligent(...)` | 旧基础拉伸 + 历史分析入口已移除 |
| `CADPipeline.process_directory_basic(...)` | `process_directory_intelligent(...)` | 批处理兼容入口已移除 |
| `CADPipeline.process_multiple_files_basic(...)` | `process_multiple_files_intelligent(...)` | 批处理兼容入口已移除 |

### 类别名

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `src.cad_parser.DXFParser` | `CADParser` | 空子类别名已移除 |
| `src.__init__.py` 中的 `DXFParser` 延迟导入 | `from src.cad_parser import CADParser` | 顶级兼容导出已移除 |

### 模块与包

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `src/legacy/geometry_analyzer/GeometryAnalyzer` | `IntelligentEngineeringAnalyzer` | 废弃几何分析器已删除，零引用 |
| `src/legacy/basic_modeling/FreeCADModeler` | `src.model_generator.PlanarExtrudeModeler` | 实现已合并到 `planar_extrude.py`，legacy 包装已删除 |
| `src/legacy/` 整个目录 | 无 | 所有 legacy 模块已清理 |
| `src/compat/` | 直接导入实际定义位置 | 兼容转发层未落地，已从文档移除 |
| `src/intelligent_analyzer/__init__.py` 中从 `reconstruction` 的跨包导出 | 直接从 `src.reconstruction` 导入 | 跨包透传已移除 |

### 函数与方法

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `src.gui.helpers.modeling_self_correction_log_lines(...)` | `stage_self_correction_log_lines(...)` | 兼容函数别名已移除 |
| `src.utils.result.Result.Ok(...)` | `Result.ok(...)` | 向后兼容别名已移除 |
| `src.utils.result.Result.Err(...)` | `Result.fail(...)` | 向后兼容别名已移除 |
| `src.utils.result.Result.is_err` | `result.is_fail` 或 `not result.success` | 属性别名已移除 |
| `src.utils.result.Result.value` | `result.data` | 属性别名已移除 |
| `src.utils.result.Result.unwrap()` | `result.data` | 方法已移除 |
| `src.utils.result.Result.unwrap_or(default)` | `result.data if result.success else default` | 方法已移除 |
| `src.utils.result.Result.map(fn)` | 直接操作 `result.data` | 方法已移除 |
| `src.utils.result.Result.to_dict()` | 手动构建字典 | 方法已移除 |
| `src.utils.stage_report.build_view_stage_report(...)` | `build_view_stage_summary(payload).render()` | 未使用的快捷包装已移除 |
| `src.utils.stage_report.build_semantic_stage_report(...)` | `build_semantic_stage_summary(payload).render()` | 未使用的快捷包装已移除 |
| `PlanarExtrudeModeler.generate_script(...)` | 无 | 未使用方法已移除 |

### 接口参数

| 已删除入口 | 替代路径 | 说明 |
|---|---|---|
| `AnalysisCache._generate_cache_key(file_path, extrude_height, ...)` | `_generate_cache_key(file_path, analysis_params=...)` | `extrude_height` 兼容参数已移除 |
| `AnalysisCache.get(file_path, extrude_height, ...)` | `get(file_path, analysis_params=...)` | `extrude_height` 兼容参数已移除 |
| `AnalysisCache.set(file_path, extrude_height, ...)` | `set(file_path, result_data, analysis_params=...)` | `extrude_height` 兼容参数已移除 |
| `AnalysisCache.invalidate(file_path, extrude_height, ...)` | `invalidate(file_path, analysis_params=...)` | `extrude_height` 兼容参数已移除 |

### 归档目录

| 已删除路径 | 说明 |
|---|---|
| `tools/archive/root_legacy_tools/` | 旧版诊断/缓存工具脚本已清理 |
| `examples/archive/root_legacy_scripts/` | 旧版示例脚本已清理 |
| `tests/manual/root_legacy/` | 旧版手工测试已清理 |

## 重复代码合并

以下重复实现已提取为公共模块，原位置改为导入公共函数：

| 公共模块 | 合并的重复代码 | 原位置 |
|---|---|---|
| `src/utils/modeling_utils.py` `looks_like_english_sentence()` | 3 处相同实现 | `modeling_execution.py`、`modeling_instruction_postprocessor.py`、`semantic_postprocessor.py` |
| `src/utils/modeling_utils.py` `normalize_feature_records()` | 2 处相同实现 | `modeling_execution.py`、`ai_script_runner.py` |

## 检查命令

```powershell
Select-String -Path .\src\*.py,.\src\*\*.py,.\src\*\*\*.py,.\tests\unit\*.py -Pattern 'FreeCADModeler' -Encoding utf8
```

检查结果应只出现在 `model_generator/__init__.py` 的别名定义、`planar_extrude.py` 的类名引用或明确标注为兼容的导入中。
