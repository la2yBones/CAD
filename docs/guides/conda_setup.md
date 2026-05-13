# Conda 环境配置指南

本指南将帮助您在 `cad_study` conda 环境中配置和运行 CAD 建模系统。

## 1. 激活 Conda 环境

首先，确保您已经激活了 `cad_study` 环境：

```bash
# Windows
conda activate cad_study

# Linux/Mac
source activate cad_study
```

验证环境是否激活：
```bash
conda info --envs
```

您应该看到 `cad_study` 旁边有一个星号 `*`。

## 2. 安装项目依赖

在项目根目录下，安装所需的 Python 包：

```bash
cd e:\Code\CAD
pip install -r requirements.txt
```

### requirements.txt 包含的主要依赖：

- **ezdxf** - DXF 文件解析库
- **openai** - OpenAI API 客户端（兼容 DeepSeek API）
- **shapely** - 几何计算库
- **numpy** - 数值计算库
- **pyyaml** - YAML 配置文件解析
- **matplotlib** - 可视化（可选）
- **pytest** - 测试框架（可选）

## 3. 验证 Python 版本

确保您使用的是 Python 3.10 或更高版本：

```bash
python --version
# 或在 conda 环境中
python --version
```

## 4. 配置环境变量（可选但推荐）

将 FreeCAD 和 LibreDWG 路径添加到环境变量中，方便系统查找：

### Windows 临时设置（当前终端会话有效）：

```bash
# 注意：根据您的实际路径调整
set PATH=D:\FreeCAD 1.0\bin;%PATH%
```

### 永久设置（推荐在项目脚本中处理）：

我们的代码已经自动处理了 FreeCAD 路径配置，所以您只需要确保 `config/config.yaml` 中的路径设置正确即可。

## 5. 运行配置测试

现在让我们测试环境是否配置正确：

```bash
# 首先激活 conda 环境
conda activate cad_study

# 然后进入项目目录
cd e:\Code\CAD

# 运行配置测试脚本
python examples\scripts\test_config.py
```

## 6. 测试 DeepSeek API

配置文件 `config/config.yaml` 已经包含了您的 API 密钥，让我们测试一下：

```bash
# 确保 conda 环境已激活
conda activate cad_study

cd e:\Code\CAD
python examples\scripts\test_api.py
```

## 7. 完整测试流程

如果所有测试通过，让我们运行完整的示例：

```bash
# 1. 激活环境
conda activate cad_study

# 2. 创建示例 DXF 文件
python examples\scripts\create_sample_dxf.py

# 3. 运行完整示例
python examples\scripts\quickstart.py
```

## 8. 常见问题解决

### 问题 1: 找不到 FreeCAD 模块

**错误**：`ModuleNotFoundError: No module named 'FreeCAD'`

**解决**：
1. 检查 config.yaml 中的 FreeCAD 路径是否正确
2. 确保路径使用正斜杠 `/` 或双反斜杠 `\\`
3. 验证 FreeCAD 安装路径下是否有 bin 目录

### 问题 2: LibreDWG 找不到

**错误**：找不到 dwg2dxf.exe

**解决**：
1. 检查 config.yaml 中的 LibreDWG 路径
2. 确认该目录下有 dwg2dxf.exe 文件
3. 或检查子目录中是否有该文件

### 问题 3: API 调用失败

**错误**：API 密钥相关错误或网络连接问题

**解决**：
1. 确认 API 密钥配置正确
2. 检查网络连接（可能需要代理）
3. 确认 API 密钥未过期且有足够额度

### 问题 4: 依赖包版本冲突

**解决**：
```bash
# 创建新的干净环境
conda create -n cad_study_new python=3.10
conda activate cad_study_new
cd e:\Code\CAD
pip install -r requirements.txt
```

## 9. 开发工作流程建议

1. 始终在 `cad_study` 环境中工作
2. 在开始工作前先激活环境：
   ```bash
   conda activate cad_study
   ```
3. 如果安装新包，考虑更新 requirements.txt：
   ```bash
   pip freeze > requirements.txt
   ```
4. 定期运行测试确保系统正常工作

## 10. 下一步

环境配置成功后，您可以：

- 查看 [API 文档](./api/index.md)
- 运行更多示例
- 开始开发自己的功能模块！
