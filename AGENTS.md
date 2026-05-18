# AGENTS.md — CAD 图纸 3D 建模系统

> 面向 AI 编码助手的项目技术档案。本文说明项目业务目标、模块角色、权限边界、交互流程、对接接口、配置约定和维护规范。

---

## 1. 项目概述

本项目是一个 **CAD 二维图纸智能分析与三维重建系统**。输入 DXF/DWG 工程图后，系统解析图元、识别工程视图和尺寸信息，并通过 FreeCAD 生成 STEP、STL、FCStd 等三维模型文件。

核心定位：

- **基础模式**：不调用 AI，按单一闭合轮廓进行通用平面拉伸建模。
- **智能模式**：调用 DeepSeek V4 Pro 进行视图语义校正、尺寸提取和 FreeCAD 脚本生成。
- **保护策略**：检测到二视图/三视图且未获得可靠 AI 多视图建模脚本时，阻止普通平面拉伸，避免生成错误模型。

运行环境：

| 项 | 当前约定 |
|---|---|
| 语言 | Python 3.10+ |
| 主要系统 | Windows |
| 大模型 | DeepSeek V4 Pro，通过 OpenAI SDK 调用 |
| 建模引擎 | FreeCAD Python API |
| DWG 转换 | LibreDWG `dwg2dxf.exe` |
| GUI | Tkinter + matplotlib |

---

## 2. 统一术语

| 术语 | 含义 |
|---|---|
| CAD 解析 | 将 DXF/DWG 文件转换为标准化 `geometry_data` |
| 基础模式 | 不调用 AI 的通用 FreeCAD 建模流程 |
| 智能模式 | 使用 DeepSeek、智能分析管道和 AI 脚本优先建模的流程 |
| 智能分析 | 视图识别、尺寸提取、LLM 视图校正、本地关系分析和建模指令生成 |
| 预览缓存 | CAD 预览 PNG 缓存，默认 `.cache/previews` |
| 分析缓存 | 智能分析结果缓存，默认 `.cache/analysis` |
| LLM 遥测 | 大模型调用耗时、token 和状态记录，默认 `.cache/llm_telemetry/llm_calls.jsonl` |
| 通用建模器 | `FreeCADModeler`，用于基础闭合轮廓建模 |
| AI 脚本运行器 | `AIScriptRunner`，用于执行 AI 生成的 FreeCAD 脚本 |

---

## 3. 代理角色总览

这里的“代理”指系统中承担独立职责、可被 CLI/GUI/批处理管道调用的模块角色。

| 角色 | 入口 | 状态 | 核心职责 |
|---|---|---|---|
| CLI 入口代理 | `cad_cli.py` | 启用 | 参数解析、模式选择、单文件/目录处理 |
| GUI 应用代理 | `gui_example.py` | 启用 | 文件选择、预览、处理、日志、缓存和 AI 调用监控 |
| 文件管理代理 | `src/batch_processor/file_manager.py` | 启用 | 扫描 CAD 文件、验证输入、创建输出结构 |
| 批处理管道代理 | `src/batch_processor/pipeline.py` | 启用 | 单文件、多文件、目录级处理编排 |
| 单文件处理代理 | `src/batch_processor/processor.py` | 启用 | 解析、分析、建模、导出、多视图保护 |
| CAD 解析代理 | `src/cad_parser/parser.py` | 启用 | DXF/DWG 解析、块展开、JSON 导出、PNG 预览 |
| 本地视图分析代理 | `src/intelligent_analyzer/view_analyzer.py` | 启用 | 本地规则和聚类视图初判 |
| LLM 视图校正代理 | `src/intelligent_analyzer/llm_view_analyzer.py` | 启用 | DeepSeek 视图语义校正和校验回退 |
| 视图结果校验代理 | `src/intelligent_analyzer/view_schema.py` | 启用 | JSON Schema、业务规则和可疑内容校验 |
| 尺寸提取代理 | `src/intelligent_analyzer/dimension_extractor.py` | 启用 | DIMENSION/TEXT/MTEXT 尺寸提取和分类 |
| 智能处理编排代理 | `src/intelligent_analyzer/pipeline.py` | 启用 | 串联智能分析子过程，并调用语义重建内核产出后续处理所需结果 |
| 建模指令生成代理 | `src/reconstruction/instruction_generator.py` | 启用 | DeepSeek 生成 FreeCAD 建模指令和脚本 |
| 兼容导出代理 | `src/compat/` | 启用 | 集中承接旧 import 路径，主路径只保留轻量入口 |
| FreeCAD 桥接代理 | `src/model_generator/freecad_bridge.py` | 启用 | direct/subprocess 模式检测和脚本执行 |
| 通用建模代理 | `src/legacy/basic_modeling/generator.py` | 启用 | 基础模式的平面轮廓建模和 STEP/STL/FCStd 导出 |
| AI 脚本运行代理 | `src/model_generator/ai_script_runner.py` | 启用 | AI FreeCAD 脚本执行和产物收集 |
| 分析缓存代理 | `src/utils/cache.py` | 启用 | 智能分析缓存读写、失效和统计 |
| 预览缓存代理 | `src/utils/preview_cache.py` | 启用 | CAD 预览图稳定路径生成 |
| LLM 遥测代理 | `src/utils/llm_telemetry.py` | 启用 | LLM 调用记录和统计汇总 |
| 配置代理 | `src/utils/config.py` | 启用 | YAML、`.env`、环境变量解析 |
| 日志代理 | `src/utils/logging.py` | 启用 | 日志初始化和敏感信息脱敏 |
| 旧几何分析代理 | `src/geometry_analyzer/analyzer.py` | 废弃兼容 | 保留兼容入口，新代码使用智能处理编排代理 |

