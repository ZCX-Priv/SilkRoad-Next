# Tasks

## 阶段一：基础架构搭建

- [x] Task 1: 创建项目目录结构和依赖清单
  - [x] SubTask 1.1: 创建所有必需目录（modules/, databases/, pages/, logs/）
  - [x] SubTask 1.2: 创建 modules/__init__.py
  - [x] SubTask 1.3: 创建 modules/url/ 目录及 __init__.py
  - [x] SubTask 1.4: 创建 requirements.txt（包含 aiohttp, loguru, chardet, psutil）
  - [x] SubTask 1.5: 创建 .gitignore 文件

- [x] Task 2: 创建配置文件和数据文件
  - [x] SubTask 2.1: 创建 databases/config.json（包含所有默认配置）
  - [x] SubTask 2.2: 创建 databases/ua.json（包含UA池数据）
  - [x] SubTask 2.3: 创建 pages/main/index.html（默认首页）
  - [x] SubTask 2.4: 创建 pages/error/ 目录及错误页面（400.html, 404.html, 500.html, 502.html, 504.html）

## 阶段二：核心基础模块

- [x] Task 3: 实现配置管理模块（modules/cfg.py）
  - [x] SubTask 3.1: 实现 ConfigManager 类
  - [x] SubTask 3.2: 实现 load() 方法（加载配置文件）
  - [x] SubTask 3.3: 实现 get() 方法（支持点分隔符访问）
  - [x] SubTask 3.4: 实现 _get_default_config() 方法（默认配置）
  - [x] SubTask 3.5: 实现 _validate_config() 方法（配置验证）
  - [x] SubTask 3.6: 实现 _save_default_config() 方法（保存默认配置）
  - [x] SubTask 3.7: 实现 register_callback() 方法（预留热重载接口）

- [x] Task 4: 实现日志服务模块（modules/logging.py）
  - [x] SubTask 4.1: 实现 Logger 类
  - [x] SubTask 4.2: 实现 _setup_logger() 方法（配置loguru）
  - [x] SubTask 4.3: 实现控制台输出（带颜色）
  - [x] SubTask 4.4: 实现文件输出（按天轮转）
  - [x] SubTask 4.5: 实现错误日志单独文件
  - [x] SubTask 4.6: 实现 info/debug/warning/error 方法
  - [x] SubTask 4.7: 实现 close() 方法
  - [x] SubTask 4.8: 实现 _parse_retention() 方法（解析保留策略）

- [x] Task 5: 实现UA随机化模块（modules/ua.py）
  - [x] SubTask 5.1: 实现 UAHandler 类
  - [x] SubTask 5.2: 实现 _load_user_agents() 方法（加载UA池）
  - [x] SubTask 5.3: 实现 get_random_ua() 方法（随机选择UA）
  - [x] SubTask 5.4: 实现 get_mobile_ua() 方法（获取移动端UA）
  - [x] SubTask 5.5: 实现 get_desktop_ua() 方法（获取桌面端UA）

- [x] Task 6: 实现优雅退出模块（modules/exit.py）
  - [x] SubTask 6.1: 实现 GracefulExit 类
  - [x] SubTask 6.2: 实现 setup() 方法（设置信号处理器）
  - [x] SubTask 6.3: 实现 _signal_handler() 方法（处理信号）
  - [x] SubTask 6.4: 实现 register_task() 方法（注册活动任务）
  - [x] SubTask 6.5: 实现 wait_for_tasks() 方法（等待任务完成）
  - [x] SubTask 6.6: 实现 _cleanup() 方法（清理资源）

## 阶段三：URL修正引擎

- [x] Task 7: 实现URL处理入口（modules/url/handle.py）
  - [x] SubTask 7.1: 实现 URLHandler 类
  - [x] SubTask 7.2: 实现 _compile_patterns() 方法（预编译正则表达式）
  - [x] SubTask 7.3: 实现 rewrite() 方法（URL重写入口）
  - [x] SubTask 7.4: 实现 _detect_encoding() 方法（检测字符集）
  - [x] SubTask 7.5: 实现 _get_handler() 方法（获取内容类型处理器）

