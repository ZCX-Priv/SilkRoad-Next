"""
缓存管理模块

功能：
1. 内存缓存与磁盘缓存
2. 缓存过期管理
3. LRU 淘汰策略
4. 缓存大小限制
5. 线程安全操作
"""

import asyncio
import time
import hashlib
import json
import os
import shutil
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from loguru import logger


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
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 创建磁盘缓存目录
        os.makedirs(disk_cache_dir, exist_ok=True)
        
        # 初始化时计算磁盘缓存大小
        self._init_disk_cache_size()
        
        # 统计信息
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
        """
        初始化时计算磁盘缓存大小
        """
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
    
    def _generate_cache_key(self, url: str, method: str = 'GET', headers: dict = None) -> str:
        """
        生成缓存键
        
        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头
            
        Returns:
            缓存键（MD5 哈希）
        """
        # 组合 URL、方法和关键请求头
        key_data = f"{method.upper()}:{url}"
        
        if headers:
            # 只包含影响响应的请求头
            important_headers = ['accept', 'accept-encoding', 'accept-language', 'content-type']
            for header in important_headers:
                header_lower = header.lower()
                if header_lower in {k.lower(): k for k in headers.keys()}:
                    # 找到原始键（可能大小写不同）
                    original_key = next((k for k in headers.keys() if k.lower() == header_lower), None)
                    if original_key:
                        key_data += f":{header_lower}={headers[original_key]}"
        
        # 生成 MD5 哈希
        return hashlib.md5(key_data.encode('utf-8')).hexdigest()
    
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
                    logger.debug(f"内存缓存命中: {url[:50]}...")
                    return data
                else:
                    # 过期，删除缓存
                    await self._delete_from_memory(cache_key)
                    logger.debug(f"内存缓存过期: {url[:50]}...")
            
            # 2. 尝试从磁盘缓存获取
            disk_data = await self._get_from_disk(cache_key)
            
            if disk_data is not None:
                # 更新 LRU 记录
                self._lru_record[cache_key] = time.time()
                self.stats['disk_hits'] += 1
                logger.debug(f"磁盘缓存命中: {url[:50]}...")
                
                # 将磁盘缓存提升到内存缓存
                await self._set_to_memory(cache_key, disk_data, self.default_ttl)
                
                return disk_data
            
            # 3. 缓存未命中
            self.stats['misses'] += 1
            logger.debug(f"缓存未命中: {url[:50]}...")
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
        if not data:
            logger.warning(f"尝试缓存空数据: {url[:50]}...")
            return
        
        cache_key = self._generate_cache_key(url, method, headers)
        ttl = ttl or self.default_ttl
        
        async with self._lock:
            # 1. 设置内存缓存
            await self._set_to_memory(cache_key, data, ttl)
            
            # 2. 设置磁盘缓存
            if cache_to_disk:
                await self._set_to_disk(cache_key, data, ttl)
            
            logger.debug(f"缓存设置成功: {url[:50]}... (大小: {len(data)} 字节, TTL: {ttl}秒)")
    
    async def _set_to_memory(self, cache_key: str, data: bytes, ttl: int):
        """
        设置内存缓存
        
        Args:
            cache_key: 缓存键
            data: 缓存数据
            ttl: 过期时间（秒）
        """
        # 检查是否需要清理空间
        data_size = len(data)
        
        # 如果单个数据超过内存缓存上限，不缓存到内存
        if data_size > self.max_memory_cache_size:
            logger.warning(f"数据大小 ({data_size} 字节) 超过内存缓存上限，跳过内存缓存")
            return
        
        # 淘汰旧缓存直到有足够空间
        while self._current_memory_size + data_size > self.max_memory_cache_size:
            if not await self._evict_lru_memory():
                # 无法淘汰更多缓存，跳过内存缓存
                logger.warning("无法腾出足够内存空间，跳过内存缓存")
                return
        
        # 如果键已存在，先删除旧数据
        if cache_key in self._memory_cache:
            _, _, old_size = self._memory_cache[cache_key]
            self._current_memory_size -= old_size
        else:
            self.stats['total_cached_items'] += 1
        
        # 设置缓存
        expire_time = time.time() + ttl
        self._memory_cache[cache_key] = (data, expire_time, data_size)
        self._lru_record[cache_key] = time.time()
        self._current_memory_size += data_size
    
    async def _set_to_disk(self, cache_key: str, data: bytes, ttl: int):
        """
        设置磁盘缓存
        
        Args:
            cache_key: 缓存键
            data: 缓存数据
            ttl: 过期时间（秒）
        """
        # 检查磁盘空间
        data_size = len(data)
        
        # 如果单个数据超过磁盘缓存上限，不缓存到磁盘
        if data_size > self.max_disk_cache_size:
            logger.warning(f"数据大小 ({data_size} 字节) 超过磁盘缓存上限，跳过磁盘缓存")
            return
        
        # 淘汰旧缓存直到有足够空间
        while self._current_disk_size + data_size > self.max_disk_cache_size:
            if not await self._evict_lru_disk():
                # 无法淘汰更多缓存，跳过磁盘缓存
                logger.warning("无法腾出足够磁盘空间，跳过磁盘缓存")
                return
        
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
                'created_at': datetime.now().isoformat(),
                'last_access': time.time()
            }
            
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            self._current_disk_size += data_size
            
        except Exception as e:
            logger.error(f"写入磁盘缓存失败: {e}")
            # 清理可能已写入的部分文件
            for filepath in [cache_file, meta_file]:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
    
    async def _get_from_disk(self, cache_key: str) -> Optional[bytes]:
        """
        从磁盘获取缓存
        
        Args:
            cache_key: 缓存键
            
        Returns:
            缓存数据，如果不存在或已过期则返回 None
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
            
            # 更新最后访问时间
            meta['last_access'] = time.time()
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            # 读取缓存数据
            with open(cache_file, 'rb') as f:
                return f.read()
                
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            # 元数据损坏，删除缓存
            await self._delete_from_disk(cache_key)
            return None
        except Exception as e:
            logger.warning(f"读取磁盘缓存失败: {e}")
            return None
    
    async def _evict_lru_memory(self) -> bool:
        """
        淘汰最近最少使用的内存缓存
        
        Returns:
            是否成功淘汰了缓存
        """
        if not self._lru_record:
            return False
        
        # 找到最久未使用的缓存键（只在内存缓存中存在的键）
        memory_keys = set(self._memory_cache.keys())
        lru_keys = {k: v for k, v in self._lru_record.items() if k in memory_keys}
        
        if not lru_keys:
            return False
        
        lru_key = min(lru_keys, key=lru_keys.get)
        
        # 删除缓存
        await self._delete_from_memory(lru_key)
        self.stats['evictions'] += 1
        logger.debug(f"LRU 淘汰内存缓存: {lru_key[:16]}...")
        
        return True
    
    async def _evict_lru_disk(self) -> bool:
        """
        淘汰最近最少使用的磁盘缓存
        
        Returns:
            是否成功淘汰了缓存
        """
        # 扫描磁盘缓存目录
        try:
            cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
        except Exception as e:
            logger.error(f"扫描磁盘缓存目录失败: {e}")
            return False
        
        if not cache_files:
            return False
        
        # 找到最旧/最少访问的缓存
        oldest_time = float('inf')
        oldest_key = None
        
        for meta_file in cache_files:
            cache_key = meta_file.replace('.meta', '')
            meta_path = os.path.join(self.disk_cache_dir, meta_file)
            
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                # 使用最后访问时间或创建时间
                last_access = meta.get('last_access', 
                                       datetime.fromisoformat(meta['created_at']).timestamp())
                
                if last_access < oldest_time:
                    oldest_time = last_access
                    oldest_key = cache_key
                    
            except Exception:
                # 元数据损坏，删除该缓存
                try:
                    await self._delete_from_disk(cache_key)
                except:
                    pass
                continue
        
        # 删除最旧的缓存
        if oldest_key:
            await self._delete_from_disk(oldest_key)
            self.stats['evictions'] += 1
            logger.debug(f"LRU 淘汰磁盘缓存: {oldest_key[:16]}...")
            return True
        
        return False
    
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
            if os.path.exists(meta_file):
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                self._current_disk_size -= meta.get('size', 0)
            
            # 删除文件
            for filepath in [cache_file, meta_file]:
                if os.path.exists(filepath):
                    os.remove(filepath)
            
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"删除磁盘缓存失败: {e}")
    
    async def delete(self, url: str, method: str = 'GET', headers: dict = None):
        """
        删除指定 URL 的缓存
        
        Args:
            url: 请求 URL
            method: 请求方法
            headers: 请求头
        """
        cache_key = self._generate_cache_key(url, method, headers)
        
        async with self._lock:
            # 删除内存缓存
            await self._delete_from_memory(cache_key)
            
            # 删除磁盘缓存
            await self._delete_from_disk(cache_key)
            
            logger.debug(f"缓存已删除: {url[:50]}...")
    
    async def cleanup_expired(self):
        """
        清理过期缓存
        """
        async with self._lock:
            current_time = time.time()
            expired_count = 0
            
            # 清理内存缓存
            expired_keys = []
            for cache_key, (_, expire_time, _) in self._memory_cache.items():
                if current_time > expire_time:
                    expired_keys.append(cache_key)
            
            for cache_key in expired_keys:
                await self._delete_from_memory(cache_key)
                expired_count += 1
            
            # 清理磁盘缓存
            try:
                cache_files = [f for f in os.listdir(self.disk_cache_dir) if f.endswith('.meta')]
            except Exception as e:
                logger.error(f"扫描磁盘缓存目录失败: {e}")
                cache_files = []
            
            for meta_file in cache_files:
                cache_key = meta_file.replace('.meta', '')
                meta_path = os.path.join(self.disk_cache_dir, meta_file)
                
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    
                    if current_time > meta['expire_time']:
                        await self._delete_from_disk(cache_key)
                        expired_count += 1
                        
                except Exception:
                    # 元数据损坏，删除该缓存
                    try:
                        await self._delete_from_disk(cache_key)
                        expired_count += 1
                    except:
                        pass
            
            if expired_count > 0:
                logger.info(f"清理过期缓存完成，共清理 {expired_count} 个缓存项")
    
    async def clear_all(self):
        """
        清空所有缓存
        """
        async with self._lock:
            # 清空内存缓存
            memory_items = len(self._memory_cache)
            self._memory_cache.clear()
            self._lru_record.clear()
            self._current_memory_size = 0
            
            # 清空磁盘缓存
            disk_items = 0
            try:
                if os.path.exists(self.disk_cache_dir):
                    # 计算磁盘缓存项数量
                    disk_items = len([f for f in os.listdir(self.disk_cache_dir) if f.endswith('.cache')])
                    
                    # 删除并重建目录
                    shutil.rmtree(self.disk_cache_dir)
                    os.makedirs(self.disk_cache_dir, exist_ok=True)
            except Exception as e:
                logger.error(f"清空磁盘缓存失败: {e}")
                # 尝试重建目录
                try:
                    os.makedirs(self.disk_cache_dir, exist_ok=True)
                except:
                    pass
            
            self._current_disk_size = 0
            
            # 重置统计
            self.stats['total_cached_items'] = 0
            
            logger.info(f"清空所有缓存完成 - 内存: {memory_items} 项, 磁盘: {disk_items} 项")
    
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
            'memory_cache_size_mb': round(self._current_memory_size / 1024 / 1024, 2),
            'disk_cache_size': self._current_disk_size,
            'disk_cache_size_mb': round(self._current_disk_size / 1024 / 1024, 2),
            'memory_cache_items': len(self._memory_cache),
            'max_memory_cache_size': self.max_memory_cache_size,
            'max_disk_cache_size': self.max_disk_cache_size,
            'hit_rate': f"{hit_rate:.2f}%",
            'total_requests': total_requests
        }
    
    async def get_cache_info(self, url: str, method: str = 'GET', headers: dict = None) -> Optional[dict]:
        """
        获取指定 URL 的缓存信息
        
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
                data, expire_time, size = self._memory_cache[cache_key]
                return {
                    'location': 'memory',
                    'size': size,
                    'expire_time': expire_time,
                    'remaining_ttl': max(0, expire_time - time.time()),
                    'last_access': self._lru_record.get(cache_key, 0)
                }
            
            # 检查磁盘缓存
            meta_file = os.path.join(self.disk_cache_dir, f"{cache_key}.meta")
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                return {
                    'location': 'disk',
                    'size': meta.get('size', 0),
                    'expire_time': meta.get('expire_time', 0),
                    'remaining_ttl': max(0, meta.get('expire_time', 0) - time.time()),
                    'last_access': meta.get('last_access', 0),
                    'created_at': meta.get('created_at', '')
                }
            except:
                return None
    
    async def warmup(self, urls: list, ttl: Optional[int] = None):
        """
        缓存预热 - 预加载指定 URL 列表的数据
        
        Args:
            urls: URL 列表
            ttl: 缓存过期时间
        """
        import aiohttp
        
        ttl = ttl or self.default_ttl
        success_count = 0
        fail_count = 0
        
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    # 检查缓存是否已存在
                    cached = await self.get(url)
                    if cached is not None:
                        logger.debug(f"缓存预热跳过（已存在）: {url[:50]}...")
                        continue
                    
                    # 获取数据
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status == 200:
                            data = await response.read()
                            await self.set(url, data, ttl=ttl)
                            success_count += 1
                            logger.debug(f"缓存预热成功: {url[:50]}...")
                        else:
                            fail_count += 1
                            logger.warning(f"缓存预热失败（状态码 {response.status}）: {url[:50]}...")
                            
                except Exception as e:
                    fail_count += 1
                    logger.warning(f"缓存预热失败: {url[:50]}... - {e}")
        
        logger.info(f"缓存预热完成 - 成功: {success_count}, 失败: {fail_count}")
    
    def __repr__(self) -> str:
        return (f"CacheManager(memory_items={len(self._memory_cache)}, "
                f"memory_size={self._current_memory_size / 1024 / 1024:.2f}MB, "
                f"disk_size={self._current_disk_size / 1024 / 1024:.2f}MB)")
