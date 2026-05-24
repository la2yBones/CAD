# CAD 图纸智能三维建模系统

本项目面向 DXF/DWG 工程图纸，提供从二维图纸解析、视图和尺寸理解、语义裁决、建模路径选择到 FreeCAD 三维模型导出的完整处理链。用户入口已经统一为 **智能处理**：系统先理解图纸，再依据结构化语义选择平面拉伸路径、回转体路径或语义重建路径。

当前 README 只描述当前代码事实。历史基础入口、旧类名和旧 import 路径仍作为兼容层存在，但不再作为推荐用法。

## 当前能力

- 解析 DXF，并通过内置 LibreDWG 将 DWG 转为 DXF 后解析。
- 提取 LINE、CIRCLE、ARC、LWPOLYLINE、TEXT、MTEXT、DIMENSION、INSERT 等实体。
- 生成稳定的 CAD 预览缓存。
- 结合本地规则、尺寸提取、投影关系和 DeepSeek V4 Pro 完成智能分析。
- 在语义生成前进行尺寸来源、尺寸绑定和特征证据的语义裁决。
- 依据路径契约选择平面拉伸、回转体或语义重建路径。
- 支持 `completed`、`partial_completed`、`needs_clarification`、`failed`、用户停止处理等状态。
- 通过 FreeCAD direct/subprocess 模式导出 STEP、STL、FCStd。
- 在 GUI 中展示预览、日志、缓存、LLM 遥测、阶段确认、批量进度和待恢复任务。

## 技术栈

| 领域 | 当前实现 |
|---|---|
| 语言 | Python 3.10+，当前推荐 `cad_study` Conda 环境 |
| CAD 解析 | `ezdxf` |
| DWG 转换 | 项目内置 `tools/bin/dwg2dxf.exe` |
| 几何与视图分析 | Shapely、NumPy、scikit-learn、本地规则 |
| 大模型 | DeepSeek V4 Pro，通过 OpenAI SDK 调用 |
| 建模执行 | FreeCAD Python API、AI 脚本运行器、确定性回转执行器 |
| GUI | Tkinter + matplotlib |
| 配置 | `config/config.example.yaml`、`.env`、环境变量 |
| 缓存与遥测 | `.cache/analysis`、`.cache/previews`、`.cache/llm_telemetry` |

## 快速开始

```powershell
cd E:\Code\CAD
D:\anaconda3\envs\cad_study\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写至少一个有效 DeepSeek API Key：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin

# 可选：项目已内置 tools/bin/dwg2dxf.exe
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

运行单元测试：

```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
```

启动 GUI：

```powershell
D:\anaconda3\envs\cad_study\python.exe gui_example.py
```

运行 CLI：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --list
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples/cad_files/sample.dxf
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples/cad_files/sample.dxf --analysis-only
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --dir examples/cad_files --output-dir examples/output
```

默认 `--file` 和 `--dir` 都走统一智能处理。`--analysis-only` 只保存分析结果和建模脚本，不执行三维建模。

## 处理流程

```text
CLI / GUI
  -> CADPipeline
  -> CADProcessor
  -> CADParser
      -> DXF 解析
      -> DWG 通过 LibreDWG 转换后解析
      -> geometry_data
  -> IntelligentEngineeringAnalyzer
      -> EngineeringViewAnalyzer 本地视图初判
      -> DimensionExtractor 尺寸提取
      -> LLMViewAnalyzer 视图语义校正
      -> 本地关系分析
      -> SemanticReconstructionPipeline
          -> SemanticPolicy 语义裁决
          -> PartSemanticGenerator 零件语义生成
          -> ModelingPathRegistry / 路径契约
          -> ModelingTaskBuilder 建模任务载荷
          -> FreeCADInstructionGenerator 建模脚本生成
  -> IntelligentModelingExecutor
      -> PlanarExtrudeModeler 平面拉伸路径
      -> revolve_executor 回转体路径
      -> AIScriptRunner 语义重建路径
  -> CADProcessResult
```

## 建模路径

| 路径 | 触发条件 | 执行方式 |
|---|---|---|
| 平面拉伸路径 | 图纸被裁决为可平面拉伸图，且平面建模语义闭合 | `PlanarExtrudeModeler`，当前复用旧平面拉伸实现 |
| 回转体路径 | 语义明确给出轴线、闭合母线点列和旋转角度 | `revolve_executor` 生成确定性 FreeCAD 脚本 |
| 语义重建路径 | 无法稳定归入专用路径，或需要复杂三维语义重建 | `FreeCADInstructionGenerator` + `AIScriptRunner` |

路径选择不是用户手动模式开关，而是语义重建内核依据路径契约做出的建模路径裁决。

## 输出与运行数据

单个图纸默认输出到：

```text
examples/output/<图纸名>/
├── <图纸名>_geometry.json
├── <图纸名>_full.json
├── <图纸名>_report.txt
├── <图纸名>_freecad.py
├── <图纸名>.step
├── <图纸名>.stl
└── <图纸名>_process.log
```

运行期数据默认位置：

| 路径 | 内容 |
|---|---|
| `.cache/analysis` | 智能分析缓存 |
| `.cache/previews` | CAD 预览 PNG 缓存 |
| `.cache/llm_telemetry/llm_calls.jsonl` | LLM 调用遥测 |
| `.cache/batch_pending` | GUI 待恢复任务 |
| `logs/` | 日志文件 |
| `examples/output/` | 示例输出与模型产物 |

