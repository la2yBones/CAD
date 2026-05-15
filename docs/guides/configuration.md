# 配置与密钥管理

版本：1.0.0
变更日期：2026-05-13
影响范围：`config/config.yaml`、`config/config.example.yaml`、`.env.example`、`src/utils/config.py`、`src/utils/logging.py`

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
| `api.deepseek.api_key` | `${DEEPSEEK_API_KEY}` | 智能分析调用 DeepSeek API | 智能模式必需 |
| `api.deepseek.base_url` | YAML | DeepSeek API 地址 | 智能模式必需 |
| `api.deepseek.model` | YAML | 模型名称，默认 `deepseek-v4-pro` | 智能模式必需 |
| `dxf_parser.libredwg_path` | `${LIBREDWG_PATH}` | DWG 转 DXF 工具路径（可选） | DWG 转换外部覆盖 |
| `dxf_parser.output_dir` | YAML | CAD 预览图默认输出目录 | 可选 |
| `dxf_parser.overlay_dimension_text` | YAML，默认 `auto` | DIMENSION 匿名块文字补绘策略，支持 `auto`、`true`、`false` | 可选 |
| `dxf_parser.dimension_text_auto_overlay_ratio` | YAML，默认 `0.008` | `auto` 模式下按图幅跨度计算补绘阈值 | 可选 |
| `dxf_parser.dimension_text_auto_overlay_min_height` | YAML，默认 `1.5` | `auto` 模式下最小补绘阈值 | 可选 |
| `freecad.bin_path` | `${FREECAD_BIN_PATH}` | FreeCAD `bin` 目录 | 建模推荐配置 |
| `modeling.export_formats` | YAML | 导出格式 | 可选 |
| `cache.cache_dir` | YAML | 分析缓存目录 | 可选 |
| `logging.file` | YAML | 日志文件路径 | 可选 |

## 日志脱敏

`setup_logging()` 会自动添加 `SensitiveDataFilter`，降低敏感信息进入控制台和日志文件的风险。

当前脱敏模式：

- `sk-` 开头的长密钥
- `api_key=...`
- `token=...`

注意：脱敏是兜底措施。开发时仍应避免直接打印完整配置字典、请求头、`.env` 内容或异常上下文中的敏感字段。

## FreeCAD 自动发现

`FreeCADBridge` 的查找顺序：

1. 当前 Python 是否为 FreeCAD Python，若是则使用 direct 模式。
2. 配置中的 `freecad.bin_path`，通常来自 `FREECAD_BIN_PATH`。
3. Windows 常见安装位置自动扫描，例如 `C:\Program Files\FreeCAD 1.0\bin\python.exe`。

如果自动发现失败，请显式设置：

```env
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

## 兼容性影响

- 旧版直接在 `config.yaml` 写入 API Key 的方式仍可作为 YAML 字面值回退，但不推荐。
- 使用 `${VAR}` 后，部署环境必须确保变量存在，否则智能模式会因无有效 API Key 失败。
- `.env` 解析器是轻量实现，支持简单 `KEY=VALUE`，不支持复杂 shell 表达式。
