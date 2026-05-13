# AGENTS.md — CAD 图纸 3D 建模系统

> 面向 AI 编码助手的项目技术档案，包含架构、约定、已知问题和改进方向。

---

## 一、项目概述

这是一个 **CAD 二维图纸智能分析与三维重建系统**（毕业设计项目）。输入 DXF/DWG 二维工程图，通过 AI 分析视图和尺寸，自动生成 STEP/STL 格式的 3D 模型。

- **语言**：Python 3.10+
- **大模型**：DeepSeek V4 Pro（已从通义千问 Qwen 迁移）
- **建模引擎**：FreeCAD Python API
- **运行环境**：Windows（FreeCAD 必须在自带 Python 中运行）

---

## 二、技术栈

| 领域 | 技术 | 用途 |
|------|------|------|
| CAD 解析 | ezdxf + LibreDWG | 读取 DXF/DWG 文件，提取图元 |
| 几何计算 | Shapely | 空间索引（STRtree）、几何分析 |
| AI 分析 | DeepSeek V4 Pro (OpenAI SDK) | 视图识别、尺寸提取、建模脚本生成 |
| 3D 建模 | FreeCAD Python API | 实体建模、STEP/STL 导出 |
| 配置管理 | YAML | 统一配置文件 `config/config.yaml` |
| 日志 | logging | 文件 + 控制台双输出 |
| GUI | Tkinter + matplotlib | 图纸预览、参数调节、进度反馈 |

---

## 三、处理流水线

```
{dxf,dwg} ──▶ [cad_parser] ──▶ [geometry_analyzer] ──▶ [model_generator] ──▶ model.step
                       │                                      │
                       └──── [intelligent_analyzer] ◀─────────┘
                              (view_analyzer → dimension_extractor → modeling_generator)
```

### 3.1 两种运行模式

| 模式 | 触发方式 | 说明 |
|------|----------|------|
| **基础模式** | `cad_cli.py` 默认 | 图层规则拉伸，不需要 AI |
| **智能模式** | `cad_cli.py --intelligent` 或 `--analysis` | AI 驱动视图分析 + 尺寸提取 + 脚本生成 |

---

## 四、目录结构

```
E:\Code\CAD\
├── cad_cli.py                    # 统一命令行入口（已合并 A4）
├── process_my_cad.py             # 单文件处理入口
├── gui_example.py                # Tkinter GUI 入口
├── run_ai_script.py              # AI 脚本独立运行器
│
├── config/
│   ├── config.yaml               # 实际配置（含 API Key，不入版本控制）
│   └── config.example.yaml       # 配置模板
│
├── src/
│   ├── cad_parser/               # ① CAD 文件解析
│   │   └── parser.py             #    DXF 解析（ezdxf）+ DWG 转换（LibreDWG）
│   │
│   ├── geometry_analyzer/        # ② 几何分析
│   │   └── analyzer.py           #    STRtree 空间索引、几何关系分析
│   │
│   ├── intelligent_analyzer/     # ③ AI 智能分析
│   │   ├── pipeline.py           #    智能分析主流水线
│   │   ├── view_analyzer.py      #    视图分离（主/俯/侧视图）
│   │   ├── dimension_extractor.py#    尺寸标注提取
│   │   └── modeling_generator.py #    建模指令生成（调用 DeepSeek）
│   │
│   ├── model_generator/          # ④ 模型生成
│   │   ├── generator.py          #    模型生成协调器
│   │   ├── freecad_bridge.py     #    FreeCAD 子进程桥接
│   │   └── ai_script_runner.py   #    AI 脚本安全运行器
│   │
│   ├── batch_processor/          # ⑤ 批量处理
│   │   ├── pipeline.py           #    批量流水线
│   │   ├── processor.py          #    单文件处理器
│   │   └── file_manager.py       #    文件扫描与验证
│   │
│   └── utils/                    # ⑥ 工具层
│       ├── config.py             #    配置加载（环境变量优先）
│       ├── result.py             #    Result[T] 错误处理
│       ├── cache.py              #    分析结果缓存（.cache 目录）
│       └── logging.py            #    日志配置
│
├── examples/
│   ├── cad_files/                # 示例 CAD 文件
│   ├── output/                   # 输出产物目录
│   └── scripts/                  # 测试与示例脚本
│       ├── quickstart.py
│       ├── test_api.py
│       ├── test_config.py
│       ├── test_dwg_conversion.py
│       └── create_sample_dxf.py
│
├── tests/
│   └── unit/
│       └── test_parser.py        # 解析器单元测试
│
└── docs/                         # 文档
    ├── QUICKSTART_REFERENCE.md
    └── guides/
        ├── getting_started.md
        ├── gui_guide.md
        └── conda_setup.md
```