- [x] Task 8: 实现HTML处理器（modules/url/html.py）
  - [x] SubTask 8.1: 实现 HTMLHandler 类
  - [x] SubTask 8.2: 实现 _compile_patterns() 方法（预编译标签属性模式）
  - [x] SubTask 8.3: 实现 rewrite() 方法（HTML URL重写）
  - [x] SubTask 8.4: 实现 _rewrite_tag_urls() 方法（重写标签URL）
  - [x] SubTask 8.5: 实现 _rewrite_single_url() 方法（重写单个URL）
  - [x] SubTask 8.6: 实现 _to_proxy_url() 方法（转换为代理URL）
  - [x] SubTask 8.7: 实现 _rewrite_style_urls() 方法（重写内联样式URL）
  - [x] SubTask 8.8: 实现 _rewrite_srcset() 方法（重写srcset属性）
  - [x] SubTask 8.9: 实现 _handle_base_tag() 方法（处理base标签）

- [x] Task 9: 实现CSS处理器（modules/url/css.py）
  - [x] SubTask 9.1: 实现 CSSHandler 类
  - [x] SubTask 9.2: 实现 _compile_patterns() 方法（预编译URL模式）
  - [x] SubTask 9.3: 实现 rewrite() 方法（CSS URL重写）

- [x] Task 10: 实现JavaScript处理器（modules/url/js.py）
  - [x] SubTask 10.1: 实现 JSHandler 类
  - [x] SubTask 10.2: 实现 _compile_patterns() 方法（预编译URL模式）
  - [x] SubTask 10.3: 实现 rewrite() 方法（JS URL重写）

- [x] Task 11: 实现XML处理器（modules/url/xml.py）
  - [x] SubTask 11.1: 实现 XMLHandler 类
  - [x] SubTask 11.2: 实现 _compile_patterns() 方法（预编译URL模式）
  - [x] SubTask 11.3: 实现 rewrite() 方法（XML URL重写）

- [x] Task 12: 实现JSON处理器（modules/url/json.py）
  - [x] SubTask 12.1: 实现 JSONHandler 类
  - [x] SubTask 12.2: 实现 rewrite() 方法（JSON URL重写）

- [x] Task 13: 实现Location头处理器（modules/url/location.py）
  - [x] SubTask 13.1: 实现 LocationHandler 类
  - [x] SubTask 13.2: 实现 rewrite() 方法（Location头URL重写）

## 阶段四：代理核心引擎

- [x] Task 14: 实现核心代理转发引擎（modules/proxy.py）
  - [x] SubTask 14.1: 实现 ProxyServer 类
  - [x] SubTask 14.2: 实现 start() 方法（启动代理服务器）
  - [x] SubTask 14.3: 实现 stop() 方法（停止服务器）
  - [x] SubTask 14.4: 实现 _handle_connection() 方法（处理客户端连接）
  - [x] SubTask 14.5: 实现 _process_request() 方法（处理HTTP请求）
  - [x] SubTask 14.6: 实现 _parse_request_line() 方法（解析请求行）
  - [x] SubTask 14.7: 实现 _parse_headers() 方法（解析请求头）
  - [x] SubTask 14.8: 实现 _parse_target_url() 方法（解析目标URL）
  - [x] SubTask 14.9: 实现 _build_forward_headers() 方法（构建转发请求头）
  - [x] SubTask 14.10: 实现 _send_response() 方法（发送响应）
  - [x] SubTask 14.11: 实现 _decompress_content() 方法（解压缩）
  - [x] SubTask 14.12: 实现 _compress_content() 方法（压缩）
  - [x] SubTask 14.13: 实现 _should_rewrite() 方法（判断是否需要URL修正）
  - [x] SubTask 14.14: 实现 _send_error() 方法（发送错误响应）
  - [x] SubTask 14.15: 实现重定向处理逻辑
  - [x] SubTask 14.16: 实现大文件流式传输逻辑

## 阶段五：辅助模块

