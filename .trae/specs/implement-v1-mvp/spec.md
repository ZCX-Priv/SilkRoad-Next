# SilkRoad-Next V1 MVP 实现规范

## Why

构建一个高性能、可扩展的反向代理软件的最小可行性版本（MVP），实现基础的反向代理功能与URL重写核心，帮助用户突破网络访问限制、保护隐私安全并提升连接速度。为后续版本迭代（V2-V5）奠定坚实基础。

## What Changes

- 创建项目基础架构和目录结构
- 实现配置管理系统（cfg.py）
- 实现日志服务系统（logging.py）
- 实现User-Agent随机化模块（ua.py）
- 实现优雅退出机制（exit.py）
- 实现核心代理转发引擎（proxy.py）
- 实现URL修正核心模块（url/ 目录下7个处理器）
- 实现静态网站服务器（pageserver.py）
- 实现控制台命令接口（command.py）
- 创建程序主入口（SilkRoad.py）
- 创建配置文件和数据文件（databases/）
- 创建静态资源目录和错误页面（pages/）
- 创建依赖清单（requirements.txt）

## Impact

- **新增功能**：
  - HTTP/HTTPS反向代理能力
  - 精准的URL修正引擎（支持HTML/CSS/JS/XML/JSON）
  - 静态网站托管服务
  - RESTful管理接口
  - 完善的日志系统
  - 优雅退出机制

- **性能指标**：
  - 支持2000+并发连接
  - URL处理延迟<50ms
  - 异步I/O模型

- **影响范围**：
  - 创建全新的项目结构
  - 无破坏性变更（新项目）

## ADDED Requirements

### Requirement: 项目基础架构

系统SHALL提供完整的项目目录结构，包括：
- `modules/` 目录：存放所有核心功能模块
- `databases/` 目录：存放配置文件和数据文件
- `pages/` 目录：存放静态网站资源
- `logs/` 目录：存放运行日志
- `SilkRoad.py`：程序主入口
- `requirements.txt`：依赖清单

#### Scenario: 项目初始化
- **WHEN** 用户首次克隆项目
- **THEN** 所有必需目录已创建
- **AND** 配置文件已生成默认值
- **AND** 依赖可一键安装

### Requirement: 配置管理系统

系统SHALL提供灵活的配置管理功能：
- 支持JSON格式配置文件
- 支持默认配置回退
- 支持配置项验证
- 支持点分隔符访问配置项（如 `server.port`）

#### Scenario: 配置加载成功
- **WHEN** 系统启动时加载配置文件
- **THEN** 配置项被正确解析
- **AND** 无效配置项被检测并报错

#### Scenario: 配置文件缺失
- **WHEN** 配置文件不存在
- **THEN** 系统自动创建默认配置文件
- **AND** 使用默认值继续运行

### Requirement: 日志服务系统

系统SHALL基于loguru实现完善的日志系统：
- 支持多级别日志（INFO/DEBUG/WARN/ERROR）
- 支持按天轮转
- 支持自动清理（可配置保留时间）
- 支持彩色控制台输出
- 支持错误日志单独文件

#### Scenario: 日志记录
- **WHEN** 系统运行过程中产生日志
- **THEN** 日志被正确写入文件
- **AND** 控制台显示彩色日志
- **AND** 日志文件按天轮转

### Requirement: User-Agent随机化

系统SHALL提供UA池管理功能：
- 支持从JSON文件加载UA池
- 支持按类别选择UA（chrome/firefox/safari/mobile）
- 支持随机选择UA
- 支持默认UA回退

#### Scenario: UA选择
- **WHEN** 代理服务器发送请求到目标服务器
- **THEN** 系统随机选择一个UA
- **AND** UA被设置到请求头中

### Requirement: 优雅退出机制

系统SHALL实现优雅退出机制：
- 支持信号处理（SIGINT/SIGTERM）
- 支持等待活动任务完成（最多30秒）
- 支持资源清理
- 支持配置保存

