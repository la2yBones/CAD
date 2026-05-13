# 基于CAD图纸的3D建模系统

毕业设计项目：实现从2D CAD图纸（DXF/DWG格式）到3D模型的智能转换。

## 项目简介

本系统集成了几何解析、AI关系推理和参数化建模技术，实现自动化3D建模流程。

### 核心功能

- **数据解析**：支持DXF/DWG格式解析，提取几何实体
- **关系分析**：基于DeepSeek的智能几何关系识别
- **建模生成**：自动生成FreeCAD建模脚本
- **模型导出**：支持STEP、STL等格式导出
- **可扩展性**：模块化设计，便于新增CAD格式支持

## 技术栈

| 组件 | 技术选型 | 版本 |
|------|---------|------|
| 开发语言 | Python | 3.10+ |
| CAD解析 | ezdxf | 1.4.3+ |
| AI模型 | DeepSeek | V3/Chat |
| 3D建模 | FreeCAD | 1.0+ |
| DWG转换 | LibreDWG | 0.13.4+ |
| 几何计算 | Shapely | 2.0+ |

## 项目结构

```
CAD/
├── src/                      # 源代码目录
│   ├── cad_parser/          # CAD解析模块（支持DXF/DWG）
│   ├── geometry_analyzer/   # 几何关系分析模块
│   ├── model_generator/     # 3D建模指令生成模块
│   └── utils/               # 工具函数
├── tests/                    # 测试目录
│   ├── unit/                # 单元测试
│   └── integration/         # 集成测试
├── docs/                     # 文档目录
│   ├── api/                 # API文档
│   └── guides/              # 使用指南
├── examples/                 # 示例文件
│   ├── cad_files/           # 示例DXF/DWG图纸
│   ├── models/              # 生成的3D模型
│   └── scripts/             # 示例脚本
├── config/                   # 配置文件
└── requirements.txt          # 依赖列表
```

## 快速开始

### 环境要求

- Python 3.10+
- Conda 环境管理器
- FreeCAD 1.0+
- LibreDWG 0.13.4+（用于DWG支持）

### 1. 配置Conda环境

详细指南请参考 [docs/guides/conda_setup.md](docs/guides/conda_setup.md)

```bash
# 激活已创建的环境
conda activate cad_study

# 安装依赖
cd e:\Code\CAD
pip install -r requirements.txt
```

### 2. 配置项目

配置文件已设置完成，包含：
- ✅ DeepSeek API 密钥
- ✅ LibreDWG 路径
- ✅ FreeCAD 路径

### 3. 运行测试

```bash
# 测试配置和依赖
python examples\scripts\test_config.py

# 测试DeepSeek API
python examples\scripts\test_api.py
```

### 4. 运行示例

```bash
# 1. 创建示例DXF文件
python examples\scripts\create_sample_dxf.py

# 2. 运行完整示例
python examples\scripts\quickstart.py
```

## 使用说明

### 基本使用流程

```python
from src.cad_parser import CADParser
from src.geometry_analyzer import GeometryAnalyzer
from src.model_generator import FreeCADModeler
from src.utils import load_config

# 加载配置
config = load_config()

# 1. 解析CAD文件（支持DXF和DWG）
parser = CADParser("examples/cad_files/sample.dxf", config.get("dxf_parser", {}))
geometry_data = parser.parse()

# 2. 分析几何关系
api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
analyzer_config = config.get("api", {}).get("deepseek", {})
analyzer = GeometryAnalyzer(api_key, analyzer_config)
relationships = analyzer.analyze(geometry_data)

# 3. 生成3D模型
modeler_config = {}
if "freecad" in config:
    modeler_config.update(config.get("freecad", {}))
if "modeling" in config:
    modeler_config.update(config.get("modeling", {}))

modeler = FreeCADModeler(modeler_config)
modeler.generate(geometry_data, relationships)
modeler.export("examples/models/output.step")
```

### 向后兼容性

旧的 `DXFParser` 类名仍然可用作为别名：
```python
from src.cad_parser import DXFParser  # 仍然可用！
```

详细使用指南请参考 [docs/guides/getting_started.md](docs/guides/getting_started.md)

## 开发计划

- [x] 项目结构搭建
- [x] 配置文件和文档
- [x] CAD解析模块基础（通用名称，支持扩展）
- [x] DeepSeek API集成
- [ ] 完整几何关系分析
- [ ] FreeCAD建模模块完善
- [ ] 系统集成与测试
- [ ] 文档完善

## 示例脚本说明

- `test_config.py` - 测试环境配置和依赖
- `test_api.py` - 测试DeepSeek API连接和几何分析
- `test_dwg_conversion.py` - 测试DWG文件处理功能
- `create_sample_dxf.py` - 创建示例DXF文件
- `quickstart.py` - 完整的端到端示例

## 贡献指南

本项目为毕业设计项目，欢迎提出建议和改进意见。

## 许可证

MIT License

## 联系方式

- 作者：[您的姓名]
- 邮箱：[您的邮箱]