---

## 4. 核心交互流程

### 4.1 基础模式

```text
CLI/GUI
  -> CADPipeline
  -> CADFileManager.resolve_file_path()
  -> CADPipeline.process_file_basic()
  -> CADParser.parse()
  -> CADParser.export_json()
  -> CADParser.visualize()
  -> FreeCADModeler.generate()
  -> FreeCADModeler.export()
  -> CADProcessResult
```

基础模式不需要 API Key，默认输入已经是可平面拉伸图；它不再负责视图类型裁决。

### 4.2 智能模式

```text
CLI/GUI
  -> CADPipeline.process_file_intelligent()
  -> CADProcessor.process_with_intelligent_analysis()
  -> CADParser.parse()
  -> IntelligentEngineeringAnalyzer.analyze_full()
      -> EngineeringViewAnalyzer.analyze_views()
      -> DimensionExtractor.extract_dimensions()
      -> LLMViewAnalyzer.refine_view_analysis()
      -> ViewAnalysisValidator.validate()
      -> IntelligentEngineeringAnalyzer._analyze_local_fallback()
      -> SemanticReconstructionPipeline.run()
          -> SemanticPolicy.evaluate()
          -> PartSemanticGenerator.generate()
          -> choose_modeling_path()
          -> FreeCADInstructionGenerator.generate() 或 planar_extrude 路由
  -> AIScriptRunner.run_script() 或基础拉伸执行路径
  -> FreeCADBridge.execute_script()
  -> CADProcessResult
```

智能模式需要有效 `DEEPSEEK_API_KEY`。LLM 视图校正失败时可回退本地规则；语义重建内核会依据分析结果给出建模路径裁决，智能模式再执行对应路径。

### 4.3 仅分析模式

```text
cad_cli.py --analysis-only
  -> CADParser.parse()
  -> IntelligentEngineeringAnalyzer.analyze_full()
  -> IntelligentEngineeringAnalyzer.save_results()
  -> <base>_full.json / <base>_report.txt / <base>_freecad.py
```

仅分析模式不生成 3D 模型，适合调试 DeepSeek 输出、查看视图校正和建模脚本。

### 4.4 GUI 监控流程

```text
CADApplication
  -> ProcessingPanel
  -> LogPanel
  -> CacheManagerPanel
  -> LLMTelemetryPanel
```

GUI 负责交互和展示，不复制核心业务逻辑。处理逻辑必须继续通过 `CADPipeline` 和 `CADProcessor` 调用。

---

## 5. 角色权限范围

### 5.1 CAD 解析代理

允许：

- 读取 DXF 文件。
- 调用 LibreDWG 将 DWG 转换为 DXF。
- 展开 INSERT 块引用。
- 导出几何 JSON。
- 生成预览 PNG。

禁止：

- 调用 DeepSeek。
- 执行 FreeCAD 建模。
- 根据业务模式决定是否允许多视图拉伸。

对接接口：

```python
parser = CADParser(file_path, config.get("dxf_parser", {}))
geometry_data = parser.parse()
parser.export_json(output_path)
parser.visualize(preview_path)
```

### 5.2 智能处理编排代理

允许：

- 组织本地视图初判、尺寸提取、LLM 视图语义校正和本地关系分析。
- 调用语义重建内核，获取语义裁决、零件语义和建模路径裁决。
- 读写分析缓存。
- 保存智能分析结果产物。
- 记录 LLM 遥测摘要。

禁止：

- 直接导出 STEP/STL/FCStd。
- 直接操作 GUI。
- 绕过视图结果校验执行 LLM 输出。

