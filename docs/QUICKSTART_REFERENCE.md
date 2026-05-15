# 快速参考卡片

## 🚀 开始使用

### 第一步：激活环境
```bash
conda activate cad_study
cd e:\Code\CAD
```

### 第二步：安装依赖
```bash
pip install -r requirements.txt
```

### 第三步：运行测试
```bash
# 1. 测试配置
python examples\scripts\test_config.py

# 2. 测试DeepSeek API
python examples\scripts\test_api.py

# 3. 创建示例DXF
python examples\scripts\create_sample_dxf.py

# 4. 运行完整示例
python examples\scripts\quickstart.py
```

## 📁 项目结构

```
e:\Code\CAD\
├── config/
│   ├── config.yaml          # 当前配置（已包含API密钥）
│   └── config.example.yaml  # 配置模板
├── src/
│   ├── cad_parser/          # CAD解析模块（通用，支持扩展）
│   ├── reconstruction/      # 新语义重建内核
│   ├── legacy/              # 旧兼容模块
│   ├── model_generator/     # 建模生成模块
│   └── utils/               # 工具函数
├── examples/
│   ├── cad_files/           # 示例DXF/DWG图纸
│   └── scripts/             # 示例脚本
└── docs/                    # 文档
```

## ⚙️ 配置文件

### config/config.yaml (已配置好)
```yaml
api:
  deepseek:
    api_key: "sk-xxxxxxxxxxxxxxxx"
    base_url: "https://api.deepseek.com"
    model: "deepseek-v4-pro"
```
dxf_parser:
  # libredwg_path: "D:\\Code\\libredwg-0.13.4.8160-win64"  # 可选，项目已内置 tools/bin/dwg2dxf.exe

freecad:
  bin_path: "D:\\FreeCAD 1.0\\bin"
```

## 📝 CAD文件处理

### 通用 CAD 解析器
| 特性 | 说明 |
|------|------|
| **支持格式** | DXF 和 DWG 自动识别 |
| **解析器类** | `CADParser`（通用名称） |
| **示例文件** | 放入 `examples\cad_files\` 目录 |
| **创建示例** | `python examples\scripts\create_sample_dxf.py` |

### DWG 文件处理（重点！）
DWG 是 AutoCAD 的专有格式，需要先转换为 DXF。

| 步骤 | 说明 |
|------|------|
| **转换方式** | 使用 **LibreDWG 自动转换 |
| **配置位置** | `examples\cad_files\` 目录放置 DWG 文件 |
| **自动处理** | CADParser 会自动检测并转换 DWG 文件 |
| **转换器** | 配置 `dxf_converter: "libredwg"` |

### CAD 处理示例

```python
from src.cad_parser import CADParser
from src.utils import load_config

# 加载配置
config = load_config()

# 直接解析 DWG 或 DXF 文件（会自动处理格式）
parser = CADParser("examples/cad_files/your_file.dxf", config.get("dxf_parser", {}))
geometry_data = parser.parse()
```

### 向后兼容性
仍然可以使用旧的类名：
```python
from src.cad_parser import DXFParser  # 仍然可用！
```

## 📝 常用命令

| 操作 | 命令 |
|------|------|
| 激活环境 | `conda activate cad_study` |
| 运行API测试 | `python examples\scripts\test_api.py` |
| 运行完整示例 | `python examples\scripts\quickstart.py` |
| 创建DXF示例 | `python examples\scripts\create_sample_dxf.py` |
| 测试DWG处理 | `python examples\scripts\test_dwg_conversion.py` |

## 🔧 问题排查

### Q: 找不到Python模块？
```bash
# 确保在项目根目录
cd e:\Code\CAD

# 使用python命令而不是python
python examples\scripts\test_config.py
```

### Q: 找不到FreeCAD？
- 检查 config.yaml 中的 freecad.bin_path 路径
- 确保路径指向 bin 目录

### Q: API调用失败？
- 确认API密钥正确
- 检查网络连接
- 检查API额度是否充足

### Q: 如何添加自己的DXF/DWG文件？
- 放入 `examples\cad_files\` 目录
- 修改 quickstart.py 中的文件路径
- DWG 文件会自动转换

### Q: DWG 转换失败？
- 确认 `tools/bin/dwg2dxf.exe` 存在（项目已内置）
- 检查 `LIBREDWG_PATH` 配置（可选）
- 确保 DWG 文件没有加密或损坏
- 运行 `python examples\scripts\test_config.py` 检查配置

## 📚 更多文档

- [Conda环境配置指南](./guides/conda_setup.md)
- [完整使用指南](./guides/getting_started.md)
- [API文档](./api/index.md)
- [README](../README.md)
