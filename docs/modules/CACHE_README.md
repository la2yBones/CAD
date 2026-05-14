# 图纸分析缓存系统

版本：2.0.0

## 概述

`AnalysisCache` 为智能分析结果提供文件级缓存，避免同一图纸、同一拉伸高度和同一分析参数重复调用 DeepSeek。

## 缓存键

缓存键基于文件路径、文件大小、文件修改时间、拉伸高度和分析参数生成 SHA-256。

## 默认路径

| 缓存 | 默认路径 |
|---|---|
| 智能分析缓存 | `.cache/analysis` |
| 预览缓存 | `.cache/previews` |
| LLM 调用遥测 | `.cache/llm_telemetry/llm_calls.jsonl` |

## CLI 工具

```powershell
python tools/cache_tool.py stats
python tools/cache_tool.py clear-expired
python tools/cache_tool.py invalidate --file examples/cad_files/sample.dxf
python tools/cache_tool.py clear
```

`clear` 会逐个删除缓存 JSON 文件，不使用递归目录删除。

## Python API

```python
from src.utils.cache import AnalysisCache

cache = AnalysisCache(cache_dir=".cache/analysis", default_ttl=3600 * 24 * 7)
cached = cache.get("examples/cad_files/sample.dxf", extrude_height=10.0)
if cached is None:
    result = {"view_analysis": {}, "modeling_instructions": {}}
    cache.set("examples/cad_files/sample.dxf", 10.0, result)
```

## GUI 集成

GUI 的缓存管理面板使用 `get_stats()`、`list_entries()`、`delete_entry(cache_path)`、`clear_expired()` 和 `clear_all()` 展示与管理缓存。

## 配置

```yaml
cache:
  enable: true
  cache_dir: ".cache/analysis"
  default_ttl: 604800
```

## 注意事项

- 修改图纸内容或文件修改时间后，缓存键会变化。
- 修改拉伸高度或分析版本后，缓存键会变化。
- 过期缓存不会被读取，可通过工具或 GUI 清理。
- 缓存文件可能包含图纸结构信息和 AI 输出，分享前需检查内容。
