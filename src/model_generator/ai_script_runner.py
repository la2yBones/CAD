"""
AI 建模脚本执行器

在隔离上下文中运行 AI 生成的 FreeCAD Python 建模脚本。
支持两种模式：direct（当前 Python）和 bridge（子进程）。
"""

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.result import Result


class AIScriptRunner:
    """
    AI 脚本执行器。

    优先使用 direct 模式，若当前环境非 FreeCAD Python 则通过 FreeCADBridge 子进程执行。
    """

    SCRIPT_WRAPPER_TEMPLATE = """
import sys
import json
import traceback

_output = {{}}
_stderr = ""

try:
{script_body}
    _output['success'] = True
except Exception as e:
    _output['success'] = False
    _output['error'] = str(e)
    _stderr = traceback.format_exc()

print("__JSON_OUTPUT_START__")
print(json.dumps(_output, default=str))
print("__JSON_OUTPUT_END__")
if _stderr:
    print("__STDERR_START__")
    print(_stderr, file=sys.stderr)
    print("__STDERR_END__", file=sys.stderr)
"""

    def __init__(self, bridge=None):
        self._bridge = bridge

    def run_script(self, script: str, timeout: int = 120) -> Result[Dict[str, Any]]:
        """
        执行 AI 生成的建模脚本。

        Args:
            script: FreeCAD Python 脚本内容
            timeout: 超时时间（秒）

        Returns:
            Result[Dict]: Ok 时包含执行结果，Err 时包含错误信息
        """
        try:
            if self._uses_direct_mode():
                return self._run_direct(script)
            elif self._bridge is not None:
                return self._run_via_bridge(script, timeout)
            else:
                return Result.Err("无可用的 FreeCAD 执行环境：既非 direct 模式，也未配置 FreeCADBridge。")
        except Exception as e:
            return Result.Err(f"脚本执行异常: {str(e)}\n{traceback.format_exc()}")

    def _uses_direct_mode(self) -> bool:
        """检测当前是否在 FreeCAD Python 环境中运行。"""
        try:
            import FreeCAD  # type: ignore[import-untyped]
            return True
        except ImportError:
            return False

    def _run_direct(self, script: str) -> Result[Dict[str, Any]]:
        """在 FreeCAD Python 环境中直接执行脚本。"""
        try:
            local_ns: Dict[str, Any] = {}
            exec(script, {"__builtins__": __builtins__}, local_ns)  # nosec

            result: Dict[str, Any] = {}
            for key, value in local_ns.items():
                if not key.startswith("__"):
                    result[key] = value

            return Result.Ok(result)
        except Exception as e:
            return Result.Err(f"direct 模式脚本执行失败: {str(e)}\n{traceback.format_exc()}")

    def _run_via_bridge(self, script: str, timeout: int) -> Result[Dict[str, Any]]:
        """通过 FreeCADBridge 子进程执行脚本。"""
        wrapped_script = self._wrap_script(script)

        bridge_result = self._bridge.execute_script(wrapped_script, timeout)
        if bridge_result.is_err():
            return Result.Err(f"bridge 模式执行失败: {bridge_result.error}")

        exec_output = bridge_result.value
        stdout = exec_output.get("output", "")
        stderr = exec_output.get("stderr", "")
        returncode = exec_output.get("returncode", -1)

        if returncode != 0:
            return Result.Err(
                f"FreeCAD 脚本返回非零退出码 ({returncode})。\n"
                f"stdout: {stdout[:500]}\n"
                f"stderr: {stderr[:500]}"
            )

        return self._parse_bridge_output(stdout)

    def _wrap_script(self, script: str) -> str:
        """将脚本包装为带输出捕获的子进程可执行格式。"""
        indented = "\n".join(f"    {line}" for line in script.split("\n"))
        return self.SCRIPT_WRAPPER_TEMPLATE.format(script_body=indented)

    def _parse_bridge_output(self, stdout: str) -> Result[Dict[str, Any]]:
        """解析子进程 stdout 中的 JSON 输出。"""
        start_marker = "__JSON_OUTPUT_START__"
        end_marker = "__JSON_OUTPUT_END__"

        try:
            start_idx = stdout.index(start_marker) + len(start_marker)
            end_idx = stdout.index(end_marker)
            json_str = stdout[start_idx:end_idx].strip()
            data = json.loads(json_str)

            if data.get("success"):
                return Result.Ok(data)
            else:
                return Result.Err(data.get("error", "脚本执行失败，未提供详细错误信息"))
        except (ValueError, json.JSONDecodeError) as e:
            return Result.Err(f"解析 bridge 输出失败: {str(e)}")