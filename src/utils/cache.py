#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图纸分析缓存系统
实现高效的缓存机制，避免重复分析
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AnalysisCache:
    """
    智能分析缓存管理器
    """

    def __init__(self, cache_dir: str = ".cache", 
                 default_ttl: int = 3600 * 24 * 7,  # 默认7天
                 config: Optional[Dict] = None):
        """
        初始化缓存管理器

        参数:
            cache_dir: 缓存目录
            default_ttl: 默认过期时间（秒）
            config: 配置字典
        """
        self.cache_dir = Path(cache_dir)
        self.default_ttl = default_ttl
        self.config = config or {}

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"缓存系统初始化完成: {self.cache_dir.absolute()}, TTL: {default_ttl}s")

    def _generate_cache_key(self, file_path: str,
                           analysis_params: Optional[Dict] = None) -> str:
        """
        生成唯一缓存键

        参数:
            file_path: 图纸文件路径
            analysis_params: 分析参数字典

        返回:
            唯一缓存键字符串
        """
        path_obj = Path(file_path)
        file_stat = path_obj.stat()

        key_parts = {
            'file_path': str(file_path),
            'file_size': file_stat.st_size,
            'file_mtime': file_stat.st_mtime,
            'analysis_params': analysis_params or {}
        }

        key_str = json.dumps(key_parts, sort_keys=True, ensure_ascii=False)
        hash_object = hashlib.sha256(key_str.encode('utf-8'))
        cache_key = hash_object.hexdigest()

        logger.debug(f"生成缓存键: {cache_key} (源: {file_path})")
        return cache_key

    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        subdir = cache_key[:2]
        return self.cache_dir / subdir / f"{cache_key}.json"

    def _prune_empty_parent_dirs(self, start_dir: Path) -> None:
        """清理缓存根目录下的空分片目录。"""
        try:
            cache_root = self.cache_dir.resolve()
            current = start_dir.resolve()
        except Exception:
            return

        while current != cache_root and cache_root in current.parents:
            try:
                current.rmdir()
                logger.debug(f"已清理空缓存目录: {current}")
            except OSError:
                break
            current = current.parent

    def delete_entry(self, cache_path: str) -> bool:
        """删除一个明确的缓存文件，并清理它留下的空目录。"""
        path = Path(cache_path)
        try:
            cache_root = self.cache_dir.resolve()
            resolved = path.resolve()
            if cache_root != resolved.parent and cache_root not in resolved.parents:
                logger.warning(f"拒绝删除缓存目录外的文件: {cache_path}")
                return False
            if not resolved.exists() or not resolved.is_file():
                return False
            parent = resolved.parent
            resolved.unlink()
            self._prune_empty_parent_dirs(parent)
            logger.info(f"缓存已删除: {resolved}")
            return True
        except Exception as e:
            logger.warning(f"删除缓存条目失败: {cache_path}: {e}")
            return False

    def get(self, file_path: str,
            analysis_params: Optional[Dict] = None) -> Optional[Dict]:
        """
        从缓存读取分析结果

        参数:
            file_path: 图纸文件路径
            analysis_params: 分析参数

        返回:
            缓存结果，如果不存在或已过期返回None
        """
        try:
            cache_key = self._generate_cache_key(file_path, analysis_params)
            cache_path = self._get_cache_path(cache_key)

            if not cache_path.exists():
                logger.debug(f"缓存未命中: {file_path}")
                return None

            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 检查过期
            stored_timestamp = cache_data.get('_cache_timestamp', 0)
            stored_ttl = cache_data.get('_cache_ttl', self.default_ttl)

            if datetime.now().timestamp() - stored_timestamp > stored_ttl:
                logger.info(f"缓存已过期: {file_path}")
                return None

            logger.info(f"缓存命中: {file_path} (键: {cache_key[:16]})")

            result = {k: v for k, v in cache_data.items() if not k.startswith('_')}
            result['_cache_hit'] = True
            result['_cache_key'] = cache_key
            result['_cache_timestamp'] = stored_timestamp
            return result

        except Exception as e:
            logger.warning(f"读取缓存失败: {e}")
            return None

    def set(self, file_path: str,
            result_data: Dict[str, Any], ttl: Optional[int] = None,
            analysis_params: Optional[Dict] = None) -> bool:
        """
        将分析结果写入缓存

        参数:
            file_path: 图纸文件路径
            result_data: 结果数据
            ttl: 过期时间（秒）
            analysis_params: 分析参数

        返回:
            是否成功
        """
        try:
            cache_key = self._generate_cache_key(file_path, analysis_params)
            cache_path = self._get_cache_path(cache_key)
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            ttl = ttl or self.default_ttl
            cache_data = dict(result_data)
            cache_data['_cache_timestamp'] = datetime.now().timestamp()
            cache_data['_cache_ttl'] = ttl
            cache_data['_cache_key'] = cache_key
            cache_data['_source_file'] = str(file_path)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            logger.info(f"缓存已保存: {file_path} -> {cache_path}")
            return True

        except Exception as e:
            logger.error(f"写入缓存失败: {e}")
            return False

    def invalidate(self, file_path: str,
                   analysis_params: Optional[Dict] = None) -> int:
        """
        使特定文件缓存失效

        参数:
            file_path: 图纸文件路径
            analysis_params: 分析参数

        返回:
            删除的缓存数量
        """
        try:
            removed_count = 0

            # 删除该文件相关的所有缓存
            file_path_str = str(file_path)
            for cache_file in list(self.cache_dir.rglob("*.json")):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if data.get('_source_file') == file_path_str:
                            if self.delete_entry(str(cache_file)):
                                removed_count += 1
                except:
                    pass

            logger.info(f"删除 {removed_count} 个缓存项")
            return removed_count

        except Exception as e:
            logger.warning(f"失效缓存失败: {e}")
            return 0

    def clear_expired(self) -> int:
        """
        清理所有过期缓存

        返回:
            删除的缓存文件数量
        """
        removed_count = 0
        current_time = datetime.now().timestamp()

        for cache_file in list(self.cache_dir.rglob("*.json")):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    timestamp = data.get('_cache_timestamp', 0)
                    ttl = data.get('_cache_ttl', self.default_ttl)

                    if current_time - timestamp > ttl:
                        if self.delete_entry(str(cache_file)):
                            removed_count += 1
                        logger.debug(f"删除过期缓存: {cache_file}")
            except:
                # 删除损坏的缓存文件
                if self.delete_entry(str(cache_file)):
                    removed_count += 1

        if removed_count > 0:
            logger.info(f"清理完成，删除了 {removed_count} 个过期缓存")
        return removed_count

    def clear_all(self) -> int:
        """
        清空所有缓存

        返回:
            删除的缓存文件数量
        """
        removed_count = 0

        for cache_file in list(self.cache_dir.rglob("*.json")):
            try:
                if self.delete_entry(str(cache_file)):
                    removed_count += 1
            except:
                pass

        logger.info(f"已清空所有缓存，删除了 {removed_count} 个文件")
        return removed_count

    def list_entries(self) -> list:
        """
        列出缓存条目，供GUI缓存管理面板展示。

        返回:
            缓存条目列表。每个条目包含源文件、大小、时间戳、是否过期等信息。
        """
        entries = []
        current_time = datetime.now().timestamp()

        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                stat = cache_file.stat()
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                timestamp = data.get('_cache_timestamp') or stat.st_mtime
                ttl = data.get('_cache_ttl', self.default_ttl)
                source_file = data.get('_source_file', '')
                entries.append({
                    'cache_key': data.get('_cache_key', cache_file.stem),
                    'cache_path': str(cache_file),
                    'source_file': source_file,
                    'size_bytes': stat.st_size,
                    'timestamp': timestamp,
                    'ttl': ttl,
                    'expired': current_time - float(timestamp or 0) > float(ttl or self.default_ttl),
                })
            except Exception as e:
                logger.warning(f"读取缓存条目失败: {cache_file}: {e}")
                stat = cache_file.stat() if cache_file.exists() else None
                entries.append({
                    'cache_key': cache_file.stem,
                    'cache_path': str(cache_file),
                    'source_file': '',
                    'size_bytes': stat.st_size if stat else 0,
                    'timestamp': stat.st_mtime if stat else 0,
                    'ttl': self.default_ttl,
                    'expired': True,
                    'error': str(e),
                })

        entries.sort(key=lambda item: item.get('timestamp') or 0, reverse=True)
        return entries

    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        返回:
            统计字典
        """
        total_size = 0
        total_count = 0
        oldest_time = None
        newest_time = None

        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                stat = cache_file.stat()
                total_size += stat.st_size
                total_count += 1

                mtime = stat.st_mtime
                if oldest_time is None or mtime < oldest_time:
                    oldest_time = mtime
                if newest_time is None or mtime > newest_time:
                    newest_time = mtime
            except:
                pass

        return {
            'total_count': total_count,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
            'oldest_timestamp': oldest_time,
            'newest_timestamp': newest_time,
            'cache_dir': str(self.cache_dir.absolute())
        }
