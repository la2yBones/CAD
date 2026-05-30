# 配置与密钥管理

## 配置优先级

项目通过 `load_config()` 加载 YAML，并解析 `${VAR}` 占位符。优先级从高到低为：

1. 操作系统环境变量
2. 项目根目录 `.env`
3. YAML 文件中的字面值

示例：

```yaml
api:
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
```

如果系统环境变量中设置了 `DEEPSEEK_API_KEY`，则优先使用系统环境变量；否则读取 `.env`；如果两者都不存在，则保留 YAML 字面值。

## `.env` 文件

复制模板：

```powershell
Copy-Item .env.example .env
```

填写真实值：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin

# 以下为可选配置（项目已内置）
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

安全要求：

- `.env` 已加入 `.gitignore`，不要提交。
- `.env.example` 必须保留在版本控制中，作为团队配置模板。
- 不要在日志、截图、论文附录或提交说明中暴露真实密钥。

## 关键配置项

| 配置项 | 来源 | 作用 | 必需性 |
|---|---|---|---|
| `api.deepseek.api_key` | `${DEEPSEEK_API_KEY}` | 智能处理调用 DeepSeek API | 统一智能处理必需 |
| `api.deepseek.base_url` | YAML | DeepSeek API 地址 | 统一智能处理必需 |
| `api.deepseek.model` | YAML | 模型名称，默认 `deepseek-v4-pro` | 统一智能处理必需 |
| `api.deepseek.view_model` | YAML | 视图语义校正阶段模型，默认与主模型一致使用 `deepseek-v4-pro` | 可选 |
| `api.deepseek.semantic_adjudication_model` | YAML | 图纸语义裁决阶段模型；未配置时回退 `semantic_model` 或 `model` | 可选 |
| `api.deepseek.semantic_model` | YAML | 零件语义生成阶段模型 | 可选 |
| `api.deepseek.front_stage_api_key` | `${MOONSHOT_API_KEY}` | 可选前置阶段 API Key；用于把视图语义校正和图纸语义裁决切到 Kimi 等多模态模型 | 可选 |
| `api.deepseek.front_stage_base_url` | YAML | 可选前置阶段 API 地址；Kimi K2.6 使用 `https://api.moonshot.cn/v1` | 可选 |
| `api.deepseek.front_stage_provider` | YAML | 可选前置阶段提供方；Kimi K2.6 填 `moonshot` | 可选 |
| `api.deepseek.enable_multimodal_front_stage_input` | YAML | 为视图语义校正和图纸语义裁决附带 CAD 预览图 data URL | 可选 |
| `api.deepseek.user_id` | YAML | DeepSeek 内容安全、调度和 KVCache 隔离标识；不要使用个人隐私信息 | 可选 |
| `api.deepseek.request_timeout_seconds` | YAML | OpenAI SDK 请求超时秒数，避免长时间无反馈 | 可选 |
| `api.deepseek.stage_thinking` | YAML | 按阶段控制 DeepSeek thinking；`reasoning_effort` 仅使用 `high` 或 `max` | 可选 |
| `api.deepseek.llm_telemetry_dir` | YAML | LLM 调用 JSONL 遥测目录，记录耗时、token 和上下文缓存命中情况 | 可选 |
| `dxf_parser.libredwg_path` | `${LIBREDWG_PATH}` | DWG 转 DXF 工具路径（可选） | DWG 转换外部覆盖 |
| `dxf_parser.output_dir` | YAML | CAD 预览图默认输出目录 | 可选 |
| `dxf_parser.overlay_dimension_text` | YAML，默认 `auto` | DIMENSION 匿名块文字补绘策略，支持 `auto`、`true`、`false` | 可选 |
| `dxf_parser.dimension_text_auto_overlay_ratio` | YAML，默认 `0.008` | `auto` 模式下按图幅跨度计算补绘阈值 | 可选 |
| `dxf_parser.dimension_text_auto_overlay_min_height` | YAML，默认 `1.5` | `auto` 模式下最小补绘阈值 | 可选 |
| `dxf_parser.dimension_text_auto_overlay_fontsize` | YAML，默认 `10.0` | `auto` 模式下补绘过小尺寸文字时使用的最小字号 | 可选 |
| `dxf_parser.preview_annotation_color` | YAML，默认 `7` | CAD 预览中统一文字与尺寸标注颜色，避免同一图纸出现粉色/白色混用 | 可选 |
| `freecad.bin_path` | `${FREECAD_BIN_PATH}` | FreeCAD `bin` 目录 | 建模推荐配置 |
| `modeling.export_formats` | YAML | 导出格式 | 可选 |
| `cache.cache_dir` | YAML | 分析缓存目录 | 可选 |
| `logging.file` | YAML | 日志文件路径 | 可选 |

