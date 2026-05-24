# 开发规范文档

## 1. 编码约定

- Python 文件第一行使用 `# -*- coding: utf-8 -*-`。
- 核心模块优先返回 `Result[T]` 或明确结果对象，不在业务边界抛出原始异常。
- 关键逻辑写必要中文注释，避免无意义注释。
- 路径、模型、超时、缓存目录和外部工具位置必须配置驱动。
- 日志使用 `logging`，最终失败用 `logger.error`，降级用 `logger.warning`，需要 traceback 时用 `logger.exception` 或显式记录 traceback。

## 2. 命名与术语

| 统一术语 | 说明 |
|---|---|
| CAD 解析 | DXF/DWG 到结构化几何数据 |
| 智能处理 | 面向用户的统一处理入口，先完成图纸理解，再选择建模路径 |
| 智能分析 | 视图、尺寸、关系、语义裁决和建模路径裁决的 AI/规则混合分析 |
| 平面拉伸路径 | 智能处理内部的低复杂度专用建模路径 |
| 语义重建路径 | 无法稳定归入专用路径时使用的兜底建模路径 |
| 预览缓存 | 图纸 PNG 预览缓存，不等同分析缓存 |
| 分析缓存 | 智能分析结果缓存 |
| LLM 遥测 | 大模型调用指标记录 |

## 3. 配置规范

- 新增配置优先放入 `config/config.example.yaml`，并在 `docs/guides/configuration.md` 说明。
- 密钥类配置必须使用 `${VAR}` 占位符，不写真实值。
- 新增环境变量同步更新 `.env.example`。
- 新增依赖同步更新 `requirements.txt` 和 `pyproject.toml`。

## 4. 模块边界

| 模块 | 边界 |
|---|---|
| `cad_parser` | 只负责读取和标准化几何，不做业务建模决策 |
| `intelligent_analyzer` | 负责智能分析编排，不直接导出模型文件 |
| `reconstruction` | 负责语义裁决、零件语义、建模路径裁决和建模任务载荷 |
| `model_generator` | 负责 AI 脚本执行和 FreeCAD 桥接 |
| `batch_processor` | 负责文件处理编排、输出结构、状态转换和结果汇总 |
| `utils` | 只放跨模块通用能力 |
| `gui_example.py` | 只编排 GUI 交互，不复制核心处理逻辑 |
| `compat` / `legacy` | 仅承接旧导入路径和旧执行路径，新代码不应新增依赖 |

## 5. 测试规范

```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
```

新增功能建议：

- 解析器新增实体类型时补充单元测试。
- 智能分析 Schema 或回退逻辑变化时补充 `tests/unit/test_view_analysis.py`。
- 缓存删除、失效逻辑变化时使用单文件明确路径验证，避免递归删除。
- FreeCAD 导出相关变更可使用 `tools/diagnose_export.py` 手工验证。

## 6. 安全规范

- 禁止提交真实 API Key、`.env`、输出模型、缓存和日志。
- 不使用批量删除命令；需要删除文件时一次只删除一个明确文件路径。
- AI 生成脚本执行前保持可信输入假设，并逐步推进白名单 API、输出目录限制和沙箱隔离。
- 日志脱敏是兜底措施，不应主动记录完整配置或请求头。

## 7. 文档同步规范

以下变更必须同步文档：

- CLI 参数或 GUI 操作流程变化。
- 配置项、环境变量或依赖版本变化。
- 模块公开类、函数、返回结构变化。
- 输出目录、缓存目录或文件命名变化。
- AI 模型、base_url、thinking 参数或遥测字段变化。
