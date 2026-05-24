# API 与模块参考

## 公共工具

### `src.utils.load_config(config_path: Optional[str] = None) -> dict`

加载 YAML 配置并解析 `${VAR}` 占位符。

优先级：

1. 操作系统环境变量
2. 项目根目录 `.env`
3. YAML 文件中的字面值

常用变量：

- `DEEPSEEK_API_KEY`
- `LIBREDWG_PATH`（可选，项目已内置）
- `FREECAD_BIN_PATH`

### `src.utils.setup_logging(level="INFO", log_file=None, name="cad_modeler")`

创建控制台和可选文件日志，并自动添加 `SensitiveDataFilter`。

脱敏范围：

- `sk-...`
- `api_key=...`
- `token=...`

### `src.utils.Result[T]`

统一结果类型：

```python
from src.utils import Result

result = Result.ok({"count": 1})
fallback = result.unwrap_or({})
mapped = result.map(lambda data: data["count"])
failed = Result.fail("解析失败")
```

兼容旧调用：

```python
Result.Ok(data)
Result.Err("error")
```

## CAD 解析

### `src.cad_parser.CADParser`

职责：

- 读取 DXF 文件
- 通过 LibreDWG 转换并解析 DWG 文件
- 提取结构化实体数据
- 生成 CAD 预览 PNG

示例：

```python
from src.cad_parser import CADParser
from src.utils import load_config

config = load_config()
parser = CADParser("examples/cad_files/sample.dxf", config.get("dxf_parser", {}))
geometry = parser.parse()
parser.visualize()
```

`visualize()` 未传入路径时会保存到：

```text
examples/output/<图纸名>_preview.png
```

GUI 预览使用的稳定缓存路径为：

```text
examples/output/<图纸名>/<图纸名>_preview.png
```

输出数据核心字段：

```json
{
  "version": "AC1027",
  "units": "mm",
  "entities": [
    {
      "type": "LINE",
      "layer": "0",
      "start": [0, 0, 0],
      "end": [100, 100, 0]
    }
  ]
}
```

## 批处理

### `src.batch_processor.CADPipeline`

职责：

- 扫描输入目录
- 调用解析器
- 执行统一智能处理或内部平面拉伸兼容路径
- 调用建模执行分发
- 汇总每个文件的处理结果

典型入口：

```python
from src.batch_processor import CADPipeline
from src.utils import load_config

pipeline = CADPipeline(config=load_config())
result = pipeline.process_file_intelligent("sample.dxf")
```

推荐入口：

```python
smart = pipeline.process_file_intelligent("sample.dxf")
batch = pipeline.process_directory_intelligent()
```

`process_file(...)`、`process_file_basic(...)` 和 `process_file_legacy_analysis(...)` 仅保留为兼容或内部专用入口；新业务代码应从统一智能处理进入，让系统依据建模路径裁决选择平面拉伸路径或语义重建路径。

兼容入口的冻结范围与迁移条件见 [兼容入口冻结清单](../compatibility.md)。

## 智能处理编排

### `src.intelligent_analyzer.IntelligentEngineeringAnalyzer`

职责：

- 作为保留旧类名的智能处理编排器
- 组织 `ViewAnalyzer`、`DimensionExtractor`、LLM 视图语义校正和本地几何证据
- 调用 `SemanticReconstructionPipeline` 这个语义重建内核
- 返回包含语义结果和 `modeling_path_decision` 的智能分析结果

统一智能处理需要 `DEEPSEEK_API_KEY` 配置可用。当前本地规则和聚类逻辑仍是智能分析子过程的重要组成部分。

LLM 输入采用阶段化载荷：

- `build_view_decision_payload(...)` 构建视图判定载荷，供 `LLMViewAnalyzer` 校正视图结构。
- `SemanticUnderstandingPayloadBuilder.build(...)` 构建语义理解载荷，供 `PartSemanticGenerator` 生成 `part_semantics`。
- `ModelingTaskBuilder.build(...)` 构建建模任务载荷，供 `FreeCADInstructionGenerator` 生成 FreeCAD 脚本。

这些载荷是 LLM 调用边界，不等同于本地缓存或完整中间结果。完整实体和本地关系明细仍可在本地分析、裁决和校验中使用，但不应直接传入大模型 prompt。

## 模型生成

### `src.model_generator.FreeCADBridge`

职责：

- direct 模式：在 FreeCAD Python 内直接导入并执行
- subprocess 模式：通过 FreeCAD 自带 `python.exe` 执行脚本
- 优先使用项目级 `tools/freecad/*/bin/python.exe` 增强包，其次使用配置路径，再扫描 Windows 常见安装位置

`.env` 推荐配置：

```env
FREECAD_BIN_PATH=D:\FreeCAD 1.0\bin
```

### `src.model_generator.PlanarExtrudeModeler`

职责：

- 承接平面拉伸路径的旧执行实现
- 导出 STEP、STL、FCStd
- 汇总生成结果和错误信息

`PlanarExtrudeModeler` 是平面拉伸路径的内部 adapter 名称，当前复用旧 `FreeCADModeler` 实现。`FreeCADModeler` 仍可通过兼容层导入，但它不是新代码的主入口；新流程应经由 `CADPipeline.process_file_intelligent(...)` 和建模执行分发调用。

旧导入路径只做兼容转发，详见 [兼容入口冻结清单](../compatibility.md)。

## 安全边界

- `.env` 不应提交到版本控制。
- 日志脱敏用于降低风险，不能替代避免记录敏感配置。
- AI/FreeCAD 脚本执行仍包含 `exec()` 路径，后续应加入脚本白名单、目录限制和更强隔离。
