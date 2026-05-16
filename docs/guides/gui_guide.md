# GUI 使用指南

版本：1.0.0
变更日期：2026-05-13
影响范围：`gui_example.py`、CAD 预览输出、配置说明

## 启动

```powershell
conda activate cad_study
cd E:\Code\CAD
D:\anaconda3\envs\cad_study\python.exe gui_example.py
```

GUI 默认扫描 `examples/cad_files`，输出写入 `examples/output`。

## 主要功能

| 区域 | 功能 |
|---|---|
| 左侧控制区 | 选择目录、刷新列表、预览选中文件、选择处理模式 |
| 右侧预览区 | 显示 CAD 图纸 PNG 预览 |
| 底部日志区 | 显示处理进度、错误信息、输出目录 |

## 预览行为

预览逻辑已调整为稳定文件输出，不再使用临时文件。

输出路径：

```text
examples/output/<图纸名>/<图纸名>_preview.png
```

影响：

- 预览图可复用，便于调试和文档引用。
- 不再调用 `plt.show()`，可在无头服务器或 CI 环境中生成预览。
- 如果解析到 0 个实体，GUI 会记录提示并停止预览生成，避免空图覆盖有效缓存。

## 基础处理流程

1. 启动 GUI。
2. 在文件列表中选择或双击图纸。
3. 点击“预览选中”生成/查看预览图。
4. 智能模式默认开启“逐阶段确认”；仅在兼容基础模式下设置拉伸高度。
5. 点击“开始处理”。
6. 查看底部日志和输出目录。

## 智能分析模式

勾选“启用 AI 智能分析”前，请确认 `.env` 中存在：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
```

智能模式会使用 DeepSeek 相关配置。兼容基础模式不需要 API Key，但只适合作为单轮廓平面拉伸兼容入口。

## 逐阶段确认

GUI 单图纸智能处理默认开启“逐阶段确认”。开启后，系统会在以下大模型阶段完成后停止并显示汇报：

1. 视图语义校正。
2. 零件语义重建。

汇报窗口使用“停止 / 继续”表示当前分支：继续会放行下一阶段，停止会结束本次处理。如果继续后马上需要追问补充信息，系统会先在汇报中提示，然后再显示追问窗口。追问窗口仍负责收集补充信息；阶段汇报只负责审阅和分流。

关闭“逐阶段确认”后，智能模式会按原流程自动完成分析、建模指令生成和 AI 脚本执行。

## 常见问题

### 预览失败

检查：

- `matplotlib` 已安装。
- `ezdxf` 已安装。
- DWG 文件默认使用项目内置 `tools/bin/dwg2dxf.exe`，也可通过 `LIBREDWG_PATH` 指定外部路径。

### FreeCAD 不可用

设置：

```env
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

如果未设置，系统会尝试自动扫描常见 Windows 安装目录。

### 日志中是否会泄露密钥

`setup_logging()` 已添加 `SensitiveDataFilter`，会脱敏常见 API Key 和 token 模式。但不要主动打印 `.env`、完整配置对象或请求头。
