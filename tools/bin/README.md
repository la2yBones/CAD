# tools/bin — 项目内置二进制工具

本目录存放项目内置的第三方二进制工具，使项目开箱可用，无需用户单独安装。

---

## LibreDWG (dwg2dxf)

**用途**：将 DWG 格式 CAD 文件转换为 DXF 格式，供 CAD 解析器读取。

**来源**：GNU LibreDWG 项目 — https://www.gnu.org/software/libredwg/

**版本**：0.13.4.8160-win64（官方 Windows 预编译包）

**文件列表**：

| 文件 | 说明 |
|------|------|
| `dwg2dxf.exe` | DWG → DXF 转换命令行工具 |
| `libredwg-0.dll` | LibreDWG 核心库 |
| `libiconv-2.dll` | 字符编码转换库 |
| `libpcre2-8-0.dll` | 正则表达式库 (8-bit) |
| `libpcre2-16-0.dll` | 正则表达式库 (16-bit) |

**调用方式**：`src/cad_parser/parser.py` 中的 `_find_dwg2dxf()` 方法优先查找本目录下的 `dwg2dxf.exe`；若不存在，回退到配置中的 `LIBREDWG_PATH` 外部路径。

**许可协议**：GNU General Public License v3 (GPLv3)

**许可提醒**：本目录中的二进制文件来自 LibreDWG 官方发布包，未经修改。再分发时须遵守 GPLv3 条款，保留原始版权声明。项目根目录 `LICENSE` 文件适用于项目自有代码；LibreDWG 组件适用其自身的 GPLv3 许可。

---

## 更新二进制文件

如需升级 LibreDWG 版本：

1. 从 https://www.gnu.org/software/libredwg/ 下载新版 Windows 预编译包。
2. 替换本目录下的 5 个文件。
3. 更新本 README 中的版本号。
4. 用 `tools/bin/dwg2dxf.exe -y -o test.dxf examples/cad_files/sample.dwg` 验证转换正常。
