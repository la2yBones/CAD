# 批量处理模块使用手册

版本：2.0.0

## 模块概述

`src/batch_processor` 提供 CAD 文件扫描、验证、输出结构创建、单文件处理和目录批处理能力。CLI 和 GUI 均通过该模块编排处理流程。

## 模块结构

```text
src/batch_processor/
├── __init__.py
├── file_manager.py      # CADFileManager
├── processor.py         # CADProcessor / CADProcessResult
└── pipeline.py          # CADPipeline
```

## 组件职责

| 组件 | 职责 |
|---|---|
| `CADFileManager` | 输入目录、文件验证、输出路径和预览缓存路径 |
| `CADProcessor` | 单文件解析、分析、建模、导出和多视图保护 |
| `CADPipeline` | 对外单文件、多文件、目录处理接口 |
| `CADProcessResult` | 标准处理结果对象 |

## CLI 使用

```powershell
python cad_cli.py --list
python cad_cli.py --file examples/cad_files/sample.dxf --height 10
python cad_cli.py --file examples/cad_files/sample.dxf --analysis
python cad_cli.py --file examples/cad_files/sample.dxf --intelligent
python cad_cli.py --dir examples/cad_files --output-dir examples/output
```

## Python API

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

config = load_config()
pipeline = CADPipeline(config=config, input_dir="examples/cad_files", output_dir="examples/output")

basic = pipeline.process_file("sample.dxf", extrude_height=10.0, enable_analysis=False)
smart = pipeline.process_file_intelligent("sample.dxf", extrude_height=10.0)
results = pipeline.process_directory(extrude_height=10.0, enable_analysis=False)
summary = pipeline.get_summary(results)
```

## 输出结构

```text
examples/output/<图纸名>/
├── <图纸名>_geometry.json
├── <图纸名>.step
├── <图纸名>.stl
├── <图纸名>_process.log
├── <图纸名>_full.json       # 智能模式/仅分析模式
├── <图纸名>_freecad.py      # AI 生成脚本
└── <图纸名>_report.txt      # 智能分析报告
```

预览图由 `get_preview_cache_path()` 生成，默认在 `.cache/previews`，不再固定写入输出子目录。

## 多视图保护

`CADProcessor` 会分析图纸是否为二视图/三视图。若当前入口未执行可靠 AI 多视图建模脚本，则返回失败结果并说明原因，避免将多视图工程图当作单一闭合轮廓直接拉伸。

## 进度回调

`process_multiple_files()` 和 `process_directory()` 支持 `progress_callback(current, total, result)`，GUI 可用该回调更新进度。

## 错误处理

`CADProcessResult.success` 表示处理是否成功。失败时读取 `error_message`，成功时读取 `output_paths`。
