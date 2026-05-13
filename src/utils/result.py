from dataclasses import dataclass, field
from typing import Generic, TypeVar, Optional, List, Any, Dict, Callable

T = TypeVar("T")


@dataclass
class Result(Generic[T]):
    """统一操作结果类型，替代 (success, data, error) 元组和裸字典"""

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @staticmethod
    def ok(data: T, warnings: Optional[List[str]] = None) -> "Result[T]":
        return Result(success=True, data=data, warnings=warnings or [])

    @staticmethod
    def fail(error: str, warnings: Optional[List[str]] = None) -> "Result[T]":
        return Result(success=False, error=error, warnings=warnings or [])

    @staticmethod
    def Ok(data: T, warnings: Optional[List[str]] = None) -> "Result[T]":
        """Backward-compatible alias for older Result.Ok(...) call sites."""
        return Result.ok(data, warnings)

    @staticmethod
    def Err(error: str, warnings: Optional[List[str]] = None) -> "Result[T]":
        """Backward-compatible alias for older Result.Err(...) call sites."""
        return Result.fail(error, warnings)

    @property
    def is_ok(self) -> bool:
        return self.success

    @property
    def is_fail(self) -> bool:
        return not self.success

    @property
    def is_err(self) -> bool:
        return not self.success

    @property
    def value(self) -> Optional[T]:
        return self.data

    def unwrap(self) -> T:
        if not self.success:
            raise ValueError(f"Called unwrap on a failed Result: {self.error}")
        return self.data

    def unwrap_or(self, default: T) -> T:
        return self.data if self.success else default

    def map(self, fn: Callable[[T], Any]) -> "Result":
        if not self.success:
            return self
        try:
            return Result.ok(fn(self.data), self.warnings)
        except Exception as e:
            return Result.fail(str(e), self.warnings)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"success": self.success}
        if self.success:
            d["data"] = self.data
        else:
            d["error"] = self.error
        if self.warnings:
            d["warnings"] = self.warnings
        return d
