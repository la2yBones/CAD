# 智能工程图纸处理系统

## 概述

本系统提供了完整的工程图纸到3D模型的智能转换，包括：

- 工程视图识别（二视图、三视图）
- 尺寸标注提取
- FreeCAD建模指令生成
- 自动化3D建模

## 模块架构

```
src/
├── intelligent_analyzer/     # 新增：智能分析模块
│   ├── __init__.py
│   ├── view_analyzer.py          # 视图分析器
│   ├── dimension_extractor.py # 尺寸提取器
│   ├── modeling_generator.py  # FreeCAD指令生成器
│   └── pipeline.py            # 整合管道
├── batch_processor/         # 批量处理模块（已增强）
└── ...
```

## 快速开始

### 1. 使用命令行工具

```bash
# 基础AI分析模式（几何关系分析 + 通用建模器）
python cad_cli.py -f sample.dxf -H 10 --analysis

# 智能模式（推荐）- 包含视图识别、尺寸提取、建模指令生成
python cad_cli.py -f sample.dxf --intelligent

# 仅分析不建模（生成报告和FreeCAD脚本）
python cad_cli.py -f sample.dxf --analysis-only

# 处理整个目录
python cad_cli.py -d examples/cad_files --intelligent
```

### 2. Python API

```python
from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
from src.utils import load_config

config = load_config()
api_key = config['api']['deepseek']['api_key']

# 创建分析器
analyzer = IntelligentEngineeringAnalyzer(api_key, config['api']['deepseek'])

# 执行完整分析
result = analyzer.analyze_full(geometry_data, extrude_height=10.0)

# 保存结果
analyzer.save_results(result, 'output', 'sample')
```

### 3. 与批量处理管道集成

```python
from src.batch_processor import CADPipeline

pipeline = CADPipeline(config, 'input_dir, 'output_dir')

# 基础处理
result = pipeline.process_file('sample.dxf')

# 智能分析处理（新增）
result = pipeline.process_file_intelligent('sample.dxf', extrude_height=10.0)
```

## 输出文件结构

```
examples/output/
└── sample/
    ├── sample_geometry.json      # 几何数据
    ├── sample.step            # STEP 3D模型
    ├── sample_full.json       # 完整分析结果
    ├── sample_freecad.py      # FreeCAD建模脚本
    └── sample_report.txt     # 分析报告
```

## 核心功能

### 1. 视图分析

- 自动识别工程图纸中的视图结构：
  - 主视图
  - 俯视图
  - 左视图
  - 其他视图

### 2. 尺寸提取

- 提取尺寸标注文本
- 识别尺寸类型：
  - 线性尺寸
  - 直径/半径尺寸
  - 螺纹尺寸
- 关联标注与几何元素

### 3. FreeCAD建模指令生成

- 分析零件结构
- 生成完整的Python脚本
- 包含所有建模步骤
- 支持参数化建模
