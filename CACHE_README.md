# 图纸分析缓存系统

## 概述

本缓存系统为图纸智能分析提供高效的重复分析加速，通过缓存机制避免重复执行完整分析流程，显著减少等待时间。

## 功能特性

- ✅ **智能缓存键生成** - 基于文件内容、大小、修改时间和分析参数生成唯一键
- ✅ **自动缓存管理** - 自动检测、使用和更新缓存
- ✅ **过期策略** - 默认7天过期，可自定义设置
- ✅ **缓存命中/未命中标识** - 清晰显示缓存状态
- ✅ **缓存管理工具** - 提供完整的缓存清理、失效和统计功能

## 使用方法

### 1. 自动缓存（默认启用）

使用智能分析模式时，缓存会自动启用：

```bash
python cad_cli.py -f 样本.dxf --intelligent
```

**首次运行：**
```
=== 开始智能工程图纸分析 ===
步骤1: 分析视图结构...
步骤2: 提取尺寸标注...
步骤3: 生成FreeCAD建模指令...
=== 智能分析完成 ===
智能分析完成并已缓存
```

**再次运行（缓存命中）：**
```
缓存系统已启用
缓存命中: 样本.dxf
从缓存加载分析结果
```

### 2. 缓存管理工具

使用 `cache_tool.py` 管理缓存：

#### 查看缓存统计
```bash
python cache_tool.py stats
```

输出示例：
```
=== 缓存统计 ===
缓存目录: E:\Code\CAD\.cache\analysis
缓存文件数: 5
总大小: 0.23 MB
```

#### 清理过期缓存
```bash
python cache_tool.py clear-expired
```

#### 清空所有缓存
```bash
python cache_tool.py clear
```

#### 使特定文件缓存失效
```bash
python cache_tool.py invalidate --file examples/cad_files/样本.dxf
```

## 配置选项

在 `config/config.yaml` 中配置缓存：

```yaml
cache:
  enable: true          # 是否启用缓存
  cache_dir: ".cache/analysis"  # 缓存存储目录
  default_ttl: 604800   # 缓存过期时间(秒)，默认7天
```

## Python API 使用

### 独立使用缓存系统

```python
from src.utils.cache import AnalysisCache

cache = AnalysisCache(cache_dir=".cache/analysis", default_ttl=3600 * 24 * 7)

# 检查并获取缓存
cached = cache.get("图纸.dxf", extrude_height=10)
if cached:
    print("使用缓存")
else:
    print("执行分析")
    # ... 执行分析 ...
    result = {...}
    cache.set("图纸.dxf", 10, result)
```

### 在智能分析器中使用

```python
from src.intelligent_analyzer import IntelligentEngineeringAnalyzer

analyzer = IntelligentEngineeringAnalyzer(
    api_key="your-key",
    config=config,
    enable_cache=True,         # 启用缓存
    cache_dir=".cache/analysis",
    cache_ttl=3600 * 24 * 7    # 7天过期
)

# 分析时自动处理缓存
result = analyzer.analyze_full(
    geometry_data, 
    extrude_height=10, 
    file_path="图纸.dxf"
)

# 检查是否为缓存命中
if result.get('_cache_hit'):
    print(f"使用缓存: {result.get('_cache_key')[:16]}")
```

## 缓存键生成

缓存键基于以下因素生成，确保唯一性：

1. 文件路径
2. 文件大小
3. 文件修改时间
4. 拉伸高度
5. 其他分析参数

使用 SHA-256 哈希生成64位唯一标识符。

## 缓存结构

```
.cache/analysis/
├── ab/
│   └── abcdef1234567890.json
├── cd/
│   └── cdef1234567890ab.json
└── ...
```

文件存储格式：
```json
{
  "view_analysis": {...},
  "dimension_extraction": {...},
  "modeling_instructions": {...},
  "_cache_timestamp": 1714978500,
  "_cache_ttl": 604800,
  "_source_file": "examples/cad_files/样本.dxf"
}
```

## 缓存清理策略

- **自动过期清理**：通过 `clear-expired` 命令
- **手动失效**：通过 `invalidate` 命令使特定文件缓存失效
- **完全清空**：通过 `clear` 命令
- **文件更新检测**：当文件大小或修改时间变化时自动使旧缓存失效

## 性能优势

| 场景 | 首次运行 | 缓存命中 |
|------|---------|---------|
| 简单图纸 | ~5-10秒 | <0.1秒 |
| 复杂图纸 | ~10-30秒 | <0.1秒 |
| 批量处理 | 线性时间 | 几乎瞬间完成 |

## 注意事项

1. 缓存文件位于 `.cache/analysis`，可手动删除
2. 修改图纸内容后会自动重新分析
3. 缓存键包含时间戳，确保文件更新后失效
4. 分析参数变化也会触发重新分析
