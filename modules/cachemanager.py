"""
缓存管理模块

提供双层缓存管理功能，包括内存缓存和磁盘缓存，支持 LRU 淘汰策略和缓存过期管理。

功能特性：
1. 内存缓存与磁盘缓存
2. 缓存过期管理
3. LRU 淘汰策略
4. 缓存大小限制
5. 缓存键生成（基于 URL + 方法 + 关键请求头）
6. 缓存统计信息查询
7. 缓存预热
8. 清理过期缓存
"""

import asyncio
import time
import hashlib
import json
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
import os
import shutil


class CacheManager:
    """
    缓存管理器

    功能：
    1. 内存缓存与磁盘缓存
    2. 缓存过期管理
    3. LRU 淘汰策略
    4. 缓存大小限制
    """

    def __init__(self,
                 max_memory_cache_size: int = 100 * 1024 * 1024,  # 100MB
                 max_disk_cache_size: int = 1024 * 1024 * 1024,   # 1GB
                 default_ttl: int = 3600,  # 1小时
                 disk_cache_dir: str = './cache'):
        """
        初始化缓存管理器

        Args:
            max_memory_cache_size: 最大内存缓存大小（字节）
            max_disk_cache_size: 最大磁盘缓存大小（字节）
            default_ttl: 默认缓存过期时间（秒）
            disk_cache_dir: 磁盘缓存目录
        """
        self.max_memory_cache_size = max_memory_cache_size
        self.max_disk_cache_size = max_disk_cache_size
        self.default_ttl = default_ttl
        self.disk_cache_dir = disk_cache_dir

        # 内存缓存：{cache_key: (data, expire_time, size)}
        self._memory_cache: Dict[str, Tuple[bytes, float, int]] = {}

        # LRU 访问记录：{cache_key: last_access_time}
        self._lru_record: Dict[str, float] = {}

        # 当前缓存大小
        self._current_memory_size = 0
        self._current_disk_size = 0

        # 锁机制
        self._lock = asyncio.Lock()

        # 创建磁盘缓存目录
        os.makedirs(disk_cache_dir, exist_ok=True)

        # 统计信息
        self.stats = {
            'memory_hits': 0,
            'disk_hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_cached_items': 0
        }

    def _generate_cache_key(self, url: str, method: str = 'GET', headers: dict = None) -> str:
        """
        生成缓存键

        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头

        Returns:
            缓存键
        """
        # 组合 URL、方法和关键请求头
        key_data = f"{method}:{url}"

        if headers:
            # 只包含影响响应的请求头
            important_headers = ['accept', 'accept-encoding', 'accept-language']
            for header in important_headers:
                if header in headers:
                    key_data += f":{header}={headers[header]}"

        # 生成 MD5 哈希
        return hashlib.md5(key_data.encode()).hexdigest()

    async def get(self,
                 url: str,
                 method: str = 'GET',
                 headers: dict = None) -> Optional[bytes]:
        """
        从缓存获取数据

        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头

        Returns:
            缓存的数据，如果不存在或已过期则返回 None
        """
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            # 1. 尝试从内存缓存获取
            if cache_key in self._memory_cache:
                data, expire_time, size = self._memory_cache[cache_key]

                # 检查是否过期
                if time.time() < expire_time:
                    # 更新 LRU 记录
                    self._lru_record[cache_key] = time.time()
                    self.stats['memory_hits'] += 1
                    return data
                else:
                    # 过期，删除缓存
                    await self._delete_from_memory(cache_key)

            # 2. 尝试从磁盘缓存获取
            disk_data = await self._get_from_disk(cache_key)

            if disk_data is not None:
                # 更新 LRU 记录
                self._lru_record[cache_key] = time.time()
                self.stats['disk_hits'] += 1

                # 将磁盘缓存提升到内存缓存
                await self._set_to_memory(cache_key, disk_data, self.default_ttl)

                return disk_data

            # 3. 缓存未命中
            self.stats['misses'] += 1
            return None

    async def set(self,
                 url: str,
                 data: bytes,
                 method: str = 'GET',
                 headers: dict = None,
                 ttl: Optional[int] = None,
                 cache_to_disk: bool = True):
        """
        设置缓存

        Args:
            url: 请求 URL
            data: 要缓存的数据
            method: 请求方法
            headers: 请求头
            ttl: 缓存过期时间（秒）
            cache_to_disk: 是否缓存到磁盘
        """
        cache_key = self._generate_cache_key(url, method, headers)
        ttl = ttl or self.default_ttl

        async with self._lock:
            # 1. 设置内存缓存
            await self._set_to_memory(cache_key, data, ttl)

            # 2. 设置磁盘缓存
            if cache_to_disk:
                await self._set_to_disk(cache_key, data, ttl)

    async def _set_to_memory(self, cache_key: str, data: bytes, ttl: int):
        """
        设置内存缓存

        Args:
            cache_key: 缓存键
            data: 缓存数据
            ttl: 过期时间
        """
        # 检查是否需要清理空间
        data_size = len(data)

        while self._current_memory_size + data_size > self.max_memory_cache_size:
            await self._evict_lru_memory()

        # 设置缓存
        expire_time = time.time() + ttl
        self._memory_cache[cache_key] = (data, expire_time, data_size)
        self._lru_record[cache_key] = time.time()
        self._current_memory_size += data_size
        self.stats['total_cached_items'] += 1

    async def _set_to_disk(self, cache_key: str, data: bytes, ttl: int):
        """
        设置磁盘缓存

        Args:
            cache_key: 缓存键
            data: 缓存数据
            ttl: 过期时间
        """
        # 检查磁盘空间
        data_size = len(data)

        while self._current_disk_size + data_size > self.max_disk_cache_size:
            await self._evict_lru_disk()

        # 写入文件
        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            # 写入缓存数据
            with open(cache_file, 'wb') as f:
                f.write(data)

            # 写入元数据
            meta = {
                'expire_time': time.time() + ttl,
                'size': data_size,
                'created_at': datetime.now().isoformat()
            }

            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f)

            self._current_disk_size += data_size

        except IOError as e:
            # 磁盘写入失败，记录错误但不中断
            print(f"Failed to write cache to disk: {e}")

    async def _get_from_disk(self, cache_key: str) -> Optional[bytes]:
        """
        从磁盘获取缓存

        Args:
            cache_key: 缓存键

        Returns:
            缓存数据
        """
        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            # 读取元数据
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)

            # 检查是否过期
            if time.time() > meta['expire_time']:
                await self._delete_from_disk(cache_key)
                return None

            # 读取缓存数据
            with open(cache_file, 'rb') as f:
                return f.read()

        except FileNotFoundError:
            return None
        except (IOError, json.JSONDecodeError) as e:
            # 文件读取失败或 JSON 解析失败
            print(f"Failed to read cache from disk: {e}")
            return None

    async def _delete_from_memory(self, cache_key: str):
        """
        从内存删除缓存

        Args:
            cache_key: 缓存键
        """
        if cache_key in self._memory_cache:
            _, _, size = self._memory_cache[cache_key]
            del self._memory_cache[cache_key]
            self._current_memory_size -= size
            self.stats['total_cached_items'] -= 1

        if cache_key in self._lru_record:
            del self._lru_record[cache_key]

    async def _delete_from_disk(self, cache_key: str):
        """
        从磁盘删除缓存

        Args:
            cache_key: 缓存键
        """
        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            # 读取元数据获取大小
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)

            self._current_disk_size -= meta['size']

            # 删除文件
            os.remove(cache_file)
            os.remove(meta_file)

        except FileNotFoundError:
            pass
        except (IOError, json.JSONDecodeError) as e:
            print(f"Failed to delete cache from disk: {e}")

    async def _evict_lru_memory(self):
        """
        淘汰最近最少使用的内存缓存
        """
        if not self._lru_record:
            return

        # 找到最久未使用的缓存键
        lru_key = min(self._lru_record, key=self._lru_record.get)

        # 删除缓存
        await self._delete_from_memory(lru_key)
        self.stats['evictions'] += 1

    async def _evict_lru_disk(self):
        """
        淘汰最近最少使用的磁盘缓存
        """
        # 扫描磁盘缓存目录
        try:
            cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
        except OSError as e:
            print(f"Failed to list disk cache directory: {e}")
            return

        if not cache_files:
            return

        # 找到最旧的缓存
        oldest_time = float('inf')
        oldest_key = None

        for meta_file in cache_files:
            cache_key = meta_file.replace('.meta', '')
            meta_path = os.path.join(self.disk_cache_dir, meta_file)

            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)

                created_at = datetime.fromisoformat(meta['created_at']).timestamp()

                if created_at < oldest_time:
                    oldest_time = created_at
                    oldest_key = cache_key

            except (IOError, json.JSONDecodeError, ValueError) as e:
                print(f"Failed to read cache meta: {e}")
                continue

        # 删除最旧的缓存
        if oldest_key:
            await self._delete_from_disk(oldest_key)
            self.stats['evictions'] += 1

    async def clear_all(self):
        """
        清空所有缓存
        """
        async with self._lock:
            # 清空内存缓存
            self._memory_cache.clear()
            self._lru_record.clear()
            self._current_memory_size = 0

            # 清空磁盘缓存
            try:
                shutil.rmtree(self.disk_cache_dir)
                os.makedirs(self.disk_cache_dir, exist_ok=True)
            except OSError as e:
                print(f"Failed to clear disk cache: {e}")

            self._current_disk_size = 0

            # 重置统计
            self.stats['total_cached_items'] = 0

    async def cleanup_expired(self):
        """
        清理过期缓存
        """
        async with self._lock:
            current_time = time.time()

            # 清理内存缓存
            expired_keys = []
            for cache_key, (_, expire_time, _) in self._memory_cache.items():
                if current_time > expire_time:
                    expired_keys.append(cache_key)

            for cache_key in expired_keys:
                await self._delete_from_memory(cache_key)

            # 清理磁盘缓存
            try:
                cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
            except OSError as e:
                print(f"Failed to list disk cache directory: {e}")
                return

            for meta_file in cache_files:
                cache_key = meta_file.replace('.meta', '')
                meta_path = os.path.join(self.disk_cache_dir, meta_file)

                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)

                    if current_time > meta['expire_time']:
                        await self._delete_from_disk(cache_key)

                except (IOError, json.JSONDecodeError) as e:
                    print(f"Failed to read cache meta: {e}")
                    continue

    def get_stats(self) -> dict:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        total_requests = (self.stats['memory_hits'] +
                         self.stats['disk_hits'] +
                         self.stats['misses'])

        hit_rate = ((self.stats['memory_hits'] + self.stats['disk_hits']) /
                   total_requests * 100 if total_requests > 0 else 0)

        return {
            **self.stats,
            'memory_cache_size': self._current_memory_size,
            'disk_cache_size': self._current_disk_size,
            'memory_cache_items': len(self._memory_cache),
            'hit_rate': f"{hit_rate:.2f}%"
        }

    async def warmup(self, urls: List[Tuple[str, bytes, Optional[int]]]):
        """
        缓存预热

        Args:
            urls: URL 列表，每个元素为 (url, data, ttl) 元组
        """
        for url, data, ttl in urls:
            try:
                await self.set(url, data, ttl=ttl)
            except Exception as e:
                print(f"Failed to warmup cache for {url}: {e}")

    async def delete(self, url: str, method: str = 'GET', headers: dict = None):
        """
        删除指定缓存

        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头
        """
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            # 从内存删除
            await self._delete_from_memory(cache_key)

            # 从磁盘删除
            await self._delete_from_disk(cache_key)

    async def exists(self, url: str, method: str = 'GET', headers: dict = None) -> bool:
        """
        检查缓存是否存在

        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头

        Returns:
            缓存是否存在
        """
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            # 检查内存缓存
            if cache_key in self._memory_cache:
                _, expire_time, _ = self._memory_cache[cache_key]
                return time.time() < expire_time

            # 检查磁盘缓存
            meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)

                return time.time() < meta['expire_time']

            except FileNotFoundError:
                return False
            except (IOError, json.JSONDecodeError):
                return False

    async def get_cache_info(self, url: str, method: str = 'GET', headers: dict = None) -> Optional[dict]:
        """
        获取缓存信息

        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头

        Returns:
            缓存信息字典，如果不存在则返回 None
        """
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            # 检查内存缓存
            if cache_key in self._memory_cache:
                _, expire_time, size = self._memory_cache[cache_key]
                return {
                    'location': 'memory',
                    'size': size,
                    'expire_time': expire_time,
                    'remaining_ttl': max(0, expire_time - time.time())
                }

            # 检查磁盘缓存
            meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)

                return {
                    'location': 'disk',
                    'size': meta['size'],
                    'expire_time': meta['expire_time'],
                    'remaining_ttl': max(0, meta['expire_time'] - time.time()),
                    'created_at': meta['created_at']
                }

            except FileNotFoundError:
                return None
            except (IOError, json.JSONDecodeError):
                return None