## 日志脱敏

`api.deepseek.stage_thinking` 当前覆盖四个大模型调用阶段：`view_analysis`（视图语义校正）、`semantic_adjudication`（图纸语义裁决）、`semantic_generation`（零件语义重建）和 `modeling_generation`（建模指令生成）。默认均关闭 thinking，需要更强语义判断时再按阶段开启。系统默认统一使用 `deepseek-v4-pro`，但各阶段仍保持独立 JSON 请求，跨阶段连续性由本地结构化结果承接。

若只希望把前置图纸理解切换到 Kimi K2.6 多模态，可保留 `api.deepseek.api_key/base_url/model/semantic_model` 给后续语义生成和建模脚本生成使用，并添加：

```yaml
api:
  deepseek:
    front_stage_api_key: "${MOONSHOT_API_KEY}"
    front_stage_provider: "moonshot"
    front_stage_base_url: "https://api.moonshot.cn/v1"
    view_model: "kimi-k2.6"
    semantic_adjudication_model: "kimi-k2.6"
    enable_multimodal_front_stage_input: true
```

处理流程会把已生成的 CAD 预览 PNG 作为 `image_url` data URL 附带给视图语义校正和图纸语义裁决阶段。

GUI 的“设置 -> 运行配置”中可填写 `DeepSeek API Key` 和 `Kimi/Moonshot API Key`；“设置 -> 大模型”中可配置默认模型、前置阶段提供方、前置阶段 Base URL、前置多模态开关，以及视图校正、图纸语义裁决、零件语义重建的分阶段模型。

`setup_logging()` 会自动添加 `SensitiveDataFilter`，降低敏感信息进入控制台和日志文件的风险。

当前脱敏模式：

- `sk-` 开头的长密钥
- `api_key=...`
- `token=...`

注意：脱敏是兜底措施。开发时仍应避免直接打印完整配置字典、请求头、`.env` 内容或异常上下文中的敏感字段。

## FreeCAD 自动发现

`FreeCADBridge` 的查找顺序：

1. 当前 Python 是否为 FreeCAD Python，若是则使用 direct 模式。
2. 项目级 FreeCAD 增强包：`tools/freecad/*/bin/python.exe`。
3. 配置中的 `freecad.bin_path`，通常来自 `FREECAD_BIN_PATH`。
4. Windows 常见安装位置自动扫描，例如 `C:\Program Files\FreeCAD 1.0\bin\python.exe`。

如果希望获得接近内置的自动建模体验，可以下载 FreeCAD 便携包并解压为：

```text
tools/freecad/FreeCAD-1.0.x/bin/python.exe
```

仓库只提交 `tools/freecad/README.md` 和占位文件，不提交完整 FreeCAD 本体。

如果自动发现失败，请显式设置：

```env
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

## 兼容性影响

- 旧版直接在 `config.yaml` 写入 API Key 的方式仍可作为 YAML 字面值回退，但不推荐。
- 使用 `${VAR}` 后，部署环境必须确保变量存在，否则统一智能处理会因无有效 API Key 失败。
- `.env` 解析器是轻量实现，支持简单 `KEY=VALUE`，不支持复杂 shell 表达式。
