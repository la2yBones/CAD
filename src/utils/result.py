#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一错误处理类型 —— Rust-style Result[T] 模式

Usage:
    from src.utils.result import Result

    def parse_file(path: str) -> Result[Dict]:
        try:
            data = load_file(path)
            return Result.Ok(data)
        except Exception as e:
            return Result.Err(f"解析失败: {e}")

    result = parse_file("test.dxf")
    if result.is_ok:
        print(result.value)
    else:
        print(f"错误: {result.error}")
"""

from typing import TypeVar, Generic, Optional, Callable, Any

T = TypeVar('T')
R = TypeVar('R')


class Result(Generic[T]):
    """Rust-style Result 类型，用于统一整个 CAD pipeline 的错误处理"""

    def __init__(self, value: Optional[T] = None, error: Optional[str] = None):
        self._value = value
        self._error = error

    @classmethod
    def Ok(cls, value: T) -> 'Result[T]':
        return cls(value=value)

    @classmethod
    def Err(cls, error: str) -> 'Result[T]':
        return cls(error=error)

    @property
    def is_ok(self) -> bool:
        return self._error is None

    @property
    def is_err(self) -> bool:
        return self._error is not None

    @property
    def value(self) -> Optional[T]:
        return self._value

    @property
    def error(self) -> Optional[str]:
        return self._error

    def unwrap(self) -> T:
        if self.is_err:
            raise RuntimeError(f"Called unwrap() on an Err: {self._error}")
        return self._value

    def unwrap_or(self, default: T) -> T:
        if self.is_err:
            return default
        return self._value

    def map(self, fn: Callable[[T], Any]) -> 'Result[Any]':
        if self.is_err:
            return Result.Err(self._error)
        try:
            return Result.Ok(fn(self._value))
        except Exception as e:
            return Result.Err(str(e))

    def and_then(self, fn: Callable[[T], 'Result[R]']) -> 'Result[R]':
        if self.is_err:
            return Result.Err(self._error)
        return fn(self._value)

    def __bool__(self) -> bool:
        return self.is_ok

    def __repr__(self) -> str:
        if self.is_ok:
            return f"Ok({self._value!r})"
        return f"Err({self._error!r})"