- [x] Task 15: 实现静态网站服务器（modules/pageserver.py）
  - [x] SubTask 15.1: 实现 PageServer 类
  - [x] SubTask 15.2: 实现 handle_request() 方法（处理静态文件请求）
  - [x] SubTask 15.3: 实现 _match_route() 方法（匹配路由）
  - [x] SubTask 15.4: 实现 _build_file_path() 方法（构建文件路径）
  - [x] SubTask 15.5: 实现 _is_safe_path() 方法（检查路径安全性）
  - [x] SubTask 15.6: 实现 _get_mime_type() 方法（获取MIME类型）
  - [x] SubTask 15.7: 实现 handle_large_file() 方法（处理大文件）

- [x] Task 16: 实现控制台命令模块（modules/command.py）
  - [x] SubTask 16.1: 实现 CommandHandler 类
  - [x] SubTask 16.2: 实现 _setup_routes() 方法（设置路由）
  - [x] SubTask 16.3: 实现 start() 方法（启动命令服务器）
  - [x] SubTask 16.4: 实现 list_commands() 方法（列出所有命令）
  - [x] SubTask 16.5: 实现 start_service() 方法（启动服务）
  - [x] SubTask 16.6: 实现 pause_service() 方法（暂停服务）
  - [x] SubTask 16.7: 实现 exit_service() 方法（优雅退出）
  - [x] SubTask 16.8: 实现 get_status() 方法（获取系统状态）
  - [x] SubTask 16.9: 实现 clear_cache() 方法（清除缓存）
  - [x] SubTask 16.10: 实现 _delayed_exit() 方法（延迟退出）

## 阶段六：主程序集成

- [x] Task 17: 实现程序主入口（SilkRoad.py）
  - [x] SubTask 17.1: 实现 SilkRoad 类
  - [x] SubTask 17.2: 实现 initialize() 方法（初始化所有模块）
  - [x] SubTask 17.3: 实现 run() 方法（启动主服务）
  - [x] SubTask 17.4: 实现 wait_for_shutdown() 方法（等待关闭信号）
  - [x] SubTask 17.5: 实现主程序入口（__main__）

## 阶段七：测试与验证

- [x] Task 18: 创建基础测试
  - [x] SubTask 18.1: 创建 tests/ 目录
  - [x] SubTask 18.2: 创建 tests/test_url_rewrite.py（URL修正测试）
  - [x] SubTask 18.3: 创建 tests/test_proxy.py（代理功能测试）
  - [x] SubTask 18.4: 创建 tests/test_config.py（配置管理测试）

- [x] Task 19: 功能验证
  - [x] SubTask 19.1: 验证配置加载功能
  - [x] SubTask 19.2: 验证日志记录功能
  - [x] SubTask 19.3: 验证代理转发功能
  - [x] SubTask 19.4: 验证URL修正功能
  - [x] SubTask 19.5: 验证静态文件服务
  - [x] SubTask 19.6: 验证命令接口
  - [x] SubTask 19.7: 验证优雅退出

# Task Dependencies

- [Task 3] depends on [Task 1] - 配置管理需要目录结构
- [Task 4] depends on [Task 3] - 日志服务需要配置管理
- [Task 5] depends on [Task 2] - UA模块需要UA数据文件
- [Task 6] depends on [Task 4] - 优雅退出需要日志服务
- [Task 7] depends on [Task 3, Task 4] - URL处理需要配置和日志
- [Task 8-13] depend on [Task 7] - 各处理器依赖URL处理入口
- [Task 14] depends on [Task 5, Task 7] - 代理引擎依赖UA和URL处理
- [Task 15] depends on [Task 3, Task 4] - 静态服务器需要配置和日志
- [Task 16] depends on [Task 14] - 命令模块依赖代理服务器
- [Task 17] depends on [Task 3, Task 4, Task 14, Task 16] - 主入口依赖所有核心模块
- [Task 18-19] depend on [Task 17] - 测试验证依赖完整系统

# Parallelizable Work

以下任务可以并行执行：
- Task 3, Task 4, Task 5, Task 6（基础模块，相互独立）
- Task 8, Task 9, Task 10, Task 11, Task 12, Task 13（URL处理器，相互独立）
- Task 15, Task 16（辅助模块，相互独立）
- Task 18, Task 19（测试验证，可并行）
