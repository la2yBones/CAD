"""
FreeCAD 桥接器

在系统 Python 中通过子进程调用 FreeCAD Python 执行建模脚本，
或在 FreeCAD 内置 Python 环境中直接导入 freecad 模块。

模式说明：
    - direct：当前 Python 即是 FreeCAD Python，直接 import freecad
    - subprocess：系统 Python → 子进程 FreeCAD Python
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.config import load_config
from ..utils.result import Result


class FreeCADBridge:
    """
    FreeCAD 桥接器。

    优先使用 direct 模式（检测 freecad 模块是否可导入），
    回退到 subprocess 模式（调用 FreeCAD 内置 Python）。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config: Dict[str, Any] = config or load_config()
        self._mode: Optional[str] = None
        self._freecad_python: Optional[str] = None

    def execute_script(self, script: str, timeout: int = 120) -> Result[Dict[str, Any]]:
        """
        执行 FreeCAD 建模脚本。

        Args:
            script: FreeCAD Python 脚本内容
            timeout: 超时时间（秒）

        Returns:
            Result[Dict]: Ok 时包含 output/stderr/returncode，Err 时包含错误信息
        """
        if self._mode is None:
            detect_result = self._detect_mode()
            if detect_result.is_err():
                return Result.Err(f"FreeCAD 模式检测失败: {detect_result.error}")

        if self._mode == "direct":
            return self._execute_direct(script)
        else:
            return self._execute_subprocess(script, timeout)

    def _detect_mode(self) -> Result[None]:
        """自动检测运行模式（direct 或 subprocess）。"""
        try:
            import freecad  # type: ignore[import-untyped]
            self._mode = "direct"
            return Result.Ok(None)
        except ImportError:
            pass

        fc_config = self._config.get("freecad", {})
        bin_path = fc_config.get("bin_path", "")
        if not bin_path:
            return Result.Err(
                "配置文件中未设置 freecad.bin_path，且当前环境非 FreeCAD Python。"
                "请在 config/config.yaml 中设置 freecad.bin_path 为 FreeCAD 安装目录下的 bin 路径。"
            )

        bin_dir = Path(bin_path)
        if not bin_dir.exists():
            return Result.Err(
                f"配置的 FreeCAD bin 路径不存在: {bin_path}。"
                "请检查 config/config.yaml 中的 freecad.bin_path 设置。"
            )

        python_exe = bin_dir / "python.exe" if os.name == "nt" else bin_dir / "python"
        if not python_exe.exists():
            return Result.Err(
                f"FreeCAD bin 目录中未找到 Python 可执行文件: {python_exe}。"
                "请确认 freecad.bin_path 指向正确的 FreeCAD bin 目录。"
            )

        self._freecad_python = str(python_exe)
        self._mode = "subprocess"
        return Result.Ok(None)

    def _execute_direct(self, script: str) -> Result[Dict[str, Any]]:
        """直接在 FreeCAD Python 环境中执行脚本（不涉及 exec，见 _execute_subprocess 路径）。"""
        result: Dict[str, Any] = {"output": "", "stderr": "", "returncode": 0}
        try:
            exec_globals: Dict[str, Any] = {}
            exec(script, exec_globals)  # nosec
            result["output"] = str(exec_globals.get("output", ""))
            result["stderr"] = str(exec_globals.get("stderr", ""))
            return Result.Ok(result)
        except Exception as e:
            result["stderr"] = str(e)
            result["returncode"] = 1
            return Result.Ok(result)

    def _execute_subprocess(self, script: str, timeout: int) -> Result[Dict[str, Any]]:
        """通过子进程调用 FreeCAD Python 执行脚本。"""
        if not self._freecad_python:
            return Result.Err("FreeCAD Python 路径未设置，请先调用 _detect_mode()。")

        try:
            proc = subprocess.run(
                [self._freecad_python, "-c", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return Result.Ok({
                "output": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            })
        except subprocess.TimeoutExpired as e:
            return Result.Err(f"FreeCAD 脚本执行超时（{timeout}秒）: {e}")
        except FileNotFoundError:
            return Result.Err(
                f"FreeCAD Python 可执行文件未找到: {self._freecad_python}。"
                "请检查 config/config.yaml 中的 freecad.bin_path 设置。"
            )
        except Exception as e:
            return Result.Err(f"FreeCAD 子进程执行失败: {e}")
