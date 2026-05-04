import asyncio
import time
import hashlib
import json
import os
import shutil
from collections import OrderedDict
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from loguru import logger


class CacheManager:

    def __init__(self,
                 max_memory_cache_size: int = 100 * 1024 * 1024,
                 max_disk_cache_size: int = 1024 * 1024 * 1024,
                 default_ttl: int = 3600,
                 disk_cache_dir: str = './cache'):
        self.max_memory_cache_size = max_memory_cache_size
        self.max_disk_cache_size = max_disk_cache_size
        self.default_ttl = default_ttl
        self.disk_cache_dir = disk_cache_dir

        self._memory_cache: OrderedDict[str, Tuple[bytes, float, int, str]] = OrderedDict()

        self._current_memory_size = 0
        self._current_disk_size = 0

        self._lock = asyncio.Lock()

        os.makedirs(disk_cache_dir, exist_ok=True)

        self._init_disk_cache_size()

        self.stats = {
            'memory_hits': 0,
            'disk_hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_cached_items': 0
        }

        logger.info(f"缓存管理器初始化完成 - 内存上限: {max_memory_cache_size / 1024 / 1024:.2f}MB, "
                   f"磁盘上限: {max_disk_cache_size / 1024 / 1024:.2f}MB, "
                   f"默认TTL: {default_ttl}秒")

    def _init_disk_cache_size(self):
        try:
            total_size = 0
            if os.path.exists(self.disk_cache_dir):
                for filename in os.listdir(self.disk_cache_dir):
                    if filename.endswith('.cache'):
                        filepath = os.path.join(self.disk_cache_dir, filename)
                        total_size += os.path.getsize(filepath)
            self._current_disk_size = total_size
            logger.debug(f"磁盘缓存初始大小: {total_size / 1024 / 1024:.2f}MB")
        except Exception as e:
            logger.warning(f"计算磁盘缓存大小失败: {e}")
            self._current_disk_size = 0

    def _generate_cache_key(self, url: str, method: str = 'GET', headers: Optional[Dict] = None) -> str:
        key_data = f"{method.upper()}:{url}"

        if headers:
            important_headers = ['accept', 'accept-encoding', 'accept-language', 'content-type']
            for header in important_headers:
                header_lower = header.lower()
                if header_lower in {k.lower(): k for k in headers.keys()}:
                    original_key = next((k for k in headers.keys() if k.lower() == header_lower), None)
                    if original_key:
                        key_data += f":{header_lower}={headers[original_key]}"

        return hashlib.md5(key_data.encode('utf-8')).hexdigest()

    async def get(self,
                 url: str,
                 method: str = 'GET',
                 headers: Optional[Dict] = None) -> Optional[Tuple[bytes, str]]:
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            if cache_key in self._memory_cache:
                data, expire_time, size, content_type = self._memory_cache[cache_key]

                if time.time() < expire_time:
                    self._memory_cache.move_to_end(cache_key)
                    self.stats['memory_hits'] += 1
                    logger.debug(f"内存缓存命中: {url[:50]}...")
                    return (data, content_type)
                else:
                    await self._delete_from_memory(cache_key)
                    logger.debug(f"内存缓存过期: {url[:50]}...")

            disk_result = await self._get_from_disk(cache_key)

            if disk_result is not None:
                disk_data, disk_content_type = disk_result
                self.stats['disk_hits'] += 1
                logger.debug(f"磁盘缓存命中: {url[:50]}...")

                await self._set_to_memory(cache_key, disk_data, self.default_ttl, disk_content_type)

                return (disk_data, disk_content_type)

            self.stats['misses'] += 1
            logger.debug(f"缓存未命中: {url[:50]}...")
            return None

    async def set(self,
                 url: str,
                 data: bytes,
                 method: str = 'GET',
                 headers: Optional[Dict] = None,
                 ttl: Optional[int] = None,
                 cache_to_disk: bool = True,
                 content_type: str = ''):
        if not data:
            logger.warning(f"尝试缓存空数据: {url[:50]}...")
            return

        cache_key = self._generate_cache_key(url, method, headers)
        ttl = ttl or self.default_ttl

        async with self._lock:
            await self._set_to_memory(cache_key, data, ttl, content_type)

            if cache_to_disk:
                asyncio.create_task(self._set_to_disk_async(cache_key, data, ttl, content_type))

            logger.debug(f"缓存设置成功: {url[:50]}... (大小: {len(data)} 字节, TTL: {ttl}秒)")

    async def _set_to_memory(self, cache_key: str, data: bytes, ttl: int, content_type: str = ''):
        data_size = len(data)

        if data_size > self.max_memory_cache_size:
            logger.warning(f"数据大小 ({data_size} 字节) 超过内存缓存上限，跳过内存缓存")
            return

        while self._current_memory_size + data_size > self.max_memory_cache_size:
            if not await self._evict_lru_memory():
                logger.warning("无法腾出足够内存空间，跳过内存缓存")
                return

        if cache_key in self._memory_cache:
            _, _, old_size, _ = self._memory_cache[cache_key]
            self._current_memory_size -= old_size
            del self._memory_cache[cache_key]
        else:
            self.stats['total_cached_items'] += 1

        expire_time = time.time() + ttl
        self._memory_cache[cache_key] = (data, expire_time, data_size, content_type)
        self._memory_cache.move_to_end(cache_key)
        self._current_memory_size += data_size

    async def _set_to_disk_async(self, cache_key: str, data: bytes, ttl: int, content_type: str = ''):
        data_size = len(data)

        if data_size > self.max_disk_cache_size:
            return

        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            def _write():
                with open(cache_file, 'wb') as f:
                    f.write(data)
                meta = {
                    'expire_time': time.time() + ttl,
                    'size': data_size,
                    'created_at': datetime.now().isoformat(),
                    'content_type': content_type
                }
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False)

            await asyncio.to_thread(_write)
            self._current_disk_size += data_size

        except Exception as e:
            logger.error(f"写入磁盘缓存失败: {e}")
            for filepath in [cache_file, meta_file]:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass

    async def _get_from_disk(self, cache_key: str) -> Optional[Tuple[bytes, str]]:
        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            def _read():
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if time.time() > meta['expire_time']:
                    return None, None, True
                with open(cache_file, 'rb') as f:
                    return f.read(), meta.get('content_type', ''), False

            data, content_type, expired = await asyncio.to_thread(_read)

            if expired:
                await self._delete_from_disk(cache_key)
                return None

            if data is not None:
                return (data, content_type)

        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            await self._delete_from_disk(cache_key)
            return None
        except Exception as e:
            logger.warning(f"读取磁盘缓存失败: {e}")
            return None

    async def _evict_lru_memory(self) -> bool:
        if not self._memory_cache:
            return False

        lru_key, _ = self._memory_cache.popitem(last=False)
        _, _, size, _ = _
        self._current_memory_size -= size
        self.stats['total_cached_items'] -= 1
        self.stats['evictions'] += 1
        logger.debug(f"LRU 淘汰内存缓存: {lru_key[:16]}...")

        return True

    async def _evict_lru_disk(self) -> bool:
        try:
            cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
        except Exception as e:
            logger.error(f"扫描磁盘缓存目录失败: {e}")
            return False

        if not cache_files:
            return False

        oldest_time = float('inf')
        oldest_key = None

        for meta_file in cache_files:
            cache_key = meta_file.replace('.meta', '')
            meta_path = os.path.join(self.disk_cache_dir, meta_file)

            try:
                def _read_meta(p=meta_path):
                    with open(p, 'r', encoding='utf-8') as f:
                        return json.load(f)

                meta = await asyncio.to_thread(_read_meta)

                last_access = meta.get('last_access',
                                       datetime.fromisoformat(meta['created_at']).timestamp())

                if last_access < oldest_time:
                    oldest_time = last_access
                    oldest_key = cache_key

            except Exception:
                try:
                    await self._delete_from_disk(cache_key)
                except:
                    pass
                continue

        if oldest_key:
            await self._delete_from_disk(oldest_key)
            self.stats['evictions'] += 1
            logger.debug(f"LRU 淘汰磁盘缓存: {oldest_key[:16]}...")
            return True

        return False

    async def _delete_from_memory(self, cache_key: str):
        if cache_key in self._memory_cache:
            _, _, size, _ = self._memory_cache[cache_key]
            del self._memory_cache[cache_key]
            self._current_memory_size -= size
            self.stats['total_cached_items'] -= 1

    async def _delete_from_disk(self, cache_key: str):
        cache_file = os.path.join(self.disk_cache_dir, f"{cache_key}.cache")
        meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")

        try:
            if os.path.exists(meta_file):
                def _read_and_delete():
                    size = 0
                    try:
                        with open(meta_file, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        size = meta.get('size', 0)
                    except:
                        pass
                    for fp in [cache_file, meta_file]:
                        if os.path.exists(fp):
                            os.remove(fp)
                    return size

                size = await asyncio.to_thread(_read_and_delete)
                self._current_disk_size -= size

        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"删除磁盘缓存失败: {e}")

    async def delete(self, url: str, method: str = 'GET', headers: Optional[Dict] = None):
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            await self._delete_from_memory(cache_key)
            await self._delete_from_disk(cache_key)

            logger.debug(f"缓存已删除: {url[:50]}...")

    async def cleanup_expired(self):
        async with self._lock:
            current_time = time.time()
            expired_count = 0

            expired_keys = []
            for cache_key, (_, expire_time, _, _) in self._memory_cache.items():
                if current_time > expire_time:
                    expired_keys.append(cache_key)

            for cache_key in expired_keys:
                await self._delete_from_memory(cache_key)
                expired_count += 1

            try:
                cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
            except Exception as e:
                logger.error(f"扫描磁盘缓存目录失败: {e}")
                cache_files = []

            for meta_file in cache_files:
                cache_key = meta_file.replace('.meta', '')
                meta_path = os.path.join(self.disk_cache_dir, meta_file)

                try:
                    def _check_expired(p=meta_path, ct=current_time):
                        with open(p, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        return ct > meta.get('expire_time', 0)

                    is_expired = await asyncio.to_thread(_check_expired)
                    if is_expired:
                        await self._delete_from_disk(cache_key)
                        expired_count += 1

                except Exception:
                    try:
                        await self._delete_from_disk(cache_key)
                        expired_count += 1
                    except:
                        pass

            if expired_count > 0:
                logger.info(f"清理过期缓存完成，共清理 {expired_count} 个缓存项")

    async def clear_all(self):
        async with self._lock:
            memory_items = len(self._memory_cache)
            self._memory_cache.clear()
            self._current_memory_size = 0

            disk_items = 0
            try:
                if os.path.exists(self.disk_cache_dir):
                    disk_items = len([f for f in os.listdir(self.disk_cache_dir) if f.endswith('.cache')])
                    await asyncio.to_thread(shutil.rmtree, self.disk_cache_dir)
                    await asyncio.to_thread(os.makedirs, self.disk_cache_dir, True)
            except Exception as e:
                logger.error(f"清空磁盘缓存失败: {e}")
                try:
                    os.makedirs(self.disk_cache_dir, exist_ok=True)
                except:
                    pass

            self._current_disk_size = 0
            self.stats['total_cached_items'] = 0

            logger.info(f"清空所有缓存完成 - 内存: {memory_items} 项, 磁盘: {disk_items} 项")

    def get_stats(self) -> dict:
        total_requests = (self.stats['memory_hits'] +
                         self.stats['disk_hits'] +
                         self.stats['misses'])

        hit_rate = ((self.stats['memory_hits'] + self.stats['disk_hits']) /
                   total_requests * 100 if total_requests > 0 else 0)

        return {
            **self.stats,
            'memory_cache_size': self._current_memory_size,
            'memory_cache_size_mb': round(self._current_memory_size / 1024 / 1024, 2),
            'disk_cache_size': self._current_disk_size,
            'disk_cache_size_mb': round(self._current_disk_size / 1024 / 1024, 2),
            'memory_cache_items': len(self._memory_cache),
            'max_memory_cache_size': self.max_memory_cache_size,
            'max_disk_cache_size': self.max_disk_cache_size,
            'hit_rate': f"{hit_rate:.2f}%",
            'total_requests': total_requests
        }

    async def get_cache_info(self, url: str, method: str = 'GET', headers: Optional[Dict] = None) -> Optional[Dict]:
        cache_key = self._generate_cache_key(url, method, headers)

        async with self._lock:
            if cache_key in self._memory_cache:
                data, expire_time, size, content_type = self._memory_cache[cache_key]
                return {
                    'location': 'memory',
                    'size': size,
                    'expire_time': expire_time,
                    'remaining_ttl': max(0, expire_time - time.time()),
                    'content_type': content_type
                }

            meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")
            try:
                def _read_info(p=meta_file):
                    with open(p, 'r', encoding='utf-8') as f:
                        return json.load(f)

                meta = await asyncio.to_thread(_read_info)
                return {
                    'location': 'disk',
                    'size': meta.get('size', 0),
                    'expire_time': meta.get('expire_time', 0),
                    'remaining_ttl': max(0, meta.get('expire_time', 0) - time.time()),
                    'content_type': meta.get('content_type', ''),
                    'created_at': meta.get('created_at', '')
                }
            except:
                return None

    async def warmup(self, urls: list, ttl: Optional[int] = None):
        import aiohttp

        ttl = ttl or self.default_ttl
        success_count = 0
        fail_count = 0

        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in urls:
                tasks.append(self._warmup_url(session, url, ttl))
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    fail_count += 1
                elif r:
                    success_count += 1
                else:
                    pass

        logger.info(f"缓存预热完成 - 成功: {success_count}, 失败: {fail_count}")

    async def _warmup_url(self, session, url: str, ttl: int) -> bool:
        try:
            cached = await self.get(url)
            if cached is not None:
                return False

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.read()
                    ct = response.headers.get('Content-Type', '')
                    await self.set(url, data, ttl=ttl, content_type=ct)
                    return True
                return False
        except Exception:
            return False

    def __repr__(self) -> str:
        return (f"CacheManager(memory_items={len(self._memory_cache)}, "
                f"memory_size={self._current_memory_size / 1024 / 1024:.2f}MB, "
                f"disk_size={self._current_disk_size / 1024 / 1024:.2f}MB)")
