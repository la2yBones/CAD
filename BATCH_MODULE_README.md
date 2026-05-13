# CAD图纸批量处理模块使用手册

## 模块概述

本模块提供了完整的CAD图纸到3D模型的批量处理功能，具有清晰的模块化架构和标准化的外部接口，支持单文件处理、批量处理，并为后续图形化界面开发预留了接口。

---

## 模块架构

```
src/batch_processor/
├── __init__.py          # 模块入口
├── file_manager.py      # 文件管理组件
├── processor.py         # 核心处理引擎
└── pipeline.py          # 高级处理管道
```

### 组件说明

| 组件 | 职责 |
|------|------|
| `CADFileManager` | 文件查找、验证、输出目录管理 |
| `CADProcessor` | 单个图纸的完整处理流程封装 |
| `CADPipeline` | 高级接口，支持单文件/批量处理 |

---

## 快速开始

### 1. 命令行工具（推荐）

最简单的方式是使用 `cad_cli.py` 命令行工具：

```bash
# 列出可用文件
python cad_cli.py --list

# 处理单个文件
python cad_cli.py --file sample.dxf --height 10

# 处理整个文件夹
python cad_cli.py --dir examples/cad_files --out my_output

# 启用AI分析
python cad_cli.py --file sample.dxf --analysis

# 显示详细日志
python cad_cli.py --file sample.dxf --verbose
```

### 2. 示例脚本

项目提供了两个示例脚本：

- `example_1_single_file.py` - 处理单个文件
- `example_2_batch.py` - 批量处理

### 3. GUI演示

运行 `gui_example.py` 查看图形界面的集成方式：

```bash
python gui_example.py
```

---

## Python 接口调用

### 基础用法

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

# 加载配置
config = load_config()

# 创建处理管道
pipeline = CADPipeline(
    config=config,
    input_dir="examples/cad_files",
    output_dir="examples/output"
)

# 方式1: 处理单个文件
result = pipeline.process_file("sample.dxf", extrude_height=10.0)
if result.success:
    print(f"成功! 输出文件: {result.output_paths['model_step']}")

# 方式2: 批量处理
results = pipeline.process_directory()
pipeline.print_summary(results)

# 方式3: 处理指定文件列表
files = ["sample.dxf", "齿轮架轮廓.dxf"]
results = pipeline.process_multiple_files(files)
```

### 进阶用法 - 独立使用组件

```python
from src.batch_processor import CADFileManager, CADProcessor

# 文件管理器
fm = CADFileManager("input_dir", "output_dir")

# 列出文件
files = fm.list_available_files()

# 验证文件
valid, error = fm.validate_file(files[0]['path'])

# 创建输出结构
output = fm.create_output_structure(files[0]['path'])

# 处理器
processor = CADProcessor(config)
result = processor.process_single_file(
    files[0]['path'],
    output,
    extrude_height=10.0
)
```

---

## 输出文件结构

每个图纸会在输出目录下创建独立的子目录：

```
examples/output/
├── sample/                        # 每个图纸独立目录
│   ├── sample_geometry.json       # 几何数据
│   ├── sample.step                # STEP模型
│   ├── sample.stl                 # STL模型（可选）
│   ├── sample_preview.png         # 预览图
│   └── sample_process.log         # 处理日志
└── 齿轮架轮廓/
    └── ...
```

---

## API 参考

### CADPipeline 类

```python
class CADPipeline:
    def __init__(self, config, input_dir, output_dir)

    # 文件操作
    def set_input_dir(dir: str)
    def set_output_dir(dir: str)
    def list_available_files() -> List[Dict]

    # 处理方法
    def process_file(filename, extrude_height=10.0, enable_analysis=True)
    def process_multiple_files(filenames, ...)
    def process_directory(input_dir=None, ...)

    # 结果处理
    def print_summary(results)
    def get_summary(results) -> Dict
```

### CADFileManager 类

```python
class CADFileManager:
    SUPPORTED_FORMATS = ['.dxf', '.dwg']

    def list_available_files() -> List[Dict]
    def validate_file(path) -> (bool, str)
    def create_output_structure(input_file) -> Dict[str, Path]
    def resolve_file_path(filename) -> Path
```

---

## 错误处理

所有处理结果通过 `CADProcessResult` 对象返回，包含：

- `success` - 是否成功
- `error_message` - 错误信息（如果失败）
- `output_paths` - 输出文件路径字典
- `entity_count` - 提取的实体数量

---

## 为GUI开发预留的接口

`gui_example.py` 展示了如何将处理模块集成到图形界面中，主要特点：

1. 非阻塞的进度回调
2. 清晰的状态展示
3. 文件列表管理
4. 参数配置界面

---

## 支持的文件格式

- 输入: `.dxf`, `.dwg`
- 输出: `.step`, `.stl`, `.json`, `.png`

---

## 完整示例

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

def my_progress_callback(current, total, result):
    name = result.input_file.split('/')[-1]
    status = "✓" if result.success else "✗"
    print(f"[{current}/{total}] {status} {name}")

if __name__ == "__main__":
    config = load_config()

    pipeline = CADPipeline(
        config=config,
        input_dir="my_cad_files",
        output_dir="my_output"
    )

    results = pipeline.process_directory(
        extrude_height=15.0,
        enable_analysis=False,
        progress_callback=my_progress_callback
    )

    summary = pipeline.get_summary(results)
    print(f"成功: {summary['success']}/{summary['total']}")
```