对接接口：

```python
analyzer = IntelligentEngineeringAnalyzer(api_key, api_config)
result = analyzer.analyze_full(geometry_data, extrude_height, file_path=file_path)
analyzer.save_results(result, output_dir, base_name)
```

### 5.3 LLM 视图校正代理

允许：

- 将本地规则结果、几何摘要和尺寸摘要发送给 DeepSeek。
- 解析 DeepSeek 返回的 JSON。
- 在校验失败或调用失败时回退本地规则结果。
- 可选读取预览图片并以多模态输入形式传递。

禁止：

- 输出完整思维链。
- 接受包含 `exec(`、`subprocess`、密钥文本等可疑内容的 LLM 视图结果。
- 直接生成 FreeCAD 脚本。

对接接口：

```python
view_result = LLMViewAnalyzer(api_key, api_config).refine_view_analysis(
    geometry_data=geometry_data,
    rule_result=rule_view_result,
    dimension_data=dimension_result,
    file_path=file_path,
)
```

### 5.4 建模指令生成代理

允许：

- 将几何数据、视图分析和尺寸结果发送给 DeepSeek。
- 生成 `analysis_summary`、`modeling_strategy`、`freecad_script`、`instructions`、`key_dimensions` 和 `warnings`。
- 根据 `llm_performance_mode` 控制 thinking 开关。
- 在需要语义重建时生成 FreeCAD 建模指令；若图纸被裁决为可平面拉伸图，则由智能模式选择对应执行路径。

禁止：

- 自行执行生成的脚本。
- 直接删除或覆盖用户文件。
- 将降级脚本伪装为可靠多视图建模脚本。

### 5.5 单文件处理代理

允许：

- 组合 CAD 解析、智能分析、通用建模和 AI 脚本执行。
- 组合 CAD 解析、智能处理编排、通用建模和 AI 脚本执行。
- 写入标准输出结构。
- 返回 `CADProcessResult`。

禁止：

- 修改配置文件中的密钥。
- 在未确认可靠脚本时处理多视图普通拉伸。
- 绕过 `CADFileManager` 自行创建不一致的输出目录结构。

### 5.6 FreeCAD 桥接代理

允许：

- 检测 direct/subprocess/unavailable 模式。
- 在 FreeCAD Python 中执行脚本。
- 解析桥接脚本的 `BRIDGE_*` 标记输出。
- 导出或收集 STEP/FCStd 产物。

禁止：

- 依赖系统 Python 直接 `import FreeCAD` 作为唯一方案。
- 在脚本中任意写入输出目录外的产物。
- 吞掉 FreeCAD 子进程错误。

### 5.7 缓存与遥测代理

允许：

- `AnalysisCache` 管理 `.cache/analysis` 下的 JSON 缓存。
- `preview_cache` 生成稳定预览路径。
- `LLMTelemetryStore` 记录 LLM 调用信息。
- GUI 或工具按明确文件路径删除缓存条目。

禁止：

- 使用递归批量删除命令清理缓存。
- 将缓存目录作为源码提交。
- 在遥测中写入完整密钥。

---

## 6. 对接接口速查

### 6.1 CLI

```powershell
python cad_cli.py --list
python cad_cli.py --file examples/cad_files/sample.dxf --height 10
python cad_cli.py --file examples/cad_files/sample.dxf --analysis
python cad_cli.py --file examples/cad_files/sample.dxf --intelligent
python cad_cli.py --file examples/cad_files/sample.dxf --analysis-only
python cad_cli.py --dir examples/cad_files --output-dir examples/output
```

### 6.2 批处理 API

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

config = load_config()
pipeline = CADPipeline(config=config, input_dir="examples/cad_files", output_dir="examples/output")

result = pipeline.process_file_basic("sample.dxf", extrude_height=10.0)
smart = pipeline.process_file_intelligent("sample.dxf", extrude_height=10.0)
batch = pipeline.process_directory_basic(extrude_height=10.0)
summary = pipeline.get_summary(batch)
```

### 6.3 缓存工具

```powershell
python tools/cache_tool.py stats
python tools/cache_tool.py clear-expired
python tools/cache_tool.py invalidate --file examples/cad_files/sample.dxf
python tools/cache_tool.py clear
```

### 6.4 导出诊断

```powershell
python tools/diagnose_export.py
```

---

## 7. 配置系统

### 7.1 配置优先级

```text
操作系统环境变量
  > 项目根目录 .env
  > config/config.yaml 或 config/config.example.yaml 字面值
