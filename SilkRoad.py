"""
SilkRoad-Next 程序主入口

作为整个系统的启动入口，负责：
- 初始化所有核心模块
- 启动代理服务器
- 注册信号处理器
- 协调各模块生命周期

Author: SilkRoad-Next Team
Version: 1.0.0
"""

import asyncio
import sys
from typing import Optional

from modules.cfg import ConfigManager, ConfigError
from modules.logging import Logger
from modules.proxy import ProxyServer
from modules.command import CommandHandler
from modules.exit import GracefulExit


class SilkRoad:
    """
    SilkRoad-Next 主应用类

    负责协调所有核心模块的初始化、启动和关闭。

    Attributes:
        config (ConfigManager): 配置管理器
        logger (Logger): 日志记录器
        proxy_server (Optional[ProxyServer]): 代理服务器实例
        command_handler (Optional[CommandHandler]): 命令处理器实例
        shutdown_event (asyncio.Event): 关闭事件，用于通知系统开始关闭

        V2 Components:
        connection_pool: 连接池（用于复用与目标服务器的长连接）
        thread_pool: 线程池（用于处理 CPU 密集型任务）
        session_manager: 会话管理器（用于管理客户端会话状态）
        cache_manager: 缓存管理器（用于优化资源加载速度）
        blacklist_manager: 黑名单管理器（用于访问控制）
        script_injector: 脚本注入器（用于注入自定义 JS 脚本）

        V3 Components:
        stream_handler: 流处理器（用于处理流式响应）
        media_handler: 媒体流处理器（用于处理视频/音频流）
        sse_handler: SSE 处理器（用于处理 Server-Sent Events）
        others_handler: 其他流处理器（用于处理分块传输等）
    """

    def __init__(self):
        """
        初始化 SilkRoad 应用

        创建所有核心模块的引用，但不执行初始化逻辑。
        """
        # 配置管理器
        self.config = ConfigManager()

        # 日志记录器（需要配置管理器）
        self.logger: Optional[Logger] = None

        # 代理服务器（需要配置和日志）
        self.proxy_server: Optional[ProxyServer] = None

        # 命令处理器（需要代理服务器、配置和日志）
        self.command_handler: Optional[CommandHandler] = None

        # 关闭事件，用于优雅退出
        self.shutdown_event = asyncio.Event()

        # ========== V2 新增组件 ==========
        # 连接池（用于复用与目标服务器的长连接）
        self.connection_pool = None

        # 线程池（用于处理 CPU 密集型任务）
        self.thread_pool = None

        # 会话管理器（用于管理客户端会话状态）
        self.session_manager = None

        # 缓存管理器（用于优化资源加载速度）
        self.cache_manager = None

        # 黑名单管理器（用于访问控制）
        self.blacklist_manager = None

        # 脚本注入器（用于注入自定义 JS 脚本）
        self.script_injector = None

        # ========== V3 新增组件 ==========
        # 流处理器（用于处理流式响应）
        self.stream_handler = None

        # 媒体流处理器（用于处理视频/音频流）
        self.media_handler = None

        # SSE 处理器（用于处理 Server-Sent Events）
        self.sse_handler = None

        # 其他流处理器（用于处理分块传输等）
        self.others_handler = None

        # ========== V4 新增组件 ==========
        # WebSocket 处理器（用于处理 WebSocket 协议）
        self.websocket_handler = None

        # 流量控制器（用于请求调度和带宽管理）
        self.traffic_controller = None

    async def initialize(self) -> None:
        """
        初始化所有模块（V1 + V2 + V3）

        按照依赖顺序初始化所有核心模块：
        1. 加载配置文件
        2. 初始化日志系统
        3. 初始化连接池（V2）
        4. 初始化线程池（V2）
        5. 初始化会话管理器（V2）
        6. 初始化缓存管理器（V2）
        7. 初始化黑名单管理器（V2）
        8. 初始化脚本注入器（V2）
        9. 初始化流处理器（V3）
        10. 初始化 WebSocket 处理器（V4）
        11. 初始化流量控制器（V4）
        12. 创建代理服务器
        13. 创建命令处理器
        14. 设置优雅退出

        Raises:
            ConfigError: 配置加载失败
            Exception: 其他初始化错误
        """
        try:
            # ========== V1 初始化 ==========
            print("=" * 60)
            print("  SilkRoad-Next v4.0.0 - 高性能反向代理服务器")
            print("=" * 60)
            print()

            # 1. 加载配置
            print("[1/14] 加载配置文件...")
            await self.config.load()

            # 2. 初始化日志系统
            print("[2/14] 初始化日志系统...")
            self.logger = Logger(self.config)
            self.logger.info("配置加载完成")

            # ========== V2 初始化 ==========
            # 3. 初始化连接池
            print("[3/14] 初始化连接池...")
            if self.config.get('performance.connectionPool.enabled', False):
                from modules.connectionpool import ConnectionPool
                self.connection_pool = ConnectionPool(
                    max_connections_per_host=self.config.get('performance.connectionPool.maxPoolSize', 100),
                    connection_timeout=self.config.get('server.proxy.connectionTimeout', 30),
                    keep_alive_timeout=self.config.get('performance.connectionPool.keepaliveTimeout', 30)
                )
                self.logger.info("连接池已启用")

            # 4. 初始化线程池
            print("[4/14] 初始化线程池...")
            if self.config.get('performance.threadPool.enabled', False):
                from modules.threadpool import ThreadPoolManager
                self.thread_pool = ThreadPoolManager(
                    max_workers=self.config.get('performance.threadPool.maxWorkers', 4)
                )
                self.logger.info("线程池已启用")

            # 5. 初始化会话管理器
            print("[5/14] 初始化会话管理器...")
            if self.config.get('v2.session.enabled', False):
                from modules.sessions import SessionManager
                self.session_manager = SessionManager(
                    session_timeout=self.config.get('v2.session.timeout', 1800),
                    cleanup_interval=self.config.get('v2.session.cleanupInterval', 60)
                )
                asyncio.create_task(self.session_manager.start_cleanup_task())
                self.logger.info("会话管理器已启用")

            # 6. 初始化缓存管理器
            print("[6/14] 初始化缓存管理器...")
            if self.config.get('cache.enabled', False):
                from modules.cachemanager import CacheManager
                self.cache_manager = CacheManager(
                    max_memory_cache_size=self.config.get('cache.maxSize', 1073741824),
                    default_ttl=self.config.get('cache.defaultTTL', 3600)
                )
                asyncio.create_task(self._cache_cleanup_task())
                self.logger.info("缓存管理器已启用")

            # 7. 初始化黑名单管理器
            print("[7/14] 初始化黑名单管理器...")
            if self.config.get('v2.blacklist.enabled', False):
                from modules.blacklist import BlacklistManager
                self.blacklist_manager = BlacklistManager(
                    config_file=self.config.get('v2.blacklist.configFile', 'databases/blacklist.json')
                )
                self.logger.info("黑名单管理器已启用")

            # 8. 初始化脚本注入器
            print("[8/14] 初始化脚本注入器...")
            if self.config.get('v2.scripts.enabled', False):
                from modules.scripts import ScriptInjector
                self.script_injector = ScriptInjector(
                    config_file=self.config.get('v2.scripts.configFile', 'databases/scripts.json')
                )
                # 加载脚本配置
                await self.script_injector.load_config()
                self.logger.info("脚本注入器已启用")

            # ========== V3 初始化 ==========
            # 9. 初始化流处理器
            print("[9/14] 初始化流处理器...")
            if self.config.get('stream.enabled', False):
                from modules.stream.handle import StreamHandler
                from modules.stream.media import MediaHandler
                from modules.stream.sse import SSEHandler
                from modules.stream.others import OthersHandler

                # 创建流处理器
                self.stream_handler = StreamHandler(self.config, self.logger)

                # 创建子处理器
                self.media_handler = MediaHandler(self.config, self.logger)
                self.sse_handler = SSEHandler(self.config, self.logger)
                self.others_handler = OthersHandler(self.config, self.logger)

                # 注入子处理器到 StreamHandler
                self.stream_handler.set_media_handler(self.media_handler)
                self.stream_handler.set_sse_handler(self.sse_handler)
                self.stream_handler.set_others_handler(self.others_handler)

                self.logger.info("流处理器已启用")

            # ========== V4 初始化 ==========
            # 10. 初始化 WebSocket 处理器
            print("[10/14] 初始化 WebSocket 处理器...")
            if self.config.get('websocket.enabled', False):
                from modules.websockets import WebSocketHandler
                
                self.websocket_handler = WebSocketHandler(self.config, self.logger.logger)
                self.logger.info("WebSocket 处理器已启用")

            # 11. 初始化流量控制器
            print("[11/14] 初始化流量控制器...")
            if self.config.get('trafficControl.enabled', False):
                from modules.controler import TrafficController
                
                self.traffic_controller = TrafficController(self.config, self.logger.logger)
                
                asyncio.create_task(self.traffic_controller.start_scheduler())
                self.logger.info("流量控制器已启用")

            # ========== 创建代理服务器 ==========
            print("[12/14] 创建代理服务器...")
            proxy_host = self.config.get('server.proxy.host', '0.0.0.0')
            proxy_port = self.config.get('server.proxy.port', 8080)

            self.proxy_server = ProxyServer(
                host=proxy_host,
                port=proxy_port,
                config=self.config,
                logger=self.logger
            )

            # 注入 V2 模块到代理服务器
            self.proxy_server.connection_pool = self.connection_pool
            self.proxy_server.thread_pool = self.thread_pool
            self.proxy_server.session_manager = self.session_manager
            self.proxy_server.cache_manager = self.cache_manager
            self.proxy_server.blacklist_manager = self.blacklist_manager
            self.proxy_server.script_injector = self.script_injector

            # 注入 V3 模块到代理服务器
            self.proxy_server.stream_handler = self.stream_handler
            self.proxy_server.media_handler = self.media_handler
            self.proxy_server.sse_handler = self.sse_handler
            self.proxy_server.others_handler = self.others_handler

            # 注入 V4 模块到代理服务器
            self.proxy_server.websocket_handler = self.websocket_handler
            self.proxy_server.traffic_controller = self.traffic_controller

            self.logger.info(f"代理服务器配置: {proxy_host}:{proxy_port}")

            # 13. 创建命令处理器
            print("[13/14] 创建命令处理器...")
            self.command_handler = CommandHandler(
                proxy_server=self.proxy_server,
                config=self.config,
                logger=self.logger
            )
            self.proxy_server.command_handler = self.command_handler
            self.logger.info("命令处理器已绑定到代理服务器")

            # 14. 设置优雅退出
            print("[14/14] 设置优雅退出...")
            GracefulExit.setup(self.shutdown_event, self.logger)

            # ========== 初始化完成 ==========
            print()
            print("=" * 60)
            print("  初始化完成！")
            print("=" * 60)
            print()

            self.logger.info("所有模块初始化完成（V1 + V2 + V3 + V4）")

        except ConfigError as e:
            print(f"[错误] 配置加载失败: {e}")
            raise

        except Exception as e:
            error_msg = f"初始化失败: {e}"
            if self.logger:
                self.logger.error(error_msg, exception=e)
            else:
                print(f"[错误] {error_msg}")
            raise

    async def run(self) -> None:
        """
        启动主服务

        执行完整的启动流程：
        1. 初始化所有模块
        2. 启动代理服务器
        3. 启动命令处理器
        4. 等待关闭信号

        关闭流程（V1 + V2 + V3 + V4）：
        1. 关闭 WebSocket 连接（V4）
        2. 停止流量控制器（V4）
        3. 关闭流处理器（V3）
        4. 关闭连接池（V2）
        5. 关闭线程池（V2）
        6. 保存会话数据（V2）
        7. 清理缓存（V2）
        8. 停止代理服务器（V1）
        9. 关闭日志系统（V1）

        Raises:
            Exception: 启动过程中的任何错误
        """
        try:
            await self.initialize()

            assert self.logger is not None
            assert self.proxy_server is not None

            self._display_startup_info()

            tasks = [
                asyncio.create_task(self.proxy_server.start()),
                asyncio.create_task(self.wait_for_shutdown())
            ]

            self.logger.info("所有服务已启动，开始处理请求...")

            await asyncio.gather(*tasks)

        except OSError as e:
            # 端口占用等系统错误
            if self.logger:
                self.logger.error(f"服务启动失败（系统错误）: {e}")
            else:
                print(f"[错误] 服务启动失败: {e}")
            raise

        except Exception as e:
            # 其他启动错误
            if self.logger:
                self.logger.error(f"服务启动失败: {e}", exception=e)
            else:
                print(f"[错误] 服务启动失败: {e}")
            raise

    async def wait_for_shutdown(self) -> None:
        """
        等待关闭信号

        阻塞等待关闭事件被触发，然后执行优雅关闭流程（V1 + V2 + V3）：
        1. 关闭流处理器（V3）
        2. 关闭连接池（V2）
        3. 关闭线程池（V2）
        4. 保存会话数据（V2）
        5. 清理缓存（V2）
        6. 停止代理服务器（V1）
        7. 关闭日志系统（V1）
        """
        await self.shutdown_event.wait()

        if not self.logger:
            return

        self.logger.info("=" * 60)
        self.logger.info("开始优雅关闭...")
        self.logger.info("=" * 60)

        try:
            # ========== 关闭 V4 模块 ==========
            # 1. 关闭 WebSocket 连接
            if self.websocket_handler:
                self.logger.info("[1/9] 关闭 WebSocket 连接...")
                connections = await self.websocket_handler.get_active_connections()
                for conn in connections:
                    await self.websocket_handler.close_connection(conn.connection_id)
                self.logger.info(f"已关闭 {len(connections)} 个 WebSocket 连接")

            # 2. 停止流量控制器
            if self.traffic_controller:
                self.logger.info("[2/9] 停止流量控制器...")
                # 流量控制器无需特殊关闭

            # ========== 关闭 V3 模块 ==========
            # 3. 关闭流处理器
            if self.stream_handler:
                self.logger.info("[3/9] 关闭流处理器...")
                active_streams = await self.stream_handler.get_active_streams()
                for stream_id in active_streams:
                    await self.stream_handler.close_stream(stream_id)
                self.logger.info(f"已关闭 {len(active_streams)} 个活跃流")

            # ========== 关闭 V2 模块 ==========
            # 4. 关闭连接池
            if self.connection_pool:
                self.logger.info("[4/9] 关闭连接池...")
                await self.connection_pool.close_all()

            # 5. 关闭线程池
            if self.thread_pool:
                self.logger.info("[5/9] 关闭线程池...")
                self.thread_pool.shutdown()

            # 6. 保存会话数据
            if self.session_manager:
                self.logger.info("[6/9] 保存会话数据...")
                await self.session_manager.save_to_file('sessions_backup.json')

            # 7. 清理缓存
            if self.cache_manager:
                self.logger.info("[7/9] 清理缓存...")
                await self.cache_manager.clear_all()

            # ========== 关闭 V1 模块 ==========
            # 8. 停止代理服务器
            if self.proxy_server:
                self.logger.info("[8/9] 停止代理服务器...")
                await self.proxy_server.stop()

            # 9. 关闭日志系统
            self.logger.info("[9/9] 关闭日志系统...")
            await self.logger.close()

            print()
            print("=" * 60)
            print("  SilkRoad-Next 已安全退出")
            print("=" * 60)

        except Exception as e:
            # 关闭过程中的错误
            if self.logger:
                self.logger.error(f"关闭过程中发生错误: {e}")
            else:
                print(f"[错误] 关闭过程中发生错误: {e}")

    async def _cache_cleanup_task(self):
        """
        定期清理缓存任务

        根据配置的清理间隔，定期清理过期的缓存项。
        该任务在后台持续运行，直到程序关闭。
        """
        while True:
            try:
                # 等待清理间隔
                cleanup_interval = self.config.get('cache.cleanupInterval', 300)
                await asyncio.sleep(cleanup_interval)

                # 执行缓存清理
                if self.cache_manager:
                    await self.cache_manager.cleanup_expired()
                    if self.logger:
                        self.logger.debug("缓存清理任务完成")

            except asyncio.CancelledError:
                # 任务被取消，正常退出
                break
            except Exception as e:
                # 清理过程中发生错误，记录日志但继续运行
                if self.logger:
                    self.logger.error(f"缓存清理任务失败: {e}")

    def _display_startup_info(self) -> None:
        """
        显示启动信息

        在控制台打印欢迎界面和服务信息。
        """
        proxy_host = self.config.get('server.proxy.host', '0.0.0.0')
        proxy_port = self.config.get('server.proxy.port', 8080)
        max_connections = self.config.get('server.proxy.maxConnections', 2000)
        log_level = self.config.get('logging.level', 'INFO')

        display_host = '127.0.0.1' if proxy_host == '0.0.0.0' else proxy_host

        print()
        print("┌" + "─" * 58 + "┐")
        print("│" + " " * 58 + "│")
        print("│" + "  SilkRoad-Next v4.0.0".ljust(58) + "│")
        print("│" + "  高性能反向代理服务器".ljust(58) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  服务信息:".ljust(59) + "│")
        print(f"│    代理服务: http://{proxy_host}:{proxy_port}".ljust(59) + "│")
        print(f"│    管理接口: http://{display_host}:{proxy_port}/command/*".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("│  配置信息:".ljust(59) + "│")
        print(f"│    最大并发连接: {max_connections}".ljust(59) + "│")
        print(f"│    日志级别: {log_level}".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("│  V4 新功能:".ljust(59) + "│")
        ws_status = "已启用" if self.config.get('websocket.enabled', False) else "未启用"
        tc_status = "已启用" if self.config.get('trafficControl.enabled', False) else "未启用"
        print(f"│    WebSocket: {ws_status}".ljust(59) + "│")
        print(f"│    流量控制: {tc_status}".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  可用命令:".ljust(59) + "│")
        print(f"│    查看状态: curl http://{display_host}:{proxy_port}/command/status".ljust(59) + "│")
        print(f"│    暂停服务: curl http://{display_host}:{proxy_port}/command/pause".ljust(59) + "│")
        print(f"│    恢复服务: curl http://{display_host}:{proxy_port}/command/resume".ljust(59) + "│")
        print(f"│    优雅退出: curl http://{display_host}:{proxy_port}/command/exit".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  按 Ctrl+C 优雅退出".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("└" + "─" * 58 + "┘")
        print()


def main() -> None:
    """
    主函数入口

    创建 SilkRoad 实例并启动服务。
    处理顶层异常并确保程序正确退出。
    """
    try:
        # 创建应用实例
        app = SilkRoad()

        # 运行应用（使用 asyncio.run 自动管理事件循环）
        asyncio.run(app.run())

    except KeyboardInterrupt:
        # Ctrl+C 中断（正常退出）
        print("\n[信息] 接收到中断信号，程序已退出")
        sys.exit(0)

    except ConfigError as e:
        # 配置错误
        print(f"\n[错误] 配置错误: {e}")
        sys.exit(1)

    except OSError as e:
        # 系统错误（如端口占用）
        print(f"\n[错误] 系统错误: {e}")
        sys.exit(1)

    except Exception as e:
        # 其他未捕获的异常
        print(f"\n[错误] 程序异常退出: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
