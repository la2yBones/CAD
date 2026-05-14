# 文档更新清单

## 文档覆盖清单

| 文档 | 类型 | 更新内容 | 更新原因 |
|---|---|---|---|
| `README.md` | 项目总览 | 重写项目介绍、技术栈、目录结构、运行命令、模式说明和文档入口 | 修复乱码和旧模型描述，对齐 DeepSeek、GUI、缓存和遥测现状 |
| `CHANGELOG.md` | 变更日志 | 重建 2.0.0 和 1.0.0 变更记录 | 去除乱码，补齐最近迭代中的智能分析、GUI、缓存和文档变更 |
| `docs/requirements.md` | 需求规格说明书 | 新增用户角色、功能需求、非功能需求、输入输出和限制 | 原项目缺少独立需求规格文档 |
| `docs/architecture.md` | 技术架构文档 | 新增总体架构、模块职责、数据结构、FreeCAD 模式、缓存和安全边界 | 原项目缺少独立架构文档 |
| `docs/api/index.md` | 接口 API 文档 | 更新 `CADParser`、`CADPipeline`、智能分析、FreeCAD、缓存和 CLI 参数 | 对齐当前类名、返回结构和新增 LLM 遥测接口 |
| `docs/deployment.md` | 部署运维手册 | 新增环境要求、安装、配置、启动、输出、运维检查和故障处理 | 原项目缺少部署运维文档 |
| `docs/development.md` | 开发规范文档 | 新增编码、术语、配置、模块边界、测试、安全和文档同步规范 | 原项目缺少开发规范文档 |
| `docs/guides/getting_started.md` | 用户使用指南 | 更新安装、`.env`、CLI、GUI、输出路径和常见问题 | 修正旧命令和旧预览路径描述 |
| `docs/guides/configuration.md` | 配置指南 | 更新 DeepSeek、LLM 性能模式、遥测、多模态、预览缓存和兼容性 | 对齐 `config.example.yaml` 与 `src/utils/config.py` |
| `docs/guides/gui_guide.md` | GUI 指南 | 更新 v2.0 GUI、日志面板、缓存面板、AI 调用监控和 STEP 预览 | 对齐增强版 `gui_example.py` |
| `docs/guides/conda_setup.md` | 环境指南 | 更新依赖范围、外部工具和测试命令 | 对齐 `requirements.txt` 与 `pyproject.toml` |
| `docs/QUICKSTART_REFERENCE.md` | 快速参考 | 重写命令、输出和排查速查 | 删除过时 API Key 明文示例和旧路径 |
| `docs/modules/BATCH_MODULE_README.md` | 模块文档 | 更新批处理职责、API、输出结构和多视图保护 | 对齐 `CADPipeline` 与 `CADProcessor` 当前实现 |
| `docs/modules/CACHE_README.md` | 模块文档 | 更新分析缓存、预览缓存、LLM 遥测、GUI 集成和清理策略 | 对齐 `AnalysisCache` 与 `tools/cache_tool.py` |
| `docs/modules/INTELLIGENT_ANALYZER_README.md` | 模块文档 | 更新 DeepSeek 管道、Schema 校验、缓存、遥测和安全限制 | 替换旧智能分析流程描述 |
| `thesis/毕业论文.md` | 论文稿 | 更新摘要、技术路线、模块实现、测试分析和展望 | 删除 Qwen/DashScope 过时描述，对齐当前 DeepSeek 架构 |

## 链接与资源校验结果

| 校验项 | 结果 |
|---|---|
| Markdown 文件数 | 19 |
| Markdown 链接数 | 27 |
| 图片资源引用数 | 0 |
| 缺失链接 | 0 |
| 过时术语扫描 | 未发现 Qwen、通义、DashScope、旧 `--out` 参数、旧日期字段或明文密钥示例 |
| 单元测试 | `D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q` 通过，5 passed |

## 术语统一

| 旧表述 | 统一表述 |
|---|---|
| 通义千问 / Qwen / DashScope | DeepSeek V4 Pro |
| AI 几何分析 | 智能分析 |
| DXFParser 主类 | CADParser |
| 临时预览图 | 预览缓存 |
| AI 调用日志 | LLM 遥测 / AI 调用监控 |
| 普通拉伸 | 基础模式 / 通用建模器 |
