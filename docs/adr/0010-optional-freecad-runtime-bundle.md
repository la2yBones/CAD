# 可选 FreeCAD 增强包

系统目前通过 `FREECAD_BIN_PATH` 或常见安装路径发现 FreeCAD。用户希望让 FreeCAD 自动建模能力像项目内置 LibreDWG 一样更容易开箱使用，但 FreeCAD 运行时体积和依赖复杂度远高于 `dwg2dxf.exe`，不适合直接平铺进 `tools/bin` 并随仓库默认提交。

## Decision

1. 仓库不默认提交完整 FreeCAD 本体。
2. 系统支持可选的项目级 FreeCAD 增强包，约定放在 `tools/freecad/<FreeCAD-version>/bin/python.exe`。
3. FreeCAD 发现优先级为：项目级增强包 > `FREECAD_BIN_PATH` > 系统常见安装路径。
4. 普通开发仓库保持轻量；离线发行包可以额外包含 `tools/freecad/` 下的 FreeCAD 运行时。
5. `tools/freecad/` 应只提交说明文件和占位文件，不把完整 FreeCAD 运行时纳入源码版本管理。

## Consequences

- 用户可以通过解压增强包获得接近内置的 FreeCAD 自动建模体验。
- Git 仓库不会因为大型二进制运行时膨胀。
- 部署文档需要说明增强包目录结构和发现优先级。
- 后续实现必须避免把增强包路径和系统安装路径混为同一个配置概念。
