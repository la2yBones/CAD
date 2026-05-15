# 部署运维手册

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 优先 |
| Python | 3.10+ |
| 建议环境 | Conda `cad_study` |
| 外部工具 | LibreDWG、FreeCAD 1.0+ |
| 网络 | 智能模式需要访问 DeepSeek API |

## 2. 安装步骤

```powershell
cd E:\Code\CAD
conda activate cad_study
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` 示例：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin

# DWG 转换已内置 LibreDWG 到 tools/bin/，以下为可选覆盖
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

## 3. 配置说明

| 配置 | 作用 | 必需场景 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 默认智能重建、`--legacy-analysis`、`--intelligent`、`--analysis-only` |
| `LIBREDWG_PATH` | LibreDWG 目录（可选，项目已内置 tools/bin/dwg2dxf.exe） | DWG 转换外部覆盖 |
| `FREECAD_BIN_PATH` | FreeCAD `bin` 目录 | 建模导出 |
| `CAD_PREVIEW_CACHE_DIR` | 预览图缓存目录 | 可选 |

## 4. 启动方式

```powershell
python cad_cli.py --list
python cad_cli.py --file examples/cad_files/sample.dxf --height 10
python cad_cli.py --file examples/cad_files/sample.dxf --intelligent
python cad_cli.py --dir examples/cad_files --output-dir examples/output
python gui_example.py
python tools/cache_tool.py stats
python tools/diagnose_export.py
```

## 5. 输出与运行数据

| 路径 | 内容 |
|---|---|
| `examples/output/<图纸名>/` | 几何 JSON、STEP、STL、日志路径、分析结果 |
| `.cache/analysis/` | 智能分析缓存 |
| `.cache/previews/` | 图纸预览 PNG |
| `.cache/llm_telemetry/llm_calls.jsonl` | AI 调用记录 |
| `logs/` | 按配置生成的日志文件 |

## 6. 运维检查清单

- `python -m pytest tests\unit -q` 可正常通过。
- `python cad_cli.py --list` 能列出示例图纸。
- `python tools/cache_tool.py stats` 能读取缓存目录。
- `FREECAD_BIN_PATH` 指向的目录下存在 `python.exe`。
- `tools/bin/dwg2dxf.exe` 存在（项目内置），或 `LIBREDWG_PATH` 指向有效 LibreDWG。
- 智能模式前确认 `DEEPSEEK_API_KEY` 不是模板值。

## 7. 故障处理

| 现象 | 排查方向 |
|---|---|
| 找不到 API Key | 检查 `.env` 或系统环境变量中的 `DEEPSEEK_API_KEY` |
| DWG 转换失败 | 确认 `tools/bin/dwg2dxf.exe` 存在，或检查 `LIBREDWG_PATH` |
| FreeCAD 不可用 | 检查 `FREECAD_BIN_PATH`，或确认 FreeCAD 是否安装 |
| 预览图为空 | 检查 CAD 是否包含实体、matplotlib/ezdxf 是否安装 |
| 智能模式很慢 | 查看 GUI 的 AI 调用监控或 `.cache/llm_telemetry` |
| 多视图未生成模型 | 这是保护行为，需要可靠 AI 多视图脚本或实现多视图重建算法 |

## 8. 安全与清理

- 不提交 `.env`、缓存目录、输出模型和日志。
- 缓存清理使用 `tools/cache_tool.py`，不要用递归删除命令。
- 需要手动删除文件时，一次只删除一个明确路径的文件。
