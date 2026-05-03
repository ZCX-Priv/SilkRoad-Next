# 统一流量处理至 flow 模块 Spec

## Why
当前流量处理逻辑分散在 `modules/proxy.py`（正常流量）、`modules/stream/`（流式流量）、`modules/websockets.py`（WebSocket 流量）中，路由判断逻辑耦合在 ProxyServer 内部，导致代码难以维护和扩展。需要将所有流量处理统一收敛至 `modules/flow/` 目录，通过 `router.py` 按流量类型路由至对应模块，`normal.py` 处理正常 HTTP 流量，使架构清晰、职责分明。

## What Changes
- 新增 `modules/flow/` 目录，统一所有流量处理
- 新增 `modules/flow/__init__.py` - 流量模块初始化，导出 FlowType、FlowContext 等公共类型
- 新增 `modules/flow/router.py` - 流量路由器，根据请求特征路由至对应处理模块
- 新增 `modules/flow/normal.py` - 正常 HTTP 流量处理器（从 proxy.py 提取）
- 迁移 `modules/stream/handle.py` → `modules/flow/handle.py`
- 迁移 `modules/stream/media.py` → `modules/flow/media.py`
- 迁移 `modules/stream/sse.py` → `modules/flow/sse.py`
- 迁移 `modules/stream/others.py` → `modules/flow/others.py`
- 迁移 `modules/websockets.py` → `modules/flow/websocket.py`
- 删除 `modules/stream/` 目录（迁移完成后）
- 修改 `modules/proxy.py` - 移除内联流量路由逻辑，委托给 FlowRouter
- 修改 `SilkRoad.py` - 更新导入路径和初始化逻辑
- 修改 `modules/command.py` - 更新对 handler 的引用路径

## Impact
- Affected specs: V1基础代理, V2性能优化, V3流媒体支持, V4 WebSocket
- Affected code:
  - modules/proxy.py (核心变更：移除流量路由逻辑，委托给 FlowRouter)
  - SilkRoad.py (更新导入路径和初始化)
  - modules/command.py (更新 handler 引用)
  - modules/stream/* (迁移至 modules/flow/)
  - modules/websockets.py (迁移至 modules/flow/websocket.py)

## ADDED Requirements

### Requirement: 流量路由器 (FlowRouter)
系统 SHALL 提供 FlowRouter 类，根据请求特征将流量路由至对应的处理模块。

#### Scenario: 识别正常 HTTP 流量
- **WHEN** 请求不满足 WebSocket 升级条件、不满足流式请求条件
- **THEN** FlowRouter 将请求路由至 NormalHandler 处理

#### Scenario: 识别流式流量
- **WHEN** 请求头或 URL 表明为流式请求（媒体流、SSE、分块传输等）
- **THEN** FlowRouter 将请求路由至 StreamHandler 处理

#### Scenario: 识别 WebSocket 流量
- **WHEN** 请求头包含 Upgrade: websocket 且满足 WebSocket 升级条件
- **THEN** FlowRouter 将请求路由至 WebSocketHandler 处理

#### Scenario: 降级处理
- **WHEN** 对应的处理器未初始化
- **THEN** FlowRouter 降级到基本处理方式（如普通流式传输）

### Requirement: 正常流量处理器 (NormalHandler)
系统 SHALL 提供 NormalHandler 类，处理正常 HTTP 流量（非流式、非 WebSocket）。

#### Scenario: 使用连接池转发
- **WHEN** 连接池可用且正常 HTTP 请求到达
- **THEN** NormalHandler 使用连接池转发请求，支持重定向、URL重写、压缩、缓存等

#### Scenario: 降级到直连转发
- **WHEN** 连接池不可用
- **THEN** NormalHandler 使用直连方式转发请求

#### Scenario: 大文件流式传输
- **WHEN** 响应 Content-Length 超过流式阈值
- **THEN** NormalHandler 使用流式传输方式发送响应

### Requirement: 流量类型枚举 (FlowType)
系统 SHALL 提供 FlowType 枚举，定义所有流量类型。

#### Scenario: 流量类型定义
- **WHEN** 系统初始化
- **THEN** FlowType 包含 NORMAL、STREAM、WEBSOCKET 三种类型

### Requirement: 统一目录结构
系统 SHALL 将所有流量处理模块统一放置在 `modules/flow/` 目录下。

#### Scenario: 目录结构
- **WHEN** 迁移完成
- **THEN** `modules/flow/` 目录包含以下文件：`__init__.py`、`router.py`、`normal.py`、`handle.py`、`media.py`、`sse.py`、`others.py`、`websocket.py`

## MODIFIED Requirements

### Requirement: ProxyServer 流量处理
原需求：ProxyServer 内部直接判断流量类型并路由到不同处理器
修改后：ProxyServer 委托 FlowRouter 进行流量类型判断和路由，自身仅负责连接管理和请求解析

### Requirement: 流处理器模块路径
原需求：流处理器位于 `modules/stream/` 目录
修改后：流处理器位于 `modules/flow/` 目录，导入路径从 `modules.stream.*` 变更为 `modules.flow.*`

### Requirement: WebSocket 处理器模块路径
原需求：WebSocket 处理器位于 `modules/websockets.py`
修改后：WebSocket 处理器位于 `modules/flow/websocket.py`，导入路径从 `modules.websockets` 变更为 `modules.flow.websocket`

## REMOVED Requirements

### Requirement: modules/stream/ 目录
**Reason**: 所有流处理模块已迁移至 `modules/flow/`，原目录不再需要
**Migration**: 将 `modules/stream/` 下所有文件迁移至 `modules/flow/`，更新所有导入路径

### Requirement: modules/websockets.py 独立文件
**Reason**: WebSocket 处理器已迁移至 `modules/flow/websocket.py`，统一流量处理架构
**Migration**: 将 `modules/websockets.py` 内容迁移至 `modules/flow/websocket.py`，更新所有导入路径
