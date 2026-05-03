# Tasks

## Phase 1: 创建 flow 目录和基础架构

- [x] Task 1: 创建 `modules/flow/` 目录和 `__init__.py`
  - [x] SubTask 1.1: 创建 `modules/flow/` 目录
  - [x] SubTask 1.2: 创建 `modules/flow/__init__.py`，定义 FlowType 枚举、FlowContext 数据类，导出公共 API

- [x] Task 2: 创建流量路由器 `modules/flow/router.py`
  - [x] SubTask 2.1: 创建 FlowRouter 类，包含 `__init__` 方法（接收 config、logger、各子处理器）
  - [x] SubTask 2.2: 实现 `identify_flow_type` 方法，根据请求头和 URL 判断流量类型（NORMAL/STREAM/WEBSOCKET）
  - [x] SubTask 2.3: 实现 `route` 方法，根据流量类型路由至对应处理器
  - [x] SubTask 2.4: 实现 `get_stats` 方法，汇总所有处理器的统计信息

## Phase 2: 创建正常流量处理器

- [x] Task 3: 创建正常流量处理器 `modules/flow/normal.py`
  - [x] SubTask 3.1: 创建 NormalHandler 类，包含 `__init__` 方法（接收 config、logger、session、url_handler、cookie_handler、ua_handler）
  - [x] SubTask 3.2: 实现 `handle` 方法，作为正常流量处理的主入口
  - [x] SubTask 3.3: 从 proxy.py 提取 `_forward_request` 逻辑到 NormalHandler 的 `_forward_direct` 方法
  - [x] SubTask 3.4: 从 proxy.py 提取 `_forward_request_with_pool` 逻辑到 NormalHandler 的 `_forward_with_pool` 方法
  - [x] SubTask 3.5: 从 proxy.py 提取 `_send_response` 逻辑到 NormalHandler 的 `_send_response` 方法
  - [x] SubTask 3.6: 从 proxy.py 提取 `_stream_response` 逻辑到 NormalHandler 的 `_stream_response` 方法
  - [x] SubTask 3.7: 从 proxy.py 提取 `_send_cached_response` 逻辑到 NormalHandler 的 `_send_cached_response` 方法
  - [x] SubTask 3.8: 从 proxy.py 提取压缩/解压缩相关方法（`_decompress_content`、`_compress_content`、`_decompress_content_sync`）
  - [x] SubTask 3.9: 从 proxy.py 提取 URL 重写判断方法（`_should_rewrite`）
  - [x] SubTask 3.10: 实现 `get_stats` 方法

## Phase 3: 迁移 stream 模块

- [x] Task 4: 迁移 `modules/stream/handle.py` → `modules/flow/handle.py`
  - [x] SubTask 4.1: 复制文件内容，更新导入路径（`modules.stream` → `modules.flow`）
  - [x] SubTask 4.2: 更新 StreamType 引用为 FlowType（保持 StreamType 作为别名兼容）

- [x] Task 5: 迁移 `modules/stream/media.py` → `modules/flow/media.py`
  - [x] SubTask 5.1: 复制文件内容，更新导入路径（`modules.stream` → `modules.flow`）

- [x] Task 6: 迁移 `modules/stream/sse.py` → `modules/flow/sse.py`
  - [x] SubTask 6.1: 复制文件内容，更新导入路径（`modules.stream` → `modules.flow`）

- [x] Task 7: 迁移 `modules/stream/others.py` → `modules/flow/others.py`
  - [x] SubTask 7.1: 复制文件内容，更新导入路径（`modules.stream` → `modules.flow`）

## Phase 4: 迁移 WebSocket 模块

- [x] Task 8: 迁移 `modules/websockets.py` → `modules/flow/websocket.py`
  - [x] SubTask 8.1: 复制文件内容，更新导入路径

## Phase 5: 重构 ProxyServer

- [x] Task 9: 重构 `modules/proxy.py`，委托流量路由至 FlowRouter
  - [x] SubTask 9.1: 移除 `_is_stream_request` 方法，由 FlowRouter.identify_flow_type 替代
  - [x] SubTask 9.2: 移除 `_is_websocket_upgrade` 方法，由 FlowRouter.identify_flow_type 替代
  - [x] SubTask 9.3: 移除 `_handle_stream_request` 方法，由 FlowRouter.route 替代
  - [x] SubTask 9.4: 移除 `_forward_request`、`_forward_request_with_pool` 方法，由 NormalHandler 替代
  - [x] SubTask 9.5: 移除 `_send_response`、`_stream_response`、`_send_cached_response` 方法，由 NormalHandler 替代
  - [x] SubTask 9.6: 移除 `_decompress_content`、`_compress_content`、`_decompress_content_sync` 方法，由 NormalHandler 替代
  - [x] SubTask 9.7: 移除 `_should_rewrite` 方法，由 NormalHandler 替代
  - [x] SubTask 9.8: 更新 `_process_request` 方法，使用 FlowRouter 进行流量路由
  - [x] SubTask 9.9: 更新 `__init__` 方法，添加 flow_router 和 normal_handler 属性，移除旧的 stream/websocket handler 属性
  - [x] SubTask 9.10: 更新 `get_stats` 方法，使用 FlowRouter 的统计接口
  - [x] SubTask 9.11: 更新 `reset_stream_stats`、`set_stream_rate_limit`、`get_stream_rate_limit_status` 方法

## Phase 6: 更新入口和引用

- [x] Task 10: 更新 `SilkRoad.py` 导入路径和初始化逻辑
  - [x] SubTask 10.1: 更新导入路径（`modules.stream.*` → `modules.flow.*`，`modules.websockets` → `modules.flow.websocket`）
  - [x] SubTask 10.2: 更新初始化逻辑，创建 FlowRouter 和 NormalHandler
  - [x] SubTask 10.3: 更新模块注入逻辑，注入 flow_router 和 normal_handler 到 ProxyServer
  - [x] SubTask 10.4: 更新 shutdown 逻辑，使用新的模块路径

- [x] Task 11: 更新 `modules/command.py` 引用
  - [x] SubTask 11.1: 更新对 `proxy.sse_handler` 的引用为 `proxy.flow_router.stream_handler.sse_handler` 或提供兼容属性
  - [x] SubTask 11.2: 更新对 `proxy.media_handler` 的引用

## Phase 7: 清理旧模块

- [x] Task 12: 删除旧的 `modules/stream/` 目录
  - [x] SubTask 12.1: 确认所有导入已更新后，删除 `modules/stream/` 目录

- [x] Task 13: 删除旧的 `modules/websockets.py` 文件
  - [x] SubTask 13.1: 确认所有导入已更新后，删除 `modules/websockets.py`

## Phase 8: 验证

- [x] Task 14: 验证功能完整性
  - [x] SubTask 14.1: 验证正常 HTTP 请求代理功能正常
  - [x] SubTask 14.2: 验证流式请求（媒体流、SSE）代理功能正常
  - [x] SubTask 14.3: 验证 WebSocket 代理功能正常
  - [x] SubTask 14.4: 验证缓存、黑名单、脚本注入等 V2 功能正常
  - [x] SubTask 14.5: 验证命令接口统计信息正常

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4, 5, 6, 7, 8 可并行执行
- Task 9 依赖 Task 2, Task 3, Task 4, Task 8
- Task 10 依赖 Task 9
- Task 11 依赖 Task 9
- Task 12, 13 依赖 Task 10, Task 11
- Task 14 依赖 Task 12, Task 13
