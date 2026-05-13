# Conda 环境配置指南

版本：1.0.0
变更日期：2026-05-13
影响范围：开发环境、测试命令、依赖安装

## 推荐环境

项目推荐使用 `cad_study`：

```powershell
conda activate cad_study
cd E:\Code\CAD
python --version
```

当前已验证：

```text
Python 3.11.15
```

关键包版本：

| 包 | 已验证版本 |
|---|---:|
| ezdxf | 1.4.3 |
| pytest | 9.0.3 |
| openai | 2.26.0 |
| shapely | 2.1.2 |
| scikit-learn | 1.8.0 |
| PyYAML | 6.0.3 |

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

开发模式：

```powershell
python -m pip install -e ".[dev]"
```

## 运行测试

```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
```

当前验证结果：

```text
3 passed
```

## `conda run` 注意事项

在当前 Windows shell 中，`conda run -n cad_study ...` 可能出现临时文件占用或 `chcp` 不可用相关报错。为了稳定执行，建议直接使用环境内解释器：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --list
D:\anaconda3\envs\cad_study\python.exe gui_example.py
```

## 配置外部工具

复制 `.env.example`：

```powershell
Copy-Item .env.example .env
```

填写：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

## 建议工作流

1. 激活 `cad_study`。
2. 修改代码前运行单元测试。
3. 修改依赖时同步更新 `requirements.txt` 和 `pyproject.toml`。
4. 修改配置行为时同步更新 `docs/guides/configuration.md`。
5. 提交前确认 `.env` 未进入版本控制。
