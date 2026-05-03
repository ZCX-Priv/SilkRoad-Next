# 统一流量处理至 flow 模块实现检查清单

## 基础架构检查
- [x] `modules/flow/` 目录已创建
- [x] `modules/flow/__init__.py` 已创建，包含 FlowType 枚举和 FlowContext 数据类
- [x] `modules/flow/router.py` 已创建，FlowRouter 类实现完整
- [x] `modules/flow/normal.py` 已创建，NormalHandler 类实现完整

## FlowRouter 功能检查
- [x] FlowRouter.identify_flow_type 能正确识别 NORMAL 类型流量
- [x] FlowRouter.identify_flow_type 能正确识别 STREAM 类型流量
- [x] FlowRouter.identify_flow_type 能正确识别 WEBSOCKET 类型流量
- [x] FlowRouter.route 能正确路由到 NormalHandler
- [x] FlowRouter.route 能正确路由到 StreamHandler
- [x] FlowRouter.route 能正确路由到 WebSocketHandler
- [x] FlowRouter.route 在处理器未初始化时能正确降级
- [x] FlowRouter.get_stats 能返回所有处理器的统计信息

## NormalHandler 功能检查
- [x] NormalHandler.handle 能正确处理正常 HTTP 请求
- [x] NormalHandler 能正确使用连接池转发请求
- [x] NormalHandler 在连接池不可用时能降级到直连转发
- [x] NormalHandler 能正确处理大文件流式传输
- [x] NormalHandler 能正确处理缓存响应
- [x] NormalHandler 能正确解压缩响应内容（gzip/deflate）
- [x] NormalHandler 能正确压缩响应内容
- [x] NormalHandler 能正确判断是否需要 URL 重写
- [x] NormalHandler 能正确处理重定向
- [x] NormalHandler 能正确处理 Cookie（Set-Cookie 重写）
- [x] NormalHandler 能正确处理脚本注入
- [x] NormalHandler.get_stats 能返回正确的统计信息

## 迁移检查
- [x] `modules/flow/handle.py` 已从 `modules/stream/handle.py` 迁移，导入路径已更新
- [x] `modules/flow/media.py` 已从 `modules/stream/media.py` 迁移，导入路径已更新
- [x] `modules/flow/sse.py` 已从 `modules/stream/sse.py` 迁移，导入路径已更新
- [x] `modules/flow/others.py` 已从 `modules/stream/others.py` 迁移，导入路径已更新
- [x] `modules/flow/websocket.py` 已从 `modules/websockets.py` 迁移，导入路径已更新

## ProxyServer 重构检查
- [x] ProxyServer 不再包含 `_is_stream_request` 方法
- [x] ProxyServer 不再包含 `_is_websocket_upgrade` 方法
- [x] ProxyServer 不再包含 `_handle_stream_request` 方法
- [x] ProxyServer 不再包含 `_forward_request` 方法
- [x] ProxyServer 不再包含 `_forward_request_with_pool` 方法
- [x] ProxyServer 不再包含 `_send_response` 方法
- [x] ProxyServer 不再包含 `_stream_response` 方法
- [x] ProxyServer 不再包含 `_send_cached_response` 方法
- [x] ProxyServer 不再包含 `_decompress_content`、`_compress_content`、`_decompress_content_sync` 方法
- [x] ProxyServer 不再包含 `_should_rewrite` 方法
- [x] ProxyServer._process_request 使用 FlowRouter 进行流量路由
- [x] ProxyServer 包含 flow_router 和 normal_handler 属性

## 入口和引用更新检查
- [x] SilkRoad.py 导入路径已更新（modules.flow.* 替代 modules.stream.*）
- [x] SilkRoad.py 导入路径已更新（modules.flow.websocket 替代 modules.websockets）
- [x] SilkRoad.py 初始化逻辑已更新，创建 FlowRouter 和 NormalHandler
- [x] SilkRoad.py 模块注入逻辑已更新
- [x] SilkRoad.py shutdown 逻辑已更新
- [x] modules/command.py 对 handler 的引用已更新

## 清理检查
- [x] `modules/stream/` 目录已删除
- [x] `modules/websockets.py` 文件已删除
- [x] 项目中无残留的 `modules.stream` 导入
- [x] 项目中无残留的 `modules.websockets` 导入

## 功能验证检查
- [x] 正常 HTTP 请求代理功能正常
- [x] 流式请求（媒体流）代理功能正常
- [x] 流式请求（SSE）代理功能正常
- [x] WebSocket 代理功能正常
- [x] 缓存功能正常
- [x] 黑名单功能正常
- [x] 脚本注入功能正常
- [x] 命令接口统计信息正常
- [x] 流量整形功能正常
