"""
配置管理模块

负责加载、解析和管理全局配置，支持：
- JSON 格式配置文件读取
- 默认配置回退
- 配置热重载
- 配置项验证
- 配置文件变更监听

Author: SilkRoad-Next Team
Version: 2.0.0
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Callable, Optional

from modules.exit import GracefulExit

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileModifiedEvent = None


class ConfigError(Exception):
    """配置错误异常"""
    pass


class ConfigManager:
    """
    配置管理器

    负责加载、解析和管理全局配置，提供配置访问接口。

    Attributes:
        config_path (str): 配置文件路径
        config (Dict[str, Any]): 当前配置字典
        default_config (Dict[str, Any]): 默认配置字典
        _callbacks (List[Callable]): 配置变更回调函数列表
        _observer (Observer): 文件监听器（可选）
        _event_loop: asyncio 事件循环引用
    """

    def __init__(self, config_path: str = "databases/config.json"):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径，默认为 "databases/config.json"
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.default_config = self._get_default_config()
        self._callbacks: List[Callable] = []
        self._observer: Optional[Any] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def load(self) -> None:
        """
        加载配置文件

        如果配置文件不存在，则创建默认配置文件。
        如果配置文件存在但格式错误，则抛出 ConfigError 异常。

        Raises:
            ConfigError: 配置文件格式错误或权限不足
        """
        # 检查配置文件是否存在
        if not os.path.exists(self.config_path):
            # 配置文件不存在，使用默认配置并保存
            self.config = self.default_config.copy()
            await self._save_default_config()
            return

        # 配置文件存在，尝试加载
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)

            # 验证配置项
            self._validate_config()

        except json.JSONDecodeError as e:
            raise ConfigError(f"配置文件格式错误: {e}")
        except PermissionError:
            raise ConfigError(f"无权限读取配置文件: {self.config_path}")
        except Exception as e:
            raise ConfigError(f"加载配置文件失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项

        支持点分隔符访问嵌套配置项，例如 'server.proxy.port'

        Args:
            key: 配置项键名，支持点分隔符（如 'server.port'）
            default: 默认值，当配置项不存在时返回

        Returns:
            Any: 配置项值，如果不存在则返回默认值

        Examples:
            >>> config.get('server.proxy.port', 8080)
            8080
            >>> config.get('server.proxy.host', '0.0.0.0')
            '0.0.0.0'
        """
        # 分割键名
        keys = key.split('.')
        value = self.config

        # 逐层访问嵌套字典
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                # 如果中间值不是字典，说明路径不存在
                return default

            # 如果值为 None，提前返回默认值
            if value is None:
                return default

        return value

    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置

        返回系统默认配置字典，包含所有必需的配置项。

        Returns:
            Dict[str, Any]: 默认配置字典
        """
        return {
            "server": {
                "proxy": {
                    "host": "0.0.0.0",
                    "port": 8080,
                    "backlog": 2048,
                    "maxConnections": 2000,
                    "connectionTimeout": 30,
                    "requestTimeout": 60,
                    "maxRedirects": 10
                },
                "command": {
                    "enabled": True
                }
            },
            "proxy": {
                "targetPrefix": "",
                "stripPrefix": False,
                "forwardHeaders": [
                    "Accept",
                    "Accept-Language",
                    "Accept-Datetime",
                    "Cache-Control",
                    "Content-Type",
                    "If-Match",
                    "If-Modified-Since",
                    "If-None-Match",
                    "If-Range",
                    "If-Unmodified-Since",
                    "Range",
                    "X-Requested-With"
                ],
                "dropHeaders": [
                    "Accept-Encoding",
                    "Connection",
                    "Keep-Alive",
                    "Proxy-Authorization",
                    "Proxy-Connection",
                    "TE",
                    "Transfer-Encoding",
                    "Upgrade"
                ],
                "acceptEncoding": ["gzip", "deflate"],
                "defaultUserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            "urlRewrite": {
                "enabled": True,
                "maxContentSize": 10485760,
                "streamThreshold": 10485760,
                "skipContentTypes": [
                    "image/*",
                    "video/*",
                    "audio/*",
                    "application/pdf",
                    "application/zip",
                    "application/x-rar-compressed",
                    "application/x-7z-compressed",
                    "application/octet-stream"
                ],
                "processContentTypes": [
                    "text/html",
                    "text/css",
                    "text/javascript",
                    "application/javascript",
                    "application/x-javascript",
                    "text/xml",
                    "application/xml",
                    "application/json",
                    "application/xhtml+xml"
                ]
            },
            "pageRoutes": {
                "/": "main",
                "/admin": "admin",
                "/error": "error"
            },
            "logging": {
                "level": "INFO",
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
                "rotation": "00:00",
                "retention": "30 days",
                "compression": "zip",
                "colorize": True,
                "errorLog": True,
                "errorLogFormat": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}\n{exception}"
            },
            "cache": {
                "enabled": False,
                "maxSize": 1073741824,
                "defaultTTL": 3600,
                "cleanupInterval": 300,
                "warmupOnStart": False,
                "warmupUrls": [],
                "warmupTTL": 7200
            },
            "security": {
                "rateLimit": {
                    "enabled": False,
                    "requestsPerMinute": 1000,
                    "burstSize": 100
                },
                "maxRequestSize": 52428800,
                "allowedMethods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
            },
            "performance": {
                "connectionPool": {
                    "enabled": False,
                    "maxPoolSize": 100,
                    "maxKeepaliveConnections": 20,
                    "keepaliveTimeout": 30
                },
                "threadPool": {
                    "enabled": False,
                    "maxWorkers": 4,
                    "queueSize": 1000
                }
            },
            "websocket": {
                "enabled": False,
                "maxConnections": 500,
                "maxMessageSize": 1048576,
                "pingInterval": 30,
                "pongTimeout": 10,
                "compression": {
                    "enabled": True,
                    "level": 6
                },
                "extensions": {
                    "permessage-deflate": True,
                    "client-max-window-bits": 15,
                    "server-max-window-bits": 15
                }
            }
        }

    def _validate_config(self) -> None:
        """
        验证配置项

        检查必需配置项是否存在，验证配置项类型和范围。

        Raises:
            ConfigError: 配置项缺失或无效
        """
        required_keys = [
            'server.proxy.host',
            'server.proxy.port'
        ]

        for key in required_keys:
            if self.get(key) is None:
                raise ConfigError(f"缺少必需配置项: {key}")

        proxy_port = self.get('server.proxy.port')
        if not self._validate_port(proxy_port):
            raise ConfigError(f"代理端口号无效: {proxy_port}，必须在 1-65535 范围内")

        # 验证日志级别
        log_level = self.get('logging.level', 'INFO')
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if log_level.upper() not in valid_levels:
            raise ConfigError(f"日志级别无效: {log_level}，必须是 {valid_levels} 之一")

        # 验证连接数配置
        max_connections = self.get('server.proxy.maxConnections', 2000)
        if not isinstance(max_connections, int) or max_connections < 1:
            raise ConfigError(f"最大连接数无效: {max_connections}，必须是正整数")

        # 验证超时配置
        timeout = self.get('server.proxy.connectionTimeout', 30)
        if not isinstance(timeout, int) or timeout < 1:
            raise ConfigError(f"连接超时时间无效: {timeout}，必须是正整数")

        request_timeout = self.get('server.proxy.requestTimeout', 60)
        if not isinstance(request_timeout, int) or request_timeout < 1:
            raise ConfigError(f"请求超时时间无效: {request_timeout}，必须是正整数")

        # 验证重定向次数
        max_redirects = self.get('server.proxy.maxRedirects', 10)
        if not isinstance(max_redirects, int) or max_redirects < 0 or max_redirects > 50:
            raise ConfigError(f"最大重定向次数无效: {max_redirects}，必须在 0-50 范围内")

        # 验证 URL 重写配置
        max_content_size = self.get('urlRewrite.maxContentSize', 10485760)
        if not isinstance(max_content_size, int) or max_content_size < 0:
            raise ConfigError(f"最大内容大小无效: {max_content_size}，必须是非负整数")

        # 验证缓存配置
        if self.get('cache.enabled', False):
            cache_size = self.get('cache.maxSize', 1073741824)
            if not isinstance(cache_size, int) or cache_size < 0:
                raise ConfigError(f"缓存大小无效: {cache_size}，必须是非负整数")

            cache_ttl = self.get('cache.defaultTTL', 3600)
            if not isinstance(cache_ttl, int) or cache_ttl < 0:
                raise ConfigError(f"缓存 TTL 无效: {cache_ttl}，必须是非负整数")

        # 验证安全配置
        max_request_size = self.get('security.maxRequestSize', 52428800)
        if not isinstance(max_request_size, int) or max_request_size < 0:
            raise ConfigError(f"最大请求大小无效: {max_request_size}，必须是非负整数")

        # 验证允许的 HTTP 方法
        allowed_methods = self.get('security.allowedMethods', [])
        if not isinstance(allowed_methods, list) or len(allowed_methods) == 0:
            raise ConfigError("允许的 HTTP 方法列表不能为空")

        valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT']
        for method in allowed_methods:
            if method.upper() not in valid_methods:
                raise ConfigError(f"无效的 HTTP 方法: {method}")

    def _validate_port(self, port: Any) -> bool:
        """
        验证端口号

        Args:
            port: 端口号

        Returns:
            bool: 端口号是否有效
        """
        # 检查类型
        if not isinstance(port, int):
            # 尝试转换为整数
            try:
                port = int(port)
            except (ValueError, TypeError):
                return False

        # 检查范围
        return 1 <= port <= 65535

    async def _save_default_config(self) -> None:
        """
        保存默认配置到文件

        创建配置文件目录（如果不存在）并保存默认配置。

        Raises:
            ConfigError: 创建目录或保存文件失败
        """
        try:
            # 创建配置文件目录
            config_dir = os.path.dirname(self.config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            # 保存配置到文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.default_config, f, indent=2, ensure_ascii=False)

        except PermissionError:
            raise ConfigError(f"无权限创建配置文件: {self.config_path}")
        except OSError as e:
            raise ConfigError(f"创建配置文件失败: {e}")
        except Exception as e:
            raise ConfigError(f"保存默认配置失败: {e}")

    def register_callback(self, callback: Callable) -> None:
        """
        注册配置变更回调函数

        为配置热重载功能预留接口（V2 功能）。
        当配置文件发生变化时，将调用所有注册的回调函数。

        Args:
            callback: 回调函数，无参数

        Examples:
            >>> def on_config_change():
            ...     print("配置已更新")
            >>> config.register_callback(on_config_change)
        """
        if not callable(callback):
            raise ValueError("回调函数必须是可调用对象")

        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable) -> None:
        """
        注销配置变更回调函数

        Args:
            callback: 要注销的回调函数
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def reload(self) -> None:
        """
        重新加载配置文件

        重新读取配置文件并验证，然后触发所有注册的回调函数。

        Raises:
            ConfigError: 配置文件格式错误或验证失败
        """
        # 重新加载配置
        await self.load()

        # 触发所有回调函数
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                # 记录错误但不中断其他回调
                print(f"配置变更回调执行失败: {e}")

    def set(self, key: str, value: Any, save: bool = False) -> None:
        """
        设置配置项（运行时修改）

        Args:
            key: 配置项键名，支持点分隔符
            value: 配置项值
            save: 是否立即保存到文件，默认为 False

        Examples:
            >>> config.set('server.proxy.port', 9090)
            >>> config.set('server.proxy.port', 9090, save=True)  # 同时保存到文件

        Raises:
            ConfigError: 保存配置文件失败
        """
        keys = key.split('.')
        config_dict = self.config

        for k in keys[:-1]:
            if k not in config_dict:
                config_dict[k] = {}
            config_dict = config_dict[k]

        config_dict[keys[-1]] = value

        if save:
            task = asyncio.create_task(self._save_config())
            if GracefulExit.is_initialized():
                GracefulExit.register_task(task)

    async def _save_config(self) -> None:
        """
        保存配置到文件

        Raises:
            ConfigError: 保存配置文件失败
        """
        try:
            config_dir = os.path.dirname(self.config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

        except PermissionError:
            raise ConfigError(f"无权限保存配置文件: {self.config_path}")
        except OSError as e:
            raise ConfigError(f"保存配置文件失败: {e}")
        except Exception as e:
            raise ConfigError(f"保存配置失败: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """
        获取完整配置字典

        Returns:
            Dict[str, Any]: 配置字典的副本
        """
        return self.config.copy()

    def __repr__(self) -> str:
        """返回配置管理器的字符串表示"""
        return f"ConfigManager(config_path='{self.config_path}', loaded={bool(self.config)})"
    
    def start_watching(self) -> bool:
        """
        启动配置文件监听

        Returns:
            bool: 是否成功启动监听
        """
        if not WATCHDOG_AVAILABLE:
            print("[警告] watchdog 库未安装，配置文件监听功能不可用")
            return False
        
        if self._observer is not None:
            return True
        
        try:
            self._event_loop = asyncio.get_event_loop()
            
            class ConfigFileHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
                def __init__(handler, config_manager: ConfigManager):
                    handler.config_manager = config_manager
                    handler._last_modified = 0
                
                def on_modified(handler, event):
                    if event.src_path.endswith('config.json'):
                        import time
                        current_time = time.time()
                        
                        if current_time - handler._last_modified < 1.0:
                            return
                        
                        handler._last_modified = current_time
                        
                        if handler.config_manager._event_loop:
                            def create_and_register_task():
                                task = asyncio.create_task(handler.config_manager._on_file_changed())
                                if GracefulExit.is_initialized():
                                    GracefulExit.register_task(task)
                            
                            handler.config_manager._event_loop.call_soon_threadsafe(
                                create_and_register_task
                            )
            
            self._observer = Observer()
            config_dir = os.path.dirname(self.config_path)
            if not config_dir:
                config_dir = '.'
            
            self._observer.schedule(
                ConfigFileHandler(self),
                config_dir,
                recursive=False
            )
            self._observer.start()
            
            return True
            
        except Exception as e:
            print(f"[错误] 启动配置文件监听失败: {e}")
            return False
    
    def stop_watching(self) -> None:
        """停止配置文件监听"""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
    
    async def _on_file_changed(self) -> None:
        """配置文件变更回调"""
        try:
            print("[信息] 检测到配置文件变更，开始重新加载...")
            await self.reload()
        except Exception as e:
            print(f"[错误] 配置文件变更处理失败: {e}")

