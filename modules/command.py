"""
控制台命令模块

提供 RESTful 风格的管理接口，用于管理和监控代理服务。

功能特性：
- 服务启动/暂停/退出控制
- 系统状态监控（CPU、内存、连接数）
- 缓存清理
- JSON 格式响应

Author: SilkRoad-Next Team
Version: 1.0.0
"""

import asyncio
import os
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from loguru import logger as loguru_logger

import psutil

from modules.exit import GracefulExit


class CommandHandler:
    """
    命令处理器

    提供 RESTful 风格的管理接口，用于管理和监控代理服务。
    作为 ProxyServer 的内部模块运行，不独立启动服务器。

    Attributes:
        proxy: 代理服务器实例
        config: 配置管理器实例
        logger: 日志记录器实例
        start_time: 服务启动时间戳
    """

    def __init__(self, proxy_server, config, logger):
        """
        初始化命令处理器

        Args:
            proxy_server: 代理服务器实例
            config: 配置管理器实例
            logger: 日志记录器实例
        """
        self.proxy = proxy_server
        self.config = config
        self.logger = logger or loguru_logger

        self.start_time = time.time()

        self.logger.info("命令处理器初始化完成")

    async def handle_request(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        处理命令请求的统一入口

        Args:
            path: 请求路径（如 /command/status）
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        path = path.rstrip('/')

        if path == '/command':
            return await self._list_commands()
        elif path == '/command/status':
            return await self._get_status()
        elif path == '/command/start':
            return await self._start_service()
        elif path == '/command/pause':
            return await self._pause_service()
        elif path == '/command/resume':
            return await self._resume_service()
        elif path == '/command/exit':
            return await self._exit_service()
        elif path == '/command/clear':
            return await self._clear_cache()
        elif path == '/command/stream/stats':
            return await self._get_stream_stats()
        elif path == '/command/stream/stats/reset':
            return await self._reset_stream_stats()
        elif path == '/command/stream/rate-limit':
            return await self._get_rate_limit_status()
        elif path.startswith('/command/stream/rate-limit/set'):
            return await self._set_rate_limit(path, method)
        elif path == '/command/media/cache':
            return await self._get_media_cache_status()
        elif path == '/command/media/cache/clear':
            return await self._clear_media_cache()
        elif path.startswith('/command/cache/delete'):
            return await self._delete_cache_item(path)
        elif path.startswith('/command/cache/info'):
            return await self._get_cache_info(path)
        elif path == '/command/cache/warmup':
            return await self._cache_warmup()
        elif path == '/command/cache/stats':
            return await self._get_cache_stats()
        elif path == '/command/config/reload':
            return await self._reload_config()
        elif path == '/command/config/get':
            return await self._get_config()
        elif path.startswith('/command/config/get/'):
            return await self._get_config_key(path)
        elif path == '/command/config/set':
            return await self._set_config(method)
        elif path == '/command/config/save':
            return await self._save_config()
        elif path == '/command/config/export':
            return await self._export_config()
        elif path == '/command/blacklist/stats':
            return await self._get_blacklist_stats()
        elif path == '/command/blacklist/list':
            return await self._get_blacklist_list()
        elif path.startswith('/command/blacklist/add'):
            return await self._add_blacklist_item(path, method)
        elif path.startswith('/command/blacklist/remove'):
            return await self._remove_blacklist_item(path, method)
        elif path == '/command/blacklist/whitelist/list':
            return await self._get_whitelist_list()
        elif path.startswith('/command/blacklist/whitelist/add'):
            return await self._add_whitelist_item(path, method)
        elif path.startswith('/command/blacklist/whitelist/remove'):
            return await self._remove_whitelist_item(path, method)
        elif path == '/command/blacklist/reload':
            return await self._reload_blacklist()
        elif path == '/command/blacklist/clear':
            return await self._clear_blacklist()
        elif path == '/command/blacklist/export':
            return await self._export_blacklist()
        elif path == '/command/blacklist/check':
            return await self._check_blacklist()
        elif path == '/command/pool/status':
            return await self._get_pool_status()
        elif path.startswith('/command/pool/status/'):
            return await self._get_pool_status_by_host(path)
        elif path == '/command/pool/health':
            return await self._get_pool_health()
        elif path == '/command/pool/cleanup':
            return await self._cleanup_pool()
        else:
            return 404, {
                'status': 'error',
                'message': f'未知命令: {path}',
                'timestamp': time.time()
            }

    async def _list_commands(self) -> Tuple[int, Dict[str, Any]]:
        """
        列出所有可用命令

        Returns:
            (status_code, response_dict) 元组
        """
        commands = {
            '/command': {
                'method': 'GET',
                'description': '列出所有可用命令'
            },
            '/command/status': {
                'method': 'GET',
                'description': '查看系统状态（CPU、内存、连接数等）'
            },
            '/command/start': {
                'method': 'GET',
                'description': '启动或恢复代理服务'
            },
            '/command/pause': {
                'method': 'GET',
                'description': '暂停代理服务（停止接收新请求）'
            },
            '/command/resume': {
                'method': 'GET',
                'description': '恢复代理服务'
            },
            '/command/exit': {
                'method': 'GET',
                'description': '优雅退出程序（完成当前请求后退出）'
            },
            '/command/clear': {
                'method': 'GET',
                'description': '清除服务端文件缓存'
            },
            '/command/stream/stats': {
                'method': 'GET',
                'description': '获取流处理统计信息'
            },
            '/command/stream/stats/reset': {
                'method': 'POST',
                'description': '重置流处理统计信息'
            },
            '/command/stream/rate-limit': {
                'method': 'GET',
                'description': '获取流量限制状态'
            },
            '/command/stream/rate-limit/set': {
                'method': 'POST',
                'description': '设置流量限制参数'
            },
            '/command/media/cache': {
                'method': 'GET',
                'description': '获取媒体缓存状态（命中率、使用量等）'
            },
            '/command/media/cache/clear': {
                'method': 'POST',
                'description': '清除媒体内存缓存'
            },
            '/command/config/reload': {
                'method': 'POST',
                'description': '重新加载配置文件（热重载）'
            },
            '/command/config/get': {
                'method': 'GET',
                'description': '获取完整配置信息'
            },
            '/command/config/get/{key}': {
                'method': 'GET',
                'description': '获取指定配置项（支持点分隔符，如 /command/config/get/server.proxy.port）'
            },
            '/command/config/set': {
                'method': 'POST',
                'description': '设置配置项（需要请求体传递 key, value, save 参数）'
            },
            '/command/config/save': {
                'method': 'POST',
                'description': '保存当前配置到文件'
            },
            '/command/config/export': {
                'method': 'GET',
                'description': '导出完整配置为 JSON 格式'
            },
            '/command/cache/stats': {
                'method': 'GET',
                'description': '获取缓存管理器统计信息'
            },
            '/command/cache/delete?url=<url>': {
                'method': 'GET',
                'description': '删除指定 URL 的缓存'
            },
            '/command/cache/info?url=<url>': {
                'method': 'GET',
                'description': '获取指定 URL 的缓存详情'
            },
            '/command/cache/warmup': {
                'method': 'POST',
                'description': '手动触发缓存预热（预热配置中的热门资源）'
            },
            '/command/blacklist/stats': {
                'method': 'GET',
                'description': '获取黑名单统计信息'
            },
            '/command/blacklist/list?type=<type>': {
                'method': 'GET',
                'description': '获取黑名单列表（type: ip, ip_range, domain, url, url_pattern）'
            },
            '/command/blacklist/add?type=<type>&item=<item>': {
                'method': 'POST',
                'description': '添加黑名单项（type: ip, ip_range, domain, url, url_pattern）'
            },
            '/command/blacklist/remove?type=<type>&item=<item>': {
                'method': 'POST',
                'description': '移除黑名单项'
            },
            '/command/blacklist/whitelist/list?type=<type>': {
                'method': 'GET',
                'description': '获取白名单列表（type: ip, ip_range, domain）'
            },
            '/command/blacklist/whitelist/add?type=<type>&item=<item>': {
                'method': 'POST',
                'description': '添加白名单项'
            },
            '/command/blacklist/whitelist/remove?type=<type>&item=<item>': {
                'method': 'POST',
                'description': '移除白名单项'
            },
            '/command/blacklist/reload': {
                'method': 'POST',
                'description': '热重载黑名单配置'
            },
            '/command/blacklist/clear': {
                'method': 'POST',
                'description': '清空所有黑名单'
            },
            '/command/blacklist/export': {
                'method': 'GET',
                'description': '导出黑名单配置'
            },
            '/command/blacklist/check?ip=<ip>&url=<url>&domain=<domain>': {
                'method': 'GET',
                'description': '检查指定 IP/URL/域名是否被拦截'
            },
            '/command/pool/status': {
                'method': 'GET',
                'description': '获取连接池整体状态（连接数、复用率等）'
            },
            '/command/pool/status/{host:port}': {
                'method': 'GET',
                'description': '获取指定主机的连接池状态（如 /command/pool/status/example.com:443）'
            },
            '/command/pool/health': {
                'method': 'GET',
                'description': '获取连接池健康检查结果'
            },
            '/command/pool/cleanup': {
                'method': 'POST',
                'description': '手动清理连接池中的过期连接'
            }
        }

        return 200, {
            'status': 'success',
            'commands': commands,
            'timestamp': time.time()
        }

    async def _get_status(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取系统状态

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            uptime = time.time() - self.start_time
            uptime_str = self._format_uptime(uptime)

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            process = psutil.Process(os.getpid())
            process_memory = process.memory_info()

            status = {
                'status': 'success',
                'timestamp': time.time(),
                'service': {
                    'uptime': uptime,
                    'uptime_formatted': uptime_str,
                    'is_running': getattr(self.proxy, 'is_running', False),
                    'active_connections': getattr(self.proxy, 'active_connections', 0),
                    'start_time': self.start_time
                },
                'system': {
                    'cpu_percent': cpu_percent,
                    'cpu_count': psutil.cpu_count(),
                    'memory': {
                        'total': memory.total,
                        'available': memory.available,
                        'used': memory.used,
                        'percent': memory.percent
                    },
                    'disk': {
                        'total': disk.total,
                        'used': disk.used,
                        'free': disk.free,
                        'percent': disk.percent
                    }
                },
                'process': {
                    'pid': os.getpid(),
                    'memory_rss': process_memory.rss,
                    'memory_vms': process_memory.vms,
                    'memory_percent': process.memory_percent(),
                    'num_threads': process.num_threads(),
                    'num_fds': self._get_num_fds(process)
                }
            }

            return 200, status

        except Exception as e:
            self.logger.error(f"获取系统状态时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取系统状态失败: {str(e)}',
                'timestamp': time.time()
            }

    async def _start_service(self) -> Tuple[int, Dict[str, Any]]:
        """
        启动服务

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not self.proxy.is_running:
                self.proxy.is_running = True
                self.logger.info("代理服务已启动")

                return 200, {
                    'status': 'success',
                    'message': '代理服务已启动',
                    'timestamp': time.time()
                }
            else:
                return 200, {
                    'status': 'success',
                    'message': '代理服务已在运行中',
                    'timestamp': time.time()
                }

        except Exception as e:
            self.logger.error(f"启动服务时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'启动服务失败: {str(e)}',
                'timestamp': time.time()
            }

    async def _pause_service(self) -> Tuple[int, Dict[str, Any]]:
        """
        暂停服务

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if self.proxy.is_running:
                self.proxy.is_running = False
                self.logger.info("代理服务已暂停")

                return 200, {
                    'status': 'success',
                    'message': '代理服务已暂停，正在处理的请求将继续完成',
                    'active_connections': getattr(self.proxy, 'active_connections', 0),
                    'timestamp': time.time()
                }
            else:
                return 200, {
                    'status': 'success',
                    'message': '代理服务已处于暂停状态',
                    'timestamp': time.time()
                }

        except Exception as e:
            self.logger.error(f"暂停服务时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'暂停服务失败: {str(e)}',
                'timestamp': time.time()
            }

    async def _resume_service(self) -> Tuple[int, Dict[str, Any]]:
        """
        恢复服务

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not self.proxy.is_running:
                self.proxy.is_running = True
                self.logger.info("代理服务已恢复")

                return 200, {
                    'status': 'success',
                    'message': '代理服务已恢复',
                    'timestamp': time.time()
                }
            else:
                return 200, {
                    'status': 'success',
                    'message': '代理服务已在运行中',
                    'timestamp': time.time()
                }

        except Exception as e:
            self.logger.error(f"恢复服务时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'恢复服务失败: {str(e)}',
                'timestamp': time.time()
            }

    async def _exit_service(self) -> Tuple[int, Dict[str, Any]]:
        """
        优雅退出

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            self.logger.info("接收到退出命令，准备优雅退出")

            task = asyncio.create_task(self._delayed_exit())
            GracefulExit.register_task(task)

            return 200, {
                'status': 'success',
                'message': '程序将在 1 秒后优雅退出',
                'active_connections': getattr(self.proxy, 'active_connections', 0),
                'timestamp': time.time()
            }

        except Exception as e:
            self.logger.error(f"处理退出命令时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'处理退出命令失败: {str(e)}',
                'timestamp': time.time()
            }

    async def _delayed_exit(self) -> None:
        """
        延迟退出

        延迟 1 秒后退出程序，给响应足够的时间返回给客户端。
        """
        try:
            await asyncio.sleep(1)

            self.logger.info("执行优雅退出...")

            os._exit(0)

        except Exception as e:
            self.logger.error(f"延迟退出时发生错误: {e}")
            os._exit(1)

    async def _clear_cache(self) -> Tuple[int, Dict[str, Any]]:
        """
        清除缓存

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            cache_dir = Path('cache')
            cleared_size = 0
            cleared_files = 0
            sse_cleared_streams = 0

            if cache_dir.exists():
                for file_path in cache_dir.rglob('*'):
                    if file_path.is_file():
                        try:
                            cleared_size += file_path.stat().st_size
                            cleared_files += 1
                        except OSError:
                            pass

                shutil.rmtree(cache_dir)
                self.logger.info(f"缓存已清除: {cleared_files} 个文件, "
                               f"{self._format_size(cleared_size)}")

            if self.proxy.flow_router and self.proxy.flow_router.stream_handler and self.proxy.flow_router.stream_handler.sse_handler:
                sse_connections = await self.proxy.flow_router.stream_handler.sse_handler.get_active_connections()
                for stream_id in list(sse_connections.keys()):
                    await self.proxy.flow_router.stream_handler.sse_handler.clear_cache(stream_id)
                    sse_cleared_streams += 1
                self.logger.info(f"SSE 缓存已清除: {sse_cleared_streams} 个流")

            if cleared_files > 0 or sse_cleared_streams > 0:
                return 200, {
                    'status': 'success',
                    'message': '缓存已清除',
                    'details': {
                        'cleared_files': cleared_files,
                        'cleared_size': cleared_size,
                        'cleared_size_formatted': self._format_size(cleared_size),
                        'sse_cleared_streams': sse_cleared_streams
                    },
                    'recommendation': '建议同时清除浏览器缓存以获得最佳效果',
                    'timestamp': time.time()
                }
            else:
                return 200, {
                    'status': 'success',
                    'message': '无需清除的缓存',
                    'timestamp': time.time()
                }

        except PermissionError as e:
            self.logger.error(f"清除缓存时权限不足: {e}")
            return 403, {
                'status': 'error',
                'message': f'权限不足，无法清除缓存: {str(e)}',
                'timestamp': time.time()
            }

        except Exception as e:
            self.logger.error(f"清除缓存时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'清除缓存失败: {str(e)}',
                'timestamp': time.time()
            }

    def _format_uptime(self, seconds: float) -> str:
        """
        格式化运行时间

        Args:
            seconds: 运行时间（秒）

        Returns:
            str: 格式化的时间字符串
        """
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分钟")
        if secs > 0 or not parts:
            parts.append(f"{secs}秒")

        return ''.join(parts)

    def _format_size(self, size: int) -> str:
        """
        格式化文件大小

        Args:
            size: 文件大小（字节）

        Returns:
            str: 格式化的大小字符串
        """
        size_float = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_float < 1024.0:
                return f"{size_float:.2f} {unit}"
            size_float /= 1024.0
        return f"{size_float:.2f} PB"

    def _get_num_fds(self, process: psutil.Process) -> int:
        """
        获取进程打开的文件描述符数量

        Args:
            process: psutil 进程对象

        Returns:
            int: 文件描述符或句柄数量
        """
        try:
            if os.name == 'nt':
                return process.num_handles()
            else:
                return process.num_fds()
        except (psutil.AccessDenied, AttributeError):
            return -1
    
    async def _get_media_cache_status(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取媒体缓存状态

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not (self.proxy.flow_router and self.proxy.flow_router.stream_handler and self.proxy.flow_router.stream_handler.media_handler):
                return 200, {
                    'status': 'success',
                    'message': '媒体处理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            cache_info = self.proxy.flow_router.stream_handler.media_handler.get_cache_info()
            media_stats = self.proxy.flow_router.stream_handler.media_handler.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'cache': {
                    'entries': cache_info['entries'],
                    'total_bytes': cache_info['total_bytes'],
                    'total_bytes_formatted': self._format_size(cache_info['total_bytes']),
                    'max_bytes': cache_info['max_bytes'],
                    'max_bytes_formatted': self._format_size(cache_info['max_bytes']),
                    'usage_percent': round(cache_info['usage_percent'], 2)
                },
                'statistics': {
                    'hits': cache_info['hits'],
                    'misses': cache_info['misses'],
                    'hit_rate': round(cache_info['hit_rate'], 2),
                    'total_media_streams': media_stats.get('total_media_streams', 0),
                    'range_requests': media_stats.get('range_requests', 0),
                    'normal_requests': media_stats.get('normal_requests', 0),
                    'bytes_streamed': media_stats.get('bytes_streamed', 0),
                    'bytes_streamed_formatted': self._format_size(media_stats.get('bytes_streamed', 0))
                },
                'config': {
                    'buffer_size': media_stats.get('buffer_size', 0),
                    'max_buffer_size': media_stats.get('max_buffer_size', 0),
                    'enable_range': media_stats.get('enable_range', False)
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取媒体缓存状态时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取媒体缓存状态失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _clear_media_cache(self) -> Tuple[int, Dict[str, Any]]:
        """
        清除媒体缓存

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not (self.proxy.flow_router and self.proxy.flow_router.stream_handler and self.proxy.flow_router.stream_handler.media_handler):
                return 200, {
                    'status': 'success',
                    'message': '媒体处理器未启用，无需清除',
                    'timestamp': time.time()
                }
            
            cleared_bytes = await self.proxy.flow_router.stream_handler.media_handler.clear_cache()
            
            self.logger.info(f"媒体缓存已清除: {self._format_size(cleared_bytes)}")
            
            return 200, {
                'status': 'success',
                'message': '媒体缓存已清除',
                'details': {
                    'cleared_bytes': cleared_bytes,
                    'cleared_bytes_formatted': self._format_size(cleared_bytes)
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"清除媒体缓存时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'清除媒体缓存失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_stream_stats(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取流处理统计信息

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not (self.proxy.flow_router and self.proxy.flow_router.stream_handler):
                return 200, {
                    'status': 'success',
                    'message': '流处理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            stream_stats = self.proxy.flow_router.stream_handler.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'statistics': stream_stats,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取流处理统计信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取流处理统计信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _reset_stream_stats(self) -> Tuple[int, Dict[str, Any]]:
        """
        重置流处理统计信息

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not (self.proxy.flow_router and self.proxy.flow_router.stream_handler):
                return 200, {
                    'status': 'success',
                    'message': '流处理器未启用',
                    'timestamp': time.time()
                }
            
            if hasattr(self.proxy.flow_router.stream_handler, 'reset_stats'):
                self.proxy.flow_router.stream_handler.reset_stats()
            
            return 200, {
                'status': 'success',
                'message': '流处理统计信息已重置',
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"重置流处理统计信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'重置流处理统计信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_rate_limit_status(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取流量限制状态

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'traffic_controller') or self.proxy.traffic_controller is None:
                return 200, {
                    'status': 'success',
                    'message': '流量控制器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            stats = await self.proxy.traffic_controller.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'rate_limit': stats,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取流量限制状态时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取流量限制状态失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _set_rate_limit(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        设置流量限制参数

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'traffic_controller') or self.proxy.traffic_controller is None:
                return 200, {
                    'status': 'success',
                    'message': '流量控制器未启用',
                    'timestamp': time.time()
                }
            
            return 200, {
                'status': 'success',
                'message': '流量限制参数设置接口（需要通过请求体传递参数）',
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"设置流量限制参数时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'设置流量限制参数失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _reload_config(self) -> Tuple[int, Dict[str, Any]]:
        """
        重新加载配置文件（热重载）

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            self.logger.info("开始重新加载配置文件...")
            
            await self.config.reload()
            
            self.logger.info("配置文件重新加载成功")
            
            return 200, {
                'status': 'success',
                'message': '配置文件已重新加载',
                'config_path': self.config.config_path,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"重新加载配置文件时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'重新加载配置文件失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_config(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取完整配置信息

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            config_dict = self.config.to_dict()
            
            return 200, {
                'status': 'success',
                'config': config_dict,
                'config_path': self.config.config_path,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取配置信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取配置信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_config_key(self, path: str) -> Tuple[int, Dict[str, Any]]:
        """
        获取指定配置项

        Args:
            path: 请求路径（如 /command/config/get/server.proxy.port）

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            key = path.replace('/command/config/get/', '')
            
            if not key:
                return 400, {
                    'status': 'error',
                    'message': '缺少配置项键名',
                    'timestamp': time.time()
                }
            
            value = self.config.get(key)
            
            if value is None:
                return 404, {
                    'status': 'error',
                    'message': f'配置项不存在: {key}',
                    'timestamp': time.time()
                }
            
            return 200, {
                'status': 'success',
                'key': key,
                'value': value,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取配置项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取配置项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _set_config(self, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        设置配置项

        Args:
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            return 200, {
                'status': 'success',
                'message': '配置项设置接口（需要通过请求体传递 key, value, save 参数）',
                'example': {
                    'key': 'server.proxy.port',
                    'value': 9090,
                    'save': True
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"设置配置项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'设置配置项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _save_config(self) -> Tuple[int, Dict[str, Any]]:
        """
        保存当前配置到文件

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            await self.config._save_config()
            
            self.logger.info("配置已保存到文件")
            
            return 200, {
                'status': 'success',
                'message': '配置已保存到文件',
                'config_path': self.config.config_path,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"保存配置文件时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'保存配置文件失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _export_config(self) -> Tuple[int, Dict[str, Any]]:
        """
        导出完整配置为 JSON 格式

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            config_dict = self.config.to_dict()
            
            return 200, {
                'status': 'success',
                'config': config_dict,
                'config_path': self.config.config_path,
                'export_time': time.time(),
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"导出配置时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'导出配置失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_blacklist_stats(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取黑名单统计信息

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            stats = self.proxy.blacklist_manager.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'statistics': stats,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取黑名单统计信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取黑名单统计信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_blacklist_list(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取黑名单列表

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            blacklist_types = ['ip', 'ip_range', 'domain', 'url', 'url_pattern']
            lists = {}
            
            for bt in blacklist_types:
                lists[bt] = self.proxy.blacklist_manager.get_blacklist(bt)
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'blacklists': lists,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取黑名单列表时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取黑名单列表失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _add_blacklist_item(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        添加黑名单项

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            item_type = params.get('type', [None])[0]
            item = params.get('item', [None])[0]
            
            if not item_type or not item:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: type 或 item',
                    'valid_types': ['ip', 'ip_range', 'domain', 'url', 'url_pattern'],
                    'example': '/command/blacklist/add?type=ip&item=192.168.1.100',
                    'timestamp': time.time()
                }
            
            if item_type not in ['ip', 'ip_range', 'domain', 'url', 'url_pattern']:
                return 400, {
                    'status': 'error',
                    'message': f'无效的类型: {item_type}',
                    'valid_types': ['ip', 'ip_range', 'domain', 'url', 'url_pattern'],
                    'timestamp': time.time()
                }
            
            item = urllib.parse.unquote(item)
            success = await self.proxy.blacklist_manager.add_to_blacklist(item, item_type)
            
            if success:
                self.logger.info(f"已添加黑名单项: {item_type} -> {item}")
                return 200, {
                    'status': 'success',
                    'message': f'已添加黑名单项',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            else:
                return 400, {
                    'status': 'error',
                    'message': f'添加黑名单项失败（可能是格式无效）',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"添加黑名单项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'添加黑名单项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _remove_blacklist_item(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        移除黑名单项

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            item_type = params.get('type', [None])[0]
            item = params.get('item', [None])[0]
            
            if not item_type or not item:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: type 或 item',
                    'valid_types': ['ip', 'ip_range', 'domain', 'url', 'url_pattern'],
                    'example': '/command/blacklist/remove?type=ip&item=192.168.1.100',
                    'timestamp': time.time()
                }
            
            item = urllib.parse.unquote(item)
            success = await self.proxy.blacklist_manager.remove_from_blacklist(item, item_type)
            
            if success:
                self.logger.info(f"已移除黑名单项: {item_type} -> {item}")
                return 200, {
                    'status': 'success',
                    'message': f'已移除黑名单项',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            else:
                return 400, {
                    'status': 'error',
                    'message': f'移除黑名单项失败',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"移除黑名单项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'移除黑名单项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_whitelist_list(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取白名单列表

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            whitelist_types = ['ip', 'ip_range', 'domain']
            lists = {}
            
            for wt in whitelist_types:
                lists[wt] = self.proxy.blacklist_manager.get_whitelist(wt)
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'whitelists': lists,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取白名单列表时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取白名单列表失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _add_whitelist_item(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        添加白名单项

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            item_type = params.get('type', [None])[0]
            item = params.get('item', [None])[0]
            
            if not item_type or not item:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: type 或 item',
                    'valid_types': ['ip', 'ip_range', 'domain'],
                    'example': '/command/blacklist/whitelist/add?type=ip&item=127.0.0.1',
                    'timestamp': time.time()
                }
            
            if item_type not in ['ip', 'ip_range', 'domain']:
                return 400, {
                    'status': 'error',
                    'message': f'无效的类型: {item_type}',
                    'valid_types': ['ip', 'ip_range', 'domain'],
                    'timestamp': time.time()
                }
            
            item = urllib.parse.unquote(item)
            success = await self.proxy.blacklist_manager.add_to_whitelist(item, item_type)
            
            if success:
                self.logger.info(f"已添加白名单项: {item_type} -> {item}")
                return 200, {
                    'status': 'success',
                    'message': f'已添加白名单项',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            else:
                return 400, {
                    'status': 'error',
                    'message': f'添加白名单项失败（可能是格式无效）',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"添加白名单项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'添加白名单项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _remove_whitelist_item(self, path: str, method: str) -> Tuple[int, Dict[str, Any]]:
        """
        移除白名单项

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            item_type = params.get('type', [None])[0]
            item = params.get('item', [None])[0]
            
            if not item_type or not item:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: type 或 item',
                    'valid_types': ['ip', 'ip_range', 'domain'],
                    'example': '/command/blacklist/whitelist/remove?type=ip&item=127.0.0.1',
                    'timestamp': time.time()
                }
            
            item = urllib.parse.unquote(item)
            success = await self.proxy.blacklist_manager.remove_from_whitelist(item, item_type)
            
            if success:
                self.logger.info(f"已移除白名单项: {item_type} -> {item}")
                return 200, {
                    'status': 'success',
                    'message': f'已移除白名单项',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            else:
                return 400, {
                    'status': 'error',
                    'message': f'移除白名单项失败',
                    'type': item_type,
                    'item': item,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"移除白名单项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'移除白名单项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _reload_blacklist(self) -> Tuple[int, Dict[str, Any]]:
        """
        热重载黑名单配置

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            success = await self.proxy.blacklist_manager.reload_config()
            
            if success:
                self.logger.info("黑名单配置已重新加载")
                return 200, {
                    'status': 'success',
                    'message': '黑名单配置已重新加载',
                    'timestamp': time.time()
                }
            else:
                return 500, {
                    'status': 'error',
                    'message': '黑名单配置重新加载失败',
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"重新加载黑名单配置时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'重新加载黑名单配置失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _clear_blacklist(self) -> Tuple[int, Dict[str, Any]]:
        """
        清空所有黑名单

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            await self.proxy.blacklist_manager.clear_all_blacklists()
            
            self.logger.info("所有黑名单已清空")
            
            return 200, {
                'status': 'success',
                'message': '所有黑名单已清空',
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"清空黑名单时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'清空黑名单失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _export_blacklist(self) -> Tuple[int, Dict[str, Any]]:
        """
        导出黑名单配置

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            config = await self.proxy.blacklist_manager.export_config()
            
            return 200, {
                'status': 'success',
                'config': config,
                'export_time': time.time(),
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"导出黑名单配置时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'导出黑名单配置失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _check_blacklist(self) -> Tuple[int, Dict[str, Any]]:
        """
        检查指定 IP/URL/域名是否被拦截

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'blacklist_manager') or self.proxy.blacklist_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '黑名单管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            return 200, {
                'status': 'success',
                'message': '黑名单检查接口',
                'usage': {
                    'check_ip': '/command/blacklist/check?ip=192.168.1.1',
                    'check_url': '/command/blacklist/check?url=/admin/config',
                    'check_domain': '/command/blacklist/check?domain=malicious.com',
                    'check_all': '/command/blacklist/check?ip=192.168.1.1&url=/admin&domain=example.com'
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"检查黑名单时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'检查黑名单失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _delete_cache_item(self, path: str) -> Tuple[int, Dict[str, Any]]:
        """
        删除指定缓存项

        Args:
            path: 请求路径

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'cache_manager') or self.proxy.cache_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '缓存管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            import urllib.parse
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            cache_key = params.get('key', [None])[0]
            
            if not cache_key:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: key',
                    'example': '/command/cache/delete?key=https://example.com/resource',
                    'timestamp': time.time()
                }
            
            cache_key = urllib.parse.unquote(cache_key)
            deleted = await self.proxy.cache_manager.delete(cache_key)
            
            if deleted:
                self.logger.info(f"已删除缓存项: {cache_key}")
                return 200, {
                    'status': 'success',
                    'message': '缓存项已删除',
                    'key': cache_key,
                    'timestamp': time.time()
                }
            else:
                return 404, {
                    'status': 'error',
                    'message': '缓存项不存在',
                    'key': cache_key,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"删除缓存项时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'删除缓存项失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_cache_info(self, path: str) -> Tuple[int, Dict[str, Any]]:
        """
        获取指定缓存项信息

        Args:
            path: 请求路径

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'cache_manager') or self.proxy.cache_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '缓存管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            import urllib.parse
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            
            cache_key = params.get('key', [None])[0]
            
            if not cache_key:
                return 400, {
                    'status': 'error',
                    'message': '缺少参数: key',
                    'example': '/command/cache/info?key=https://example.com/resource',
                    'timestamp': time.time()
                }
            
            cache_key = urllib.parse.unquote(cache_key)
            info = await self.proxy.cache_manager.get_info(cache_key)
            
            if info:
                return 200, {
                    'status': 'success',
                    'key': cache_key,
                    'info': info,
                    'timestamp': time.time()
                }
            else:
                return 404, {
                    'status': 'error',
                    'message': '缓存项不存在',
                    'key': cache_key,
                    'timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"获取缓存信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取缓存信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _cache_warmup(self) -> Tuple[int, Dict[str, Any]]:
        """
        缓存预热

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'cache_manager') or self.proxy.cache_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '缓存管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            return 200, {
                'status': 'success',
                'message': '缓存预热接口（需要通过请求体传递 urls 参数）',
                'example': {
                    'urls': [
                        'https://example.com/css/style.css',
                        'https://example.com/js/main.js',
                        'https://example.com/images/logo.png'
                    ]
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"缓存预热时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'缓存预热失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_cache_stats(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取缓存统计信息

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'cache_manager') or self.proxy.cache_manager is None:
                return 200, {
                    'status': 'success',
                    'message': '缓存管理器未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            stats = await self.proxy.cache_manager.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'statistics': stats,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取缓存统计信息时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取缓存统计信息失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_pool_status(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取连接池整体状态

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'connection_pool') or self.proxy.connection_pool is None:
                return 200, {
                    'status': 'success',
                    'message': '连接池未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            stats = await self.proxy.connection_pool.get_stats()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'statistics': stats,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取连接池状态时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取连接池状态失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_pool_status_by_host(self, path: str) -> Tuple[int, Dict[str, Any]]:
        """
        获取指定主机的连接池状态

        Args:
            path: 请求路径（如 /command/pool/status/example.com:443）

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'connection_pool') or self.proxy.connection_pool is None:
                return 200, {
                    'status': 'success',
                    'message': '连接池未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            # 从路径中提取 host:port
            host_port = path.split('/command/pool/status/')[-1]
            if ':' in host_port:
                host, port_str = host_port.rsplit(':', 1)
                port = int(port_str)
            else:
                host = host_port
                port = 443
            
            status = await self.proxy.connection_pool.get_pool_status(host, port)
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'host': host,
                'port': port,
                'pool_status': status,
                'timestamp': time.time()
            }
            
        except ValueError as e:
            return 400, {
                'status': 'error',
                'message': f'无效的主机或端口: {str(e)}',
                'timestamp': time.time()
            }
        except Exception as e:
            self.logger.error(f"获取指定主机连接池状态时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取连接池状态失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _get_pool_health(self) -> Tuple[int, Dict[str, Any]]:
        """
        获取连接池健康检查结果

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'connection_pool') or self.proxy.connection_pool is None:
                return 200, {
                    'status': 'success',
                    'message': '连接池未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            health = await self.proxy.connection_pool.health_check()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'health': health,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"获取连接池健康检查结果时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'获取健康检查结果失败: {str(e)}',
                'timestamp': time.time()
            }
    
    async def _cleanup_pool(self) -> Tuple[int, Dict[str, Any]]:
        """
        手动清理连接池中的过期连接

        Returns:
            (status_code, response_dict) 元组
        """
        try:
            if not hasattr(self.proxy, 'connection_pool') or self.proxy.connection_pool is None:
                return 200, {
                    'status': 'success',
                    'message': '连接池未启用',
                    'enabled': False,
                    'timestamp': time.time()
                }
            
            cleaned_count = await self.proxy.connection_pool.cleanup_expired_connections()
            
            return 200, {
                'status': 'success',
                'enabled': True,
                'message': f'已清理 {cleaned_count} 个过期连接',
                'cleaned_count': cleaned_count,
                'timestamp': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"清理连接池时发生错误: {e}")
            return 500, {
                'status': 'error',
                'message': f'清理连接池失败: {str(e)}',
                'timestamp': time.time()
            }
