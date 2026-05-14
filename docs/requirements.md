# 需求规格说明书

## 1. 项目目标

系统面向二维 CAD 工程图到三维模型的自动化转换。用户输入 DXF/DWG 图纸后，系统应解析几何实体、识别视图和尺寸信息，并输出可用于后续 CAD 交换、3D 打印或工程演示的 STEP、STL、FCStd 文件。

## 2. 用户角色

| 角色 | 目标 |
|---|---|
| 普通使用者 | 通过 GUI 或 CLI 选择图纸并生成模型 |
| 开发者 | 扩展解析、分析、建模和批处理逻辑 |
| 运维/部署人员 | 配置 DeepSeek、LibreDWG、FreeCAD 和缓存目录 |
| 毕设答辩/演示人员 | 展示完整流程、日志、报告和结果产物 |

## 3. 功能需求

| 编号 | 需求 | 当前实现 |
|---|---|---|
| FR-01 | 支持 DXF 文件解析 | `CADParser.parse()` 使用 ezdxf 读取模型空间 |
| FR-02 | 支持 DWG 文件解析 | 通过 LibreDWG `dwg2dxf.exe` 转 DXF 后解析 |
| FR-03 | 支持常见图元 | LINE、CIRCLE、ARC、LWPOLYLINE、TEXT、MTEXT、ELLIPSE、SPLINE、DIMENSION、INSERT |
| FR-04 | 支持块引用展开 | INSERT 递归读取 block 并应用平移、缩放、旋转 |
| FR-05 | 输出结构化几何数据 | `*_geometry.json` |
| FR-06 | 生成预览图 | matplotlib/ezdxf 渲染为 PNG，默认缓存到 `.cache/previews` |
| FR-07 | 基础建模 | 通用 FreeCAD 建模器对闭合轮廓进行拉伸和孔槽减除 |
| FR-08 | 智能分析 | `IntelligentEngineeringAnalyzer` 完成视图、尺寸、关系和建模指令 |
| FR-09 | LLM 视图语义校正 | `LLMViewAnalyzer` 使用 DeepSeek 并通过 Schema 校验结果 |
| FR-10 | 多视图保护 | 二/三视图无可靠 AI 脚本时阻止普通拉伸 |
| FR-11 | 模型导出 | STEP、STL、FCStd |
| FR-12 | 批处理 | `CADPipeline` 支持单文件、多文件和目录处理 |
| FR-13 | GUI | 文件扫描、预览、处理、日志、缓存管理和 AI 调用监控 |
| FR-14 | 缓存管理 | `AnalysisCache` 和 `tools/cache_tool.py` |
| FR-15 | LLM 调用监控 | `LLMTelemetryStore` 记录调用耗时和 token 统计 |

## 4. 非功能需求

| 编号 | 需求 | 实现约束 |
|---|---|---|
| NFR-01 | Windows 优先 | FreeCAD 和 LibreDWG 路径示例均以 Windows 为主 |
| NFR-02 | Python 兼容 | Python 3.10+，推荐 Conda 环境 |
| NFR-03 | 配置安全 | 真实密钥放入 `.env` 或系统环境变量 |
| NFR-04 | 可观测性 | 日志脱敏、GUI 日志面板、LLM JSONL 遥测 |
| NFR-05 | 可恢复性 | AI 失败后回退本地规则或通用建模器 |
| NFR-06 | 可维护性 | 模块化目录、统一配置、文档与代码同步 |
| NFR-07 | 性能 | 本地关系分析使用 STRtree，复杂图纸可跳过全量关系分析 |
| NFR-08 | 安全边界 | AI 脚本执行仍非强沙箱，需在可信环境运行 |

## 5. 输入输出

| 类型 | 格式 | 说明 |
|---|---|---|
| 输入 | `.dxf`, `.dwg` | DWG 依赖 LibreDWG 转换 |
| 中间产物 | `.json`, `.txt`, `.py` | 几何数据、分析报告、AI FreeCAD 脚本 |
| 输出 | `.step`, `.stl`, `.FCStd`, `.png` | 模型文件和图纸预览 |
| 缓存 | `.cache/analysis`, `.cache/previews`, `.cache/llm_telemetry` | 分析缓存、预览缓存、AI 调用记录 |

## 6. 当前限制

- 通用建模器适合单一闭合轮廓平面拉伸，不负责从二/三视图确定性重建三维实体。
- AI 脚本执行使用 `exec()`，尚未实现完整沙箱、文件系统白名单和 API 白名单。
- DWG 支持取决于 LibreDWG 对具体 DWG 版本的兼容性。
- FreeCAD 依赖本机安装，普通 Python 环境不能直接 `import FreeCAD`。
