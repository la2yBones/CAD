# 更新日志

## 1.0.0 - 2026-05-13

变更类型：安全修复、架构优化、工程基础设施、GUI/预览修复、文档同步
影响范围：配置加载、日志输出、FreeCAD 检测、CAD 预览、依赖安装、开发者上手流程

### 安全修复

- 将 DeepSeek API Key 从 `config/config.yaml` 移出，改为在 `.env` 中设置 `DEEPSEEK_API_KEY`，配置文件仅保留 `${DEEPSEEK_API_KEY}` 占位符。
- 新增 `SensitiveDataFilter`，对日志中的 `sk-*`、`api_key=*`、`token=*` 等常见敏感信息进行脱敏。
- `.gitignore` 新增 `.env`、`.env.*` 忽略规则，并显式保留 `.env.example`。

### 架构优化

- `src/utils/config.py` 支持 `.env` 读取和 `${VAR}` 占位符解析，配置优先级为：操作系统环境变量 > `.env` 文件 > YAML 字面值。
- `src/model_generator/freecad_bridge.py` 移除固定 FreeCAD 绝对路径列表，改为通过 `_find_freecad_candidates()` 自动扫描常见安装位置，并支持 `FREECAD_BIN_PATH` 显式配置。
- 新增 `src/utils/result.py`，提供泛型 `Result[T]`、`ok()`、`fail()`、`unwrap_or()`、`map()` 等统一错误处理接口。
- 新增 `pyproject.toml`，统一项目元数据、依赖版本范围、pytest、coverage、ruff 和 mypy 配置。

### 功能修复

- `src/cad_parser/parser.py` 新增 `output_dir` 配置，`visualize()` 未传入输出路径时自动保存到输出目录。
- `src/cad_parser/parser.py` 移除 `plt.show()` 依赖，避免无头服务器或 CI 环境中预览失败。
- `gui_example.py` 移除临时文件预览，改为保存到 `examples/output/<图纸名>/<图纸名>_preview.png`，与流水线输出结构保持一致。
- `gui_example.py` 在解析到 0 个实体时直接返回，避免生成无效空预览图。
- `gui_example.py` 新增默认开启的“逐阶段确认”，在视图语义校正和零件语义重建完成后展示阶段汇报，用户点击“继续”后再进入后续阶段或追问窗口。

### 依赖更新

- `pyproject.toml` 和 `requirements.txt` 依赖范围同步为当前 DeepSeek/OpenAI SDK 实现：`openai`、`ezdxf`、`shapely`、`pyyaml`、`json5`、`matplotlib`、`numpy`、`scikit-learn`、`typing-extensions`。
- 移除与当前代码路径不一致的 `dashscope` 依赖声明。
- 开发依赖覆盖 `pytest`、`pytest-cov`、`ruff`、`mypy`、`black`、`flake8`。

### 影响评估

- 现有基础模式不需要 API Key，仍可解析 DXF/DWG 并生成模型。
- 智能模式需要 `.env` 或操作系统环境变量中存在有效 `DEEPSEEK_API_KEY`。
- 日志中打印密钥的风险降低，但仍建议不要主动记录完整配置对象。
- FreeCAD 自动发现降低了新机器配置成本；如果自动发现失败，应在 `.env` 中设置 `FREECAD_BIN_PATH`。
- 预览图路径稳定后，GUI 可复用已有预览缓存，减少重复渲染。

### 已知风险

- AI/FreeCAD 脚本执行仍依赖 `exec()`，需要后续引入更严格的脚本沙箱与 API 白名单。
- `.env` 解析器是轻量实现，不支持复杂 shell 展开语法。
- FreeCAD 自动扫描优先覆盖 Windows 常见路径，跨平台部署仍建议显式配置。