# 使用示例
async def example_usage():
    """缓存管理器使用示例"""
    # 创建缓存管理器
    cache_manager = CacheManager(
        max_memory_cache_size=100 * 1024 * 1024,  # 100MB
        max_disk_cache_size=1024 * 1024 * 1024,   # 1GB
        default_ttl=3600,  # 1小时
        disk_cache_dir='./cache'
    )

    try:
        url = 'https://www.example.com/api/data'

        # 尝试从缓存获取
        cached_data = await cache_manager.get(url)

        if cached_data is not None:
            print(f"Cache hit! Data size: {len(cached_data)} bytes")
        else:
            print("Cache miss, fetching from server...")

            # 模拟从服务器获取数据
            data = b'Example data from server'

            # 设置缓存
            await cache_manager.set(url, data, ttl=1800)  # 30分钟
            print(f"Data cached: {len(data)} bytes")

        # 获取统计信息
        stats = cache_manager.get_stats()
        print(f"Cache stats: {stats}")

        # 缓存预热
        warmup_data = [
            ('https://www.example.com/page1', b'Page 1 data', 3600),
            ('https://www.example.com/page2', b'Page 2 data', 3600),
        ]
        await cache_manager.warmup(warmup_data)
        print("Cache warmup completed")

        # 检查缓存是否存在
        exists = await cache_manager.exists(url)
        print(f"Cache exists: {exists}")

        # 获取缓存信息
        info = await cache_manager.get_cache_info(url)
        print(f"Cache info: {info}")

        # 清理过期缓存
        await cache_manager.cleanup_expired()
        print("Expired cache cleaned")

    finally:
        # 清空所有缓存
        await cache_manager.clear_all()
        print("All cache cleared")


if __name__ == '__main__':
    import asyncio
    asyncio.run(example_usage())
