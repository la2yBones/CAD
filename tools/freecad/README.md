# FreeCAD 增强包

此目录用于放置可选的项目级 FreeCAD 便携运行时。仓库不会提交完整 FreeCAD 本体。

推荐目录结构：

```text
tools/freecad/
  FreeCAD-1.0.x/
    bin/
      python.exe
      FreeCAD.exe
      ...
```

`FreeCADBridge` 的查找优先级：

1. 当前 Python 已经是 FreeCAD Python 时，使用 direct 模式。
2. `tools/freecad/*/bin/python.exe`。
3. `.env` 或配置中的 `FREECAD_BIN_PATH`。
4. Windows 常见安装位置。

如果本目录下有多个版本，系统按目录名倒序优先选择，例如 `FreeCAD-1.0.2` 会优先于 `FreeCAD-1.0.1`。
