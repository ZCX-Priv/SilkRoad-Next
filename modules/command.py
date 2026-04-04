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
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import psutil


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
        self.logger = logger

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
                'description': '清除服务端缓存'
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

            asyncio.create_task(self._delayed_exit())

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

                return 200, {
                    'status': 'success',
                    'message': '缓存已清除',
                    'details': {
                        'cleared_files': cleared_files,
                        'cleared_size': cleared_size,
                        'cleared_size_formatted': self._format_size(cleared_size)
                    },
                    'recommendation': '建议同时清除浏览器缓存以获得最佳效果',
                    'timestamp': time.time()
                }
            else:
                return 200, {
                    'status': 'success',
                    'message': '缓存目录不存在，无需清除',
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
