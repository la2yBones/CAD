# 批量处理模块使用手册

## 模块概述

`src/batch_processor` 提供 CAD 文件扫描、验证、输出结构创建、单文件处理、建模执行分发和目录批处理能力。CLI 和 GUI 均通过该模块进入统一智能处理。

## 模块结构

```text
src/batch_processor/
├── __init__.py
├── file_manager.py      # CADFileManager
├── processor.py         # CADProcessor / CADProcessResult
├── pipeline.py          # CADPipeline
└── pending_store.py     # PendingClarificationStore
```

## 组件职责

| 组件 | 职责 |
|---|---|
| `CADFileManager` | 输入目录、文件验证、输出路径和预览缓存路径 |
| `CADProcessor` | 单文件解析、智能分析、状态转换、建模执行分发和待恢复结果组装 |
| `CADPipeline` | 对外单文件、多文件、目录处理入口，推荐使用智能处理入口 |
| `CADProcessResult` | 标准处理结果对象 |
| `PendingClarificationStore` | 持久化批量处理中等待恢复的 `needs_clarification` 项 |

## CLI 使用

```powershell
python cad_cli.py --list
python cad_cli.py --file examples/cad_files/sample.dxf
python cad_cli.py --file examples/cad_files/sample.dxf --analysis-only
python cad_cli.py --dir examples/cad_files --output-dir examples/output
```

## Python API

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

config = load_config()
pipeline = CADPipeline(config=config, input_dir="examples/cad_files", output_dir="examples/output")

smart = pipeline.process_file_intelligent("sample.dxf")
results = pipeline.process_directory_intelligent()
summary = pipeline.get_summary(results)
```

`process_file_basic(...)`、`process_file_legacy_analysis(...)` 和 `process_directory_basic(...)` 仍可用于兼容或内部验证，但新业务流程不应直接绕过统一智能处理。

## 输出结构

```text
examples/output/<图纸名>/
├── <图纸名>_geometry.json
├── <图纸名>.step
├── <图纸名>.stl
├── <图纸名>_process.log
├── <图纸名>_full.json       # 智能处理/仅分析模式
├── <图纸名>_freecad.py      # AI 生成脚本
└── <图纸名>_report.txt      # 智能分析报告
```

预览图由 `get_preview_cache_path()` 生成，默认在 `.cache/previews`，不再固定写入输出子目录。

## 多视图保护

`CADProcessor` 会通过智能分析和语义重建内核判断图纸结构，再依据建模路径裁决选择平面拉伸路径、回转体路径或语义重建路径。兼容平面拉伸入口仍保留多视图保护，避免将多视图工程图当作单一闭合轮廓直接拉伸。

## 进度回调

`process_multiple_files_basic()`、`process_directory_basic()`、`process_multiple_files_intelligent()` 和 `process_directory_intelligent()` 支持 `progress_callback(current, total, result)`，GUI 可用该回调更新进度。

## 待恢复任务

GUI 批量处理多张选中图纸时，如果单张图纸返回 `needs_clarification`，界面会把它保存为待恢复任务，然后继续处理下一张图纸。默认存储目录为 `.cache/batch_pending`。

每个待恢复任务保存：

- 输入图纸路径。
- 输出目录。
- 拉伸高度和处理模式。
- 结构化追问清单。
- 澄清上下文。
- 创建和更新时间。

调用方可通过 `list_pending()` 展示待恢复任务列表，通过 `load(pending_id)` 读取记录，通过 `mark_resolved(pending_id)` 在恢复成功后隐藏该项。

## 错误处理

`CADProcessResult.success` 表示处理是否成功。失败时读取 `error_message`，成功时读取 `output_paths`。
