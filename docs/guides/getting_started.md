# 快速开始

版本：1.0.0
变更日期：2026-05-13
影响范围：安装、配置、测试、CLI、GUI

## 1. 准备环境

推荐使用已创建的 Conda 环境：

```powershell
conda activate cad_study
cd E:\Code\CAD
python --version
```

已验证环境：

- Python 3.11.15
- ezdxf 1.4.3
- pytest 9.0.3
- openai 2.26.0
- shapely 2.1.2
- scikit-learn 1.8.0
- PyYAML 6.0.3

在当前 PowerShell 中，如果 `conda run` 出现临时文件或 `chcp` 相关报错，可直接调用：

```powershell
D:\anaconda3\envs\cad_study\python.exe
```

## 2. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

或使用项目元数据安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

## 3. 配置 `.env`

复制模板：

```powershell
Copy-Item .env.example .env
```

填写：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key-here
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin

# 以下为可选配置
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

配置读取优先级：

1. 系统环境变量
2. `.env`
3. `config/config.yaml`

更多说明见 [配置与密钥管理](configuration.md)。

## 4. 运行测试

```powershell
D:\anaconda3\envs\cad_study\python.exe -m pytest tests\unit -q
```

当前单元测试验证结果：

```text
3 passed
```

`ezdxf/pyparsing` 可能输出弃用警告，不影响当前测试通过。

## 5. 启动 GUI

```powershell
D:\anaconda3\envs\cad_study\python.exe gui_example.py
```

GUI 支持：

- 扫描 `examples/cad_files`
- 预览 DXF/DWG 图纸
- 在兼容基础模式下设置拉伸高度
- 默认使用智能模式处理；必要时显式切换到兼容基础模式
- 输出 STEP/STL/FCStd 和预览 PNG

预览图保存位置：

```text
examples/output/<图纸名>/<图纸名>_preview.png
```

## 6. 使用 CLI

列出文件：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --list
```

默认智能重建模式：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples/cad_files/sample.dxf
```

显式兼容基础模式：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples/cad_files/sample.dxf --basic
```

仅分析不建模：

```powershell
D:\anaconda3\envs\cad_study\python.exe cad_cli.py --file examples/cad_files/sample.dxf --analysis-only
```

## 7. 常见问题

### 找不到 API Key

确认 `.env` 中存在：

```env
DEEPSEEK_API_KEY=...
```

并确认 `config/config.yaml` 使用：

```yaml
api:
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
```

### 找不到 FreeCAD

优先在 `.env` 设置：

```env
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

如果不设置，系统会尝试扫描 Windows 常见安装路径。

### DWG 转换失败

确认：

```env
# 项目已内置 LibreDWG 到 tools/bin/，无需配置
# LIBREDWG_PATH=D:\Code\libredwg-0.13.4.8160-win64
```

确认 `tools/bin/dwg2dxf.exe` 存在，或通过 `LIBREDWG_PATH` 指定外部 LibreDWG 路径。
