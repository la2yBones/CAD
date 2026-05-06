# API文档

本目录包含项目各模块的API参考文档。

## 模块列表

- [DXF解析器](./dxf_parser.md) - DXF/DWG文件解析
- [几何分析器](./geometry_analyzer.md) - 几何关系分析
- [模型生成器](./model_generator.md) - 3D模型生成

## 数据格式

### 几何数据格式

```json
{
  "version": "AC1027",
  "units": "mm",
  "entities": [
    {
      "type": "LINE",
      "layer": "0",
      "color": 256,
      "start": [0, 0, 0],
      "end": [100, 100, 0]
    }
  ]
}
```

### 关系分析结果格式

```json
{
  "entity_pairs": [
    {
      "id1": 0,
      "id2": 1,
      "relationship": "相交"
    }
  ],
  "summary": "检测到2个实体，存在1个相交关系"
}
```