---

## 五、核心模块详解

### 5.1 cad_parser — CAD 文件解析

**入口**：[`parser.py`](src/cad_parser/parser.py)

- DXF 文件：直接用 ezdxf 解析
- DWG 文件：调用 LibreDWG 的 `dwg2dxf.exe` 转为 DXF 后解析
- DWG 转换路径从 `config.yaml` → `dxf_parser.libredwg_path` 读取
- 返回 `Result[Dict[str, Any]]`

### 5.2 geometry_analyzer — 几何分析

**入口**：[`analyzer.py`](src/geometry_analyzer/analyzer.py)

- 使用 Shapely STRtree 进行 O(n log n) 空间索引
- 分析图元间的碰撞、包含、邻接关系
- 返回 `Result[Dict[str, Any]]`

### 5.3 intelligent_analyzer — AI 智能分析

**入口**：[`pipeline.py`](src/intelligent_analyzer/pipeline.py)

- 三步流水线：视图分析 → 尺寸提取 → 建模指令生成
- 通过 OpenAI SDK 调用 DeepSeek V4 Pro API
- 思考模式通过 `extra_body={"thinking": {"type": "enabled", "reasoning_effort": "max"}}` 启用
- 返回 `Result[Dict[str, Any]]`

### 5.4 model_generator — 模型生成

**入口**：[`generator.py`](src/model_generator/generator.py)

- [freecad_bridge.py](src/model_generator/freecad_bridge.py)：通过子进程调用 FreeCAD 内置 Python 执行脚本
- [ai_script_runner.py](src/model_generator/ai_script_runner.py)：安全执行 AI 生成的建模脚本
- FreeCAD 路径从 `config.yaml` → `freecad.bin_path` 读取
- 支持直接模式（项目 Python = FreeCAD Python）和子进程模式
- 输出：STEP、STL、FCStd

### 5.5 batch_processor — 批量处理

**入口**：[`pipeline.py`](src/batch_processor/pipeline.py)

- 扫描目录 → 验证文件 → 逐个处理 → 汇总报告
- `CADProcessResult` dataclass 承载每个文件的处理结果

### 5.6 utils — 工具层

| 文件 | 核心职责 |
|------|----------|
| [`config.py`](src/utils/config.py) | 配置加载：环境变量 → config.yaml → 自动发现 |
| [`result.py`](src/utils/result.py) | Rust 风挌 `Result[T]` 泛型类 |
| [`cache.py`](src/utils/cache.py) | 分析结果缓存（`AnalysisCache`），非 `Result[T]` 风格 |
| [`logging.py`](src/utils/logging.py) | `setup_logging()` 统一日志配置 |

---

## 六、配置系统

### 6.1 配置优先级

```
环境变量 (CAD_PROJECT_ROOT, CAD_CONFIG_PATH)
    ↑
config/config.yaml
    ↑
代码内默认值
```

### 6.2 API 配置（DeepSeek V4 Pro）

```yaml
api:
  deepseek:
    api_key: "sk-xxx"
    base_url: "https://api.deepseek.com"
    model: "deepseek-v4-pro"
    max_tokens: 4096
    max_prompt_tokens: 12000
    thinking: true
    reasoning_effort: "max"  # high(默认) / max(最大思考强度)
```

### 6.3 外部工具路径

