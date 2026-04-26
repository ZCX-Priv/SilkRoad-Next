# SilkRoad-Next V2 功能实现 Spec

## Why
V1 版本已实现基础反向代理功能，但缺乏性能优化、访问控制和定制化能力。V2 版本通过引入连接池、线程池、会话管理、缓存管理、黑名单拦截和脚本注入等模块，大幅提升系统性能、安全性和可扩展性。

## What Changes
- 新增 `modules/connectionpool.py` - 目标服务器连接池管理
- 新增 `modules/threadpool.py` - CPU 密集型任务线程池
- 新增 `modules/sessions.py` - 客户端会话管理
- 新增 `modules/cachemanager.py` - 内存与磁盘缓存管理
- 新增 `modules/blacklist.py` - IP/域名/URL 黑名单拦截
- 新增 `modules/scripts.py` - 前端 JS 脚本注入
- 新增 `databases/blacklist.json` - 黑名单配置文件
- 新增 `databases/scripts.json` - 脚本注入配置文件
- 新增 `Scripts/` 目录及示例脚本
- 修改 `SilkRoad.py` - 集成 V2 模块到主程序
- 修改 `modules/proxy.py` - 集成 V2 功能到代理服务器
- 修改 `databases/config.json` - 添加 V2 配置项

## Impact
- Affected specs: V1 基础代理功能、配置管理、命令处理器
- Affected code: 
  - `SilkRoad.py` - 主程序初始化流程
  - `modules/proxy.py` - 请求处理流程
  - `databases/config.json` - 配置结构

## ADDED Requirements

### Requirement: 连接池管理
系统应提供目标服务器连接池管理功能，维护与高频目标服务器的长连接，降低 TLS 握手开销。

#### Scenario: 连接复用
- **WHEN** 多个请求访问同一目标服务器
- **THEN** 系统应复用现有连接而非创建新连接

#### Scenario: 连接超时清理
- **WHEN** 连接超过 keepalive 超时时间未使用
- **THEN** 系统应自动关闭并移除该连接

#### Scenario: 连接池已满
- **WHEN** 连接池达到最大连接数限制
- **THEN** 系统应拒绝新连接请求或等待现有连接释放

### Requirement: 线程池管理
系统应提供线程池管理功能，将 CPU 密集型任务（解压缩、正则替换）交由独立线程池处理，防止阻塞主事件循环。

#### Scenario: CPU 密集型任务执行
- **WHEN** 需要执行解压缩或大规模正则替换
- **THEN** 系统应在线程池中执行而非主事件循环

#### Scenario: 任务超时处理
- **WHEN** 任务执行超过设定的超时时间
- **THEN** 系统应取消任务并抛出 TimeoutError

#### Scenario: 批量任务执行
- **WHEN** 需要并发执行多个 CPU 密集型任务
- **THEN** 系统应支持批量提交并返回结果列表

### Requirement: 会话管理
系统应提供客户端会话管理功能，支持会话创建、更新、查询、删除和持久化。

#### Scenario: 会话创建
- **WHEN** 新客户端首次访问
- **THEN** 系统应创建新会话并返回唯一会话 ID

#### Scenario: 会话过期
- **WHEN** 会话超过超时时间未活动
- **THEN** 系统应自动删除该会话

#### Scenario: 会话持久化
- **WHEN** 系统关闭时
- **THEN** 系统应保存会话数据到文件

### Requirement: 缓存管理
系统应提供内存与磁盘缓存管理功能，支持缓存过期、LRU 淘汰策略和缓存大小限制。

#### Scenario: 缓存命中
- **WHEN** 请求的资源在缓存中且未过期
- **THEN** 系统应直接返回缓存数据

#### Scenario: 缓存淘汰
- **WHEN** 缓存大小超过限制
- **THEN** 系统应淘汰最近最少使用的缓存项

#### Scenario: 缓存过期清理
- **WHEN** 定期清理任务执行
- **THEN** 系统应删除所有过期缓存

### Requirement: 黑名单拦截
系统应提供多层次访问控制，支持 IP 黑名单、IP 范围黑名单、域名黑名单、URL 黑名单和正则表达式匹配。

#### Scenario: IP 黑名单拦截
- **WHEN** 客户端 IP 在黑名单中
- **THEN** 系统应拒绝请求并返回 403 错误

#### Scenario: 白名单优先
- **WHEN** 客户端 IP 同时在黑名单和白名单中
- **THEN** 系统应允许请求（白名单优先）

#### Scenario: 热重载配置
- **WHEN** 黑名单配置文件被修改
- **THEN** 系统应支持热重载配置无需重启

### Requirement: 脚本注入
系统应提供前端 JS 脚本注入功能，支持基于 URL 模式和内容类型的条件注入。

#### Scenario: 条件注入
- **WHEN** 响应内容类型为 text/html 且 URL 匹配配置的模式
- **THEN** 系统应注入配置的脚本

#### Scenario: 脚本位置控制
- **WHEN** 配置脚本注入位置为 head_end 或 body_end
- **THEN** 系统应将脚本注入到指定位置

#### Scenario: 脚本优先级
- **WHEN** 多个脚本匹配同一 URL
- **THEN** 系统应按优先级顺序注入脚本

## MODIFIED Requirements

### Requirement: 主程序初始化
V1 的主程序初始化流程需要扩展以支持 V2 模块的初始化。

**修改内容**：
- 在 V1 初始化流程后添加 V2 模块初始化步骤
- 添加连接池、线程池、会话管理器、缓存管理器、黑名单管理器、脚本注入器的初始化
- 所有 V2 模块通过配置开关控制是否启用

### Requirement: 代理服务器请求处理
V1 的代理服务器请求处理流程需要扩展以集成 V2 功能。

**修改内容**：
- 在请求处理开始时检查黑名单
- 在转发请求前检查缓存
- 使用连接池管理目标服务器连接
- 使用线程池处理 CPU 密集型任务
- 在响应返回前执行脚本注入
- 在响应返回后更新缓存

### Requirement: 配置文件结构
V1 的配置文件需要扩展以支持 V2 配置项。

**修改内容**：
- 启用 `cache` 配置项
- 启用 `performance.connectionPool` 配置项
- 启用 `performance.threadPool` 配置项
- 新增 `v2.session` 配置项
- 新增 `v2.blacklist` 配置项
- 新增 `v2.scripts` 配置项

## REMOVED Requirements
无移除的需求。V2 完全向后兼容 V1。
