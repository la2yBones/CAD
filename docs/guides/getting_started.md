# 快速开始指南

本文档将帮助您快速上手基于CAD图纸的3D建模系统。

## 前置准备

### 1. 安装Python

确保已安装Python 3.10或更高版本：

```bash
python --version
```

### 2. 安装FreeCAD

从 [FreeCAD官网](https://www.freecadweb.org/) 下载并安装FreeCAD 1.0+。

### 3. 安装 LibreDWG（用于DWG文件支持）

LibreDWG 是处理 DWG 文件的核心工具：
- 下载地址：https://www.gnu.org/software/libredwg/
- 我们已配置路径：`D:\Code\libredwg-0.13.4.8160-win64\`

### 4. 获取API密钥（可选但推荐）

- 注册 DeepSeek 平台账号
- 获取 DeepSeek V4 Pro API 密钥

## 安装步骤

### 1. 克隆项目

```bash
cd E:\Code\CAD
```

### 2. 使用 Conda 环境

```bash
# 激活环境
conda activate cad_study
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置项目

配置文件已设置完成（已包含API密钥和路径配置）。

## CAD 文件处理指南

### DXF 文件处理
DXF 是开放格式，可以直接解析：

```python
from src.dxf_parser import DXFParser

# 创建解析器
parser = DXFParser("examples/dxf_files/your_file.dxf")

# 解析文件
geometry_data = parser.parse()

# 导出为JSON
parser.export_json("output.json")
```

### DWG 文件处理（重点！）

DWG 是 AutoCAD 专有格式，需要转换。我们使用 LibreDWG 自动转换：

```python
from src.dxf_parser import DXFParser
from src.utils import load_config

# 加载配置（包含 LibreDWG 路径）
config = load_config()

# 直接解析 DWG 文件 - 系统会自动转换为DXF！
parser = DXFParser("examples/dxf_files/your_file.dwg", config.get("dxf_parser", {}))

# 解析（转换+解析，全程自动化！
geometry_data = parser.parse()
```

### DWG 转换原理
1. **自动检测文件扩展名
2. 使用 LibreDWG 转换
3. 转换后的 DXF 保存于同目录
4. 解析转换后的 DXF

## 第一个示例

### 方式一：图形界面（推荐）

```bash
python gui_example.py
```

打开图形界面后，双击文件列表中的图纸即可预览，设置参数后点击「开始处理」一键完成 2D→3D 转换。详见 [GUI 使用指南](./gui_guide.md)。

### 方式二：命令行脚本

将您的 DXF 或 DWG 文件放入 `examples/cad_files/` 目录。

```bash
# 运行完整示例
python examples/scripts/quickstart.py
```

生成的3D模型将保存在 `examples/output/` 目录中。

## 核心模块使用

### DXF/DWG 解析模块（重点！

```python
from src.dxf_parser import DXFParser
from src.utils import load_config

# 加载配置
config = load_config()

# 解析 DXF 文件
parser_dxf = DXFParser("examples/dxf_files/your_file.dxf", config.get("dxf_parser", {}))
geometry_data = parser_dxf.parse()

# 或者解析 DWG 文件（自动转换）
parser_dwg = DXFParser("examples/dxf_files/your_file.dwg", config.get("dxf_parser", {}))
geometry_data = parser_dwg.parse()

# 导出为 JSON
parser.export_json("output.json")
```

### 几何关系分析模块

```python
from src.geometry_analyzer import GeometryAnalyzer
from src.utils import load_config

# 加载配置
config = load_config()

# 创建分析器
api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
analyzer_config = config.get("api", {}).get("deepseek", {})
analyzer = GeometryAnalyzer(api_key, analyzer_config)

# 分析关系
relationships = analyzer.analyze(geometry_data)
```

### 3D建模模块

```python
from src.model_generator import FreeCADModeler
from src.utils import load_config

# 加载配置
config = load_config()

# 创建建模器
modeler_config = {}
if "freecad" in config:
    modeler_config.update(config.get("freecad", {}))
if "modeling" in config:
    modeler_config.update(config.get("modeling", {}))

modeler = FreeCADModeler(modeler_config)

# 生成模型
model = modeler.generate(geometry_data, relationships)

# 导出模型
model.export("output.step", format="STEP")
```

## 完整端到端示例

```python
from src.dxf_parser import DXFParser
from src.geometry_analyzer import GeometryAnalyzer
from src.model_generator import FreeCADModeler
from src.utils import load_config

# 1. 加载配置
config = load_config()

# 2. 解析 CAD 文件（DXF 或 DWG）
parser = DXFParser("examples/dxf_files/your_file.dxf", config.get("dxf_parser", {}))
geometry_data = parser.parse()

# 3. 分析几何关系
api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
analyzer = GeometryAnalyzer(api_key, config.get("api", {}).get("deepseek", {}))
relationships = analyzer.analyze(geometry_data)

# 4. 生成 3D 模型
modeler_config = {}
if "freecad" in config:
    modeler_config.update(config.get("freecad", {}))
if "modeling" in config:
    modeler_config.update(config.get("modeling", {}))

modeler = FreeCADModeler(modeler_config)
modeler.generate(geometry_data, relationships)
modeler.export("examples/models/output.step")
```

## 常见问题

### Q: FreeCAD导入失败怎么办？

A: 确保FreeCAD已正确安装，并且Python可以找到FreeCAD的库路径。检查 config.yaml 中的 freecad.bin_path 配置。

### Q: DWG文件如何处理？

A: 非常简单！直接使用相同的 DXFParser，系统会自动使用 LibreDWG 转换 DWG 文件！无需额外步骤！只需：
1. 确保 config.yaml 中配置了 libredwg_path
2. 直接传入 .dwg 文件路径即可
3. 系统自动转换并解析

### Q: 如何验证 DWG 转换是否正常？

A: 运行：
```bash
python examples/scripts/test_config.py
```
它会检查 LibreDWG 是否可用。

### Q: API调用费用如何？

A: 请参考 DeepSeek 平台的定价页面。也可以使用本地几何计算库减少API调用（analyzer 会优先尝试本地计算）。

### Q: DWG 转换失败可能原因？

1. 检查 LibreDWG 路径是否配置正确
2. 确认 DWG 文件没有损坏
3. 确保 DWG 文件没有加密
4. 尝试在 config.yaml 检查 libredwg_path 路径正确
5. 运行 `test_config.py 检查

## 下一步

- 阅读 [API文档](../api/index.md) 了解详细接口
- 查看 [示例脚本](../../examples/scripts/) 获取更多用法
- 查看 [Conda配置指南](./conda_setup.md) 了解环境配置