```yaml
dxf_parser:
  libredwg_path: "D:\\Code\\libredwg-0.13.4.8160-win64"

freecad:
  bin_path: "D:\\FreeCAD 1.0\\bin"
```

---

## 七、错误处理约定

### 7.1 Result[T] 模式

项目采用 **Rust 风格 Result[T]** 统一错误处理，不允许抛出原始异常：

```python
from src.utils import Result

def my_function() -> Result[Dict]:
    try:
        data = do_something()
        return Result.Ok(data)
    except Exception as e:
        return Result.Err(f"操作失败: {e}")
```

核心 API：
- `Result.Ok(value)` — 成功
- `Result.Err(error_str)` — 失败
- `result.is_ok` / `result.is_err` — 状态检查
- `result.unwrap()` — 取值（失败时抛 RuntimeError）
- `result.unwrap_or(default)` — 取值或默认值
- `result.map(fn)` — 成功时映射
- `result.and_then(fn)` — 链式调用

### 7.2 已知不足

- **无错误码体系**：所有错误统一为字符串，无法分类处理
- **缺少结构化上下文**：无时间戳、无 traceback 保留、无 HTTP 状态码
- **`except Exception` 过于宽泛**：API 速率限制、连接错误等未区分
- **cache.py 不一致**：`get()` 返回 `Optional`，`set()` 返回 `bool`，未采用 `Result[T]`

---

## 八、已知问题与改进方向

### 8.1 硬编码路径残留

| 严重度 | 位置 | 内容 |
|--------|------|------|
| 高 | `run_with_freecad.bat:L24-L27` | 四个 FreeCAD 安装绝对路径 |
| 中 | `cad_cli.py:L113-L116` | argparse 默认值 `"examples/cad_files"` 等 |
| 中 | `gui_example.py`（6 处） | 同上 |
| 中 | 若干入口脚本 | 固定的相对路径字符串 |

### 8.2 FreeCAD 运行限制

- FreeCAD 必须在自带的 Python 中运行（有独立的包管理器）
- 项目中 `import FreeCAD` 是 stub import，仅用于类型提示
- 实际建模通过子进程调用 FreeCAD 的 Python 执行

### 8.3 安全注意事项

- `exec()` 执行 AI 生成代码时无沙箱，存在风险
- API Key 存储在 `config/config.yaml` 中，需确保不提交到版本控制

### 8.4 性能优化空间

- 几何分析已优化至 O(n log n)（STRtree），这是正确的
- AI 分析有缓存机制，避免重复调用

---

## 九、常用命令

```bash
# 基础模式 — 处理单个 CAD 文件
python cad_cli.py examples/cad_files/sample.dxf

# 智能模式 — AI 分析 + 建模
python cad_cli.py examples/cad_files/sample.dxf --intelligent

# 仅分析（不建模）
python cad_cli.py examples/cad_files/sample.dxf --analysis-only

# 指定输出目录
python cad_cli.py examples/cad_files --mode batch --output-dir output/my_project

# 运行 GUI
python gui_example.py

# 测试 API 连接
python examples/scripts/test_api.py
```

---

## 十、编码约定

1. **注释规范**：代码中需要写注释，说明关键逻辑、参数含义、返回值等
2. **Result[T] 强制**：所有核心模块函数返回 `Result[T]`，不抛异常
3. **配置驱动**：路径、API 参数等从 `config.yaml` 读取，不用硬编码
4. **路径优先级**：环境变量 → config.yaml → 自动发现
5. **日志规范**：`logger.error` 用于最终失败，`logger.warning` 用于降级，`logger.exception` 用于记录完整 traceback
6. **Python 文件头**：`# -*- coding: utf-8 -*-` 在第一行

---

## 十一、依赖

核心依赖（见 `requirements.txt`）：
- `ezdxf` — DXF 文件解析
- `shapely` — 计算几何
- `openai` — DeepSeek API 调用
- `pyyaml` — 配置文件解析
- `matplotlib` — 图纸预览
- `numpy` — 数值计算

外部工具依赖：
- **LibreDWG** — DWG 转 DXF（`dwg2dxf.exe`）
- **FreeCAD** — 3D 建模引擎
