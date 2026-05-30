from dataclasses import dataclass, field
from typing import Generic, TypeVar, Optional, List

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

    @property
    def is_ok(self) -> bool:
        return self.success

    @property
    def is_fail(self) -> bool:
        return not self.success
