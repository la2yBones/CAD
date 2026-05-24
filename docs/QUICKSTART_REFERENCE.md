# 快速参考

## 🚀 开始使用

### 第一步：激活环境
```powershell
cd E:\Code\CAD
D:\anaconda3\envs\cad_study\python.exe --version
```

### 第二步：安装依赖
```powershell
D:\anaconda3\envs\cad_study\python.exe -m pip install -r requirements.txt
```

### 第三步：配置密钥
```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。`config/config.example.yaml` 使用 `${DEEPSEEK_API_KEY}` 占位符，不应写入真实密钥。

### 第四步：运行验证
```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --list
```

## 📁 项目结构

```
e:\Code\CAD\
├── config/
│   └── config.example.yaml  # 配置模板，本地 config.yaml 不提交
├── src/
│   ├── cad_parser/          # CAD 解析与预览
│   ├── intelligent_analyzer/ # 智能处理编排与分析子过程
│   ├── reconstruction/      # 语义重建内核
│   ├── model_generator/     # AI 脚本运行与 FreeCAD 桥接
│   ├── batch_processor/     # 文件扫描、单文件处理、批处理
│   ├── compat/              # 旧 import 路径兼容层
│   ├── legacy/              # 旧组件兼容实现
│   └── utils/               # 配置、缓存、日志、遥测
├── examples/
│   ├── cad_files/           # 示例DXF/DWG图纸
│   └── scripts/             # 示例脚本
└── docs/                    # 文档
```

## ⚙️ 配置文件

### `.env`
```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

### `config/config.example.yaml`
```yaml
api:
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com"
    model: "deepseek-v4-pro"
dxf_parser:
  libredwg_path: "${LIBREDWG_PATH}"
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

兼容入口和旧类名迁移见 [兼容入口冻结清单](compatibility.md)。

## 📝 常用命令

| 操作 | 命令 |
|------|------|
| 列出图纸 | `D:\anaconda3\envs\cad_study\python.exe cad_cli.py --list` |
| 统一智能处理 | `D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples\cad_files\sample.dxf` |
| 仅分析模式 | `D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples\cad_files\sample.dxf --analysis-only` |
| 运行 GUI | `D:\anaconda3\envs\cad_study\python.exe gui_example.py` |
| 运行单元测试 | `D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q` |

## 🔧 问题排查

### Q: 找不到Python模块？
```powershell
# 确保在项目根目录
cd E:\Code\CAD

# 使用 cad_study 环境解释器
D:\anaconda3\envs\cad_study\python.exe examples\scripts\test_config.py
```

### Q: 找不到 FreeCAD？
- 检查 `.env` 中的 `FREECAD_BIN_PATH`
- 确保路径指向 bin 目录

### Q: API调用失败？
- 确认 `.env` 中的 `DEEPSEEK_API_KEY` 正确
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