```

`load_config()` 会递归解析 `${VAR}` 占位符。`config/config.yaml` 不存在时，会回退到 `config/config.example.yaml`。

### 7.2 关键环境变量

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
CAD_PREVIEW_CACHE_DIR=.cache/previews

# 可选：外部 LibreDWG 路径（项目已内置 tools/bin/dwg2dxf.exe）
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

### 7.3 DeepSeek 配置

```yaml
api:
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com"
    model: "deepseek-v4-pro"
    llm_performance_mode: "fast"
    llm_telemetry_dir: ".cache/llm_telemetry"
    thinking: true
    reasoning_effort: "max"
```

说明：

- `fast`、`latency`、`balanced` 模式会关闭 thinking。
- 需要深度建模时可使用 deep 类模式并启用 thinking。
- 不在文档、日志或配置模板中写真实 API Key。

---

## 8. 当前停用与兼容模块

| 模块 | 状态 | 处理方式 |
|---|---|---|
| `src/geometry_analyzer/GeometryAnalyzer` | 废弃兼容 | 新代码使用 `IntelligentEngineeringAnalyzer`；旧入口只作为兼容层 |
| `DXFParser` | 兼容别名 | 新代码使用 `CADParser` |
| 根目录旧示例脚本 | 已迁移 | 示例脚本放入 `examples/scripts/` |
| 根目录旧工具脚本 | 已迁移 | 工具脚本放入 `tools/` |

维护要求：

- 不为废弃模块新增业务功能。
- 修改公共导入时保留兼容别名，除非同步更新所有调用方和文档。
- 删除失效入口前先确认 `rg` 搜索无引用。

---

## 9. 安全与权限约束

### 9.1 文件删除约束

禁止批量删除文件或目录。

不要使用：

- `del /s`
- `rd /s`
- `rmdir /s`
- `Remove-Item -Recurse`
- `rm -rf`

需要删除文件时，只能一次删除一个明确路径的文件。

正确示例：

```powershell
Remove-Item -LiteralPath "C:\path\to\file.txt"
```

如果需要批量删除文件，应停止操作，并询问用户，让用户手动删除。

### 9.2 密钥与隐私

- `.env` 不应提交。
- 配置模板只允许 `${DEEPSEEK_API_KEY}` 等占位符。
- 日志脱敏是兜底措施，不能主动打印完整配置、请求头或密钥。
- 缓存、输出模型、日志和 LLM 遥测可能包含图纸结构信息，不应作为源码提交。

### 9.3 AI 脚本执行

- AI 生成脚本仍通过执行器运行，尚未实现强沙箱。
- 只能在可信环境中运行 AI 脚本。
- 后续安全增强方向是 API 白名单、输出目录限制和进程级隔离。

---

## 10. 开发与测试约定

### 10.1 编码约定

1. Python 文件第一行使用 `# -*- coding: utf-8 -*-`。
2. 路径、模型、超时、缓存目录和外部工具位置必须配置驱动。
3. 新增依赖时同步更新 `requirements.txt` 和 `pyproject.toml`。
4. 新增配置项时同步更新 `config/config.example.yaml` 和配置文档。
5. 日志失败用 `logger.error`，降级用 `logger.warning`，需要 traceback 时记录完整堆栈。
6. 核心边界优先返回 `Result[T]` 或明确结果对象。

### 10.2 测试命令

```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
```

常见手工验证：

```powershell
python cad_cli.py --list
python cad_cli.py --file examples/cad_files/sample.dxf --height 10
python tools/cache_tool.py stats
python tools/diagnose_export.py
```

---

## 11. 文档索引

| 文档 | 说明 |
|---|---|
| `README.md` | 项目总览和快速入口 |
| `CHANGELOG.md` | 版本变更记录 |
| `docs/requirements.md` | 需求规格说明书 |
| `docs/architecture.md` | 技术架构文档 |
| `docs/api/index.md` | API 与模块参考 |
| `docs/deployment.md` | 部署运维手册 |
| `docs/development.md` | 开发规范文档 |
| `docs/guides/getting_started.md` | 快速开始 |
| `docs/guides/configuration.md` | 配置与密钥管理 |
| `docs/guides/gui_guide.md` | GUI 使用指南 |
| `docs/modules/BATCH_MODULE_README.md` | 批处理模块说明 |
| `docs/modules/CACHE_README.md` | 缓存系统说明 |
| `docs/modules/INTELLIGENT_ANALYZER_README.md` | 智能分析模块说明 |

## Agent skills

### Issue tracker

本仓库的问题与 PRD 通过 GitHub Issues 管理。详见 `docs/agents/issue-tracker.md`。

### Triage labels

本仓库使用默认的分诊标签词表。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用单上下文布局。详见 `docs/agents/domain.md`。