这些运行期数据不应作为源码提交。

## 目录结构

```text
E:\Code\CAD
├── cad_cli.py                         # CLI 入口
├── gui_example.py                     # Tkinter GUI 入口
├── config/
│   └── config.example.yaml            # 配置模板
├── docs/
│   ├── architecture.md                # 技术架构
│   ├── compatibility.md               # 兼容入口冻结清单
│   ├── api/index.md                   # API 与模块参考
│   ├── adr/                           # 架构决策记录
│   ├── guides/                        # 使用与配置指南
│   └── modules/                       # 模块说明
├── src/
│   ├── batch_processor/               # 文件处理、状态转换、建模执行分发
│   ├── cad_parser/                    # DXF/DWG 解析与预览
│   ├── intelligent_analyzer/          # 智能分析编排与分析子过程
│   ├── reconstruction/                # 语义裁决、零件语义、路径契约和建模任务
│   ├── model_generator/               # FreeCAD 桥接、AI 脚本运行、平面拉伸 adapter
│   ├── compat/                        # 旧 import 路径集中兼容层
│   ├── legacy/                        # 旧实现保留区，不新增业务能力
│   └── utils/                         # 配置、日志、缓存、遥测、Result
├── tests/unit/                        # 单元测试
├── tools/                             # 诊断、缓存工具、内置二进制工具
└── examples/cad_files/                # 示例图纸
```

## 配置要点

配置读取优先级：

```text
操作系统环境变量
  > 项目根目录 .env
  > config/config.yaml 或 config/config.example.yaml 字面值
```

关键配置：

| 配置 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 统一智能处理必需 |
| `FREECAD_BIN_PATH` | 可选，指向 FreeCAD `bin` 目录 |
| `LIBREDWG_PATH` | 可选，外部 LibreDWG 路径；项目已内置 `tools/bin/dwg2dxf.exe` |
| `CAD_PREVIEW_CACHE_DIR` | 可选，覆盖预览缓存目录 |

FreeCAD 还支持项目级增强包：

```text
tools/freecad/<FreeCAD发行目录>/bin/python.exe
```

若存在该路径，系统会优先使用项目内 FreeCAD 运行时；仓库默认不提交完整 FreeCAD 本体。

## GUI 工作流

GUI 是当前最完整的交互入口，覆盖：

- 图纸列表和多选批量处理。
- DXF/DWG 预览。
- 单图纸阶段确认。
- 语义不足时保存待恢复任务。
- 只补充追问答案或自然语言建模提示后继续处理。
- 批量处理进度窗口。
- 缓存管理和 LLM 遥测查看。
- STEP 文本预览和输出目录打开。

GUI 只编排交互，不复制核心业务逻辑；处理仍通过 `CADPipeline` 和 `CADProcessor` 进入共享管线。

## 兼容入口

这些入口仍保留，但只用于迁移：

- `cad_cli.py --basic`
- `cad_cli.py --legacy-analysis`
- `cad_cli.py --analysis`
- `cad_cli.py --intelligent`
- `CADPipeline.process_file(...)`
- `CADPipeline.process_file_basic(...)`
- `CADPipeline.process_file_legacy_analysis(...)`
- `DXFParser`
- `GeometryAnalyzer`
- `FreeCADModeler`

新代码应使用统一智能处理入口、`CADParser`、`PlanarExtrudeModeler` 和当前模块路径。兼容范围和删除条件见 [docs/compatibility.md](docs/compatibility.md)。

## 安全与维护边界

- 不提交 `.env`、真实 API Key、缓存、日志、输出模型和图纸产物。
- 日志脱敏只是兜底，不能主动打印完整配置、请求头或密钥。
- AI 生成的 FreeCAD 脚本仍应视为可信环境内执行，后续安全方向是 API 白名单、输出目录限制和进程级隔离。
- 不使用递归批量删除命令清理缓存或输出；需要删除文件时一次只处理一个明确路径。
- 新增配置项时同步更新 `config/config.example.yaml` 和配置文档。
- 新增依赖时同步更新 `requirements.txt` 和 `pyproject.toml`。
- 改动智能处理、建模路径、状态结果或 GUI 流程时，同步更新 `CONTEXT.md`、相关 ADR 或模块文档。

## 文档入口

- [docs/architecture.md](docs/architecture.md)：当前架构和核心流程。
- [docs/guides/getting_started.md](docs/guides/getting_started.md)：安装与使用。
- [docs/guides/configuration.md](docs/guides/configuration.md)：配置与密钥管理。
- [docs/guides/gui_guide.md](docs/guides/gui_guide.md)：GUI 使用说明。
- [docs/api/index.md](docs/api/index.md)：API 与模块参考。
- [docs/compatibility.md](docs/compatibility.md)：兼容入口冻结清单。
- [docs/adr/](docs/adr/)：架构决策记录。

## 第三方组件许可

项目在 `tools/bin/` 内置 LibreDWG 的 `dwg2dxf.exe` 及运行库，用于 DWG 到 DXF 转换。LibreDWG 遵循 GPLv3；再分发时必须保留其来源、版本和许可说明。详见 [tools/bin/README.md](tools/bin/README.md)。