#### Scenario: 接收到退出信号
- **WHEN** 系统接收到SIGINT或SIGTERM信号
- **THEN** 停止接收新请求
- **AND** 等待现有请求完成
- **AND** 清理资源后退出

### Requirement: 核心代理转发引擎

系统SHALL实现完整的反向代理功能：
- 支持HTTP/HTTPS协议
- 支持请求头转发和修改
- 支持请求体转发
- 支持响应处理和URL修正
- 支持压缩和解压缩（gzip/deflate）
- 支持重定向处理（最多10次）
- 支持大文件流式传输

#### Scenario: 正常代理请求
- **WHEN** 客户端发送HTTP请求到代理服务器
- **THEN** 请求被转发到目标服务器
- **AND** 响应被处理后返回给客户端
- **AND** URL被正确修正

#### Scenario: 处理重定向
- **WHEN** 目标服务器返回301/302重定向
- **THEN** 系统自动跟随重定向
- **AND** 更新基础URL用于URL修正

#### Scenario: 处理大文件
- **WHEN** 响应内容超过10MB
- **THEN** 使用流式传输
- **AND** 跳过URL修正步骤

### Requirement: URL修正引擎

系统SHALL实现精准的URL修正功能：
- 支持HTML/CSS/JS/XML/JSON等多种内容类型
- 支持绝对URL修正
- 支持相对URL补全
- 支持协议相对URL处理
- 支持特殊协议跳过（javascript:/mailto:/tel:/data:）
- 支持srcset属性处理
- 支持内联样式URL处理
- 支持字符集自动检测
- 支持URL规范化（去重、补全协议）

#### Scenario: HTML URL修正
- **WHEN** 处理HTML内容
- **THEN** 所有标签中的URL被修正
- **AND** 内联样式中的URL被修正
- **AND** srcset属性被正确处理

#### Scenario: 相对URL补全
- **WHEN** 遇到相对URL
- **THEN** 根据当前URL补全为绝对URL
- **AND** 转换为代理URL格式

#### Scenario: 字符集检测
- **WHEN** 处理文本内容
- **THEN** 正确检测字符集编码
- **AND** 使用正确的编码解码和编码

### Requirement: 静态网站服务器

系统SHALL提供静态文件托管服务：
- 支持多路由映射
- 支持MIME类型自动识别
- 支持默认首页（index.html）
- 支持目录遍历防护
- 支持大文件流式传输

#### Scenario: 静态文件请求
- **WHEN** 客户端请求静态文件
- **THEN** 文件被正确返回
- **AND** MIME类型被正确设置

#### Scenario: 目录遍历防护
- **WHEN** 请求路径包含 `../`
- **THEN** 请求被拒绝
- **AND** 记录安全警告

### Requirement: 控制台命令接口

系统SHALL提供RESTful风格的管理接口：
- `/command` - 列出所有命令
- `/command/start` - 启动服务
- `/command/pause` - 暂停服务
- `/command/exit` - 优雅退出
- `/command/status` - 查看状态
- `/command/clear` - 清除缓存

#### Scenario: 查看系统状态
- **WHEN** 访问 `/command/status`
- **THEN** 返回系统状态信息
- **AND** 包含CPU、内存、连接数等信息

#### Scenario: 优雅退出
- **WHEN** 访问 `/command/exit`
- **THEN** 系统开始优雅退出流程
- **AND** 返回退出确认信息

### Requirement: 程序主入口

系统SHALL提供统一的程序入口：
- 初始化所有核心模块
- 启动代理服务器
- 启动命令服务器
- 协调各模块生命周期
- 处理关闭信号

#### Scenario: 系统启动
- **WHEN** 运行 `python SilkRoad.py`
- **THEN** 所有模块被正确初始化
- **AND** 代理服务器在8080端口启动
- **AND** 命令服务器在8081端口启动

## MODIFIED Requirements

无修改的需求（新项目）

## REMOVED Requirements

无移除的需求（新项目）
