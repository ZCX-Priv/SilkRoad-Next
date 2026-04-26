# WAF 穿透模块 Spec

## Why
SilkRoad-Next 需要在严格网络环境下保持可用性。当前版本(V1-V4)虽然具备基础代理、性能优化、流媒体支持和流量控制能力，但缺乏应对 WAF (Web Application Firewall) 拦截的能力，导致在访问受 WAF 保护的网站时会被拦截。V5 版本通过引入 WAF 穿透模块，实现请求特征混淆、反爬虫机制绕过和 JavaScript 挑战求解，极大提升代理在严格网络环境下的可用性。

## What Changes
- 创建 `modules/wafpasser.py` - WAF 穿透核心模块
- 扩展 `databases/config.json` - 添加 WAF 穿透相关配置
- 创建 `databases/waf_signatures.json` - WAF 指纹数据库
- 创建 `databases/sessions/` 目录 - 会话持久化存储
- 集成到 V1 的代理引擎 (`modules/proxy.py`)
- 集成到 V2 的连接池 (`modules/connectionpool.py`)
- 集成到 V3 的流媒体处理 (`modules/stream/handle.py`)
- 集成到 V4 的流量控制器 (`modules/controler.py`)
- 创建测试文件 `tests/test_wafpasser.py`

## Impact
- Affected specs: V1 (proxy.py), V2 (connectionpool.py), V3 (stream/), V4 (controler.py)
- Affected code: modules/proxy.py, modules/connectionpool.py, modules/stream/handle.py, modules/controler.py, SilkRoad.py

## ADDED Requirements

### Requirement: WAF 类型识别与指纹检测
系统 SHALL 提供智能 WAF 类型识别功能，能够通过响应头、状态码和页面内容识别主流 WAF 类型。

#### Scenario: 检测 Cloudflare WAF
- **WHEN** 响应包含 `Server: cloudflare` 头或 `CF-RAY` 头，且状态码为 403 或 503
- **THEN** 系统识别为 Cloudflare WAF，置信度 > 0.5

#### Scenario: 检测 Akamai WAF
- **WHEN** 响应包含 `Server: AkamaiGHost` 头，且状态码为 403
- **THEN** 系统识别为 Akamai WAF，置信度 > 0.5

#### Scenario: 检测 Imperva WAF
- **WHEN** 响应包含 `X-CDN: Incapsula` 头或 Cookie 包含 `incap_ses_` 前缀
- **THEN** 系统识别为 Imperva WAF，置信度 > 0.5

#### Scenario: 检测通用 WAF
- **WHEN** 响应状态码为 403/406/429/503 且页面包含 "forbidden"、"blocked" 等关键词
- **THEN** 系统识别为通用 WAF 拦截

### Requirement: 请求特征混淆
系统 SHALL 提供请求特征混淆功能，包括 User-Agent 轮换、请求头伪装、Referer 伪造等。

#### Scenario: User-Agent 轮换
- **WHEN** 启用 WAF 穿透功能
- **THEN** 系统从 UA 池中随机选择 User-Agent，模拟真实浏览器

#### Scenario: 请求头混淆
- **WHEN** 向目标网站发送请求
- **THEN** 系统自动添加完整的浏览器指纹请求头（Accept、Accept-Language、sec-ch-ua 等）

#### Scenario: WAF 特定请求头
- **WHEN** 检测到特定 WAF 类型
- **THEN** 系统添加该 WAF 特定的请求头（如 Cloudflare 的 CF-Connecting-IP）

### Requirement: JavaScript 挑战求解
系统 SHALL 提供自动求解 JavaScript 挑战的能力，主要用于 Cloudflare 等需要客户端计算的 WAF。

#### Scenario: 检测 JavaScript 挑战
- **WHEN** 响应页面包含 `challenge-platform` 标识
- **THEN** 系统识别为 JavaScript 挑战页面

#### Scenario: 求解 Cloudflare 挑战
- **WHEN** 检测到 Cloudflare JavaScript 挑战
- **THEN** 系统提取挑战参数，执行 JavaScript 计算，构造响应请求

#### Scenario: 挑战求解超时
- **WHEN** JavaScript 挑战求解超过 10 秒
- **THEN** 系统返回 None，记录超时日志

### Requirement: 会话持久化管理
系统 SHALL 提供会话持久化功能，保存验证后的 Cookie 和 Token，避免重复验证。

#### Scenario: 保存会话
- **WHEN** 成功通过 WAF 验证
- **THEN** 系统保存会话 ID、Cookie、域名等信息到本地存储

#### Scenario: 加载会话
- **WHEN** 后续请求访问相同域名
- **THEN** 系统自动加载已保存的会话 Cookie

#### Scenario: 会话过期清理
- **WHEN** 会话超过 48 小时未更新
- **THEN** 系统自动清理过期会话文件

### Requirement: 多策略绕过机制
系统 SHALL 提供 8 种不同的绕过策略，并根据历史成功率自适应调整策略优先级。

#### Scenario: 策略优先级排序
- **WHEN** 启用 WAF 穿透
- **THEN** 系统按优先级顺序尝试绕过策略（UA 轮换 -> 请求头混淆 -> Referer 伪造 -> ...）

#### Scenario: 自适应延迟
- **WHEN** 历史成功率低于 50%
- **THEN** 系统增加请求延迟至 5-10 秒

#### Scenario: 策略成功率记录
- **WHEN** 某策略成功绕过 WAF
- **THEN** 系统记录该策略的成功次数，用于后续优化

### Requirement: 性能监控与日志
系统 SHALL 提供 WAF 穿透性能监控和详细日志记录。

#### Scenario: 记录检测耗时
- **WHEN** 执行 WAF 检测
- **THEN** 系统记录检测耗时，计算平均值

#### Scenario: 记录绕过尝试
- **WHEN** 尝试绕过策略
- **THEN** 系统记录策略名称、成功状态、耗时

#### Scenario: 日志输出
- **WHEN** 发生 WAF 检测或绕过事件
- **THEN** 系统使用 loguru 输出结构化日志

## MODIFIED Requirements

### Requirement: V1 代理引擎集成
V1 的 `modules/proxy.py` SHALL 集成 WAF 穿透功能，在请求转发前后进行 WAF 检测和绕过处理。

#### Scenario: 请求预处理
- **WHEN** 接收到客户端请求
- **THEN** 系统使用 RequestObfuscator 混淆请求头

#### Scenario: 响应后处理
- **WHEN** 收到目标服务器响应
- **THEN** 系统检测是否被 WAF 拦截，如被拦截则尝试绕过

### Requirement: V2 连接池集成
V2 的 `modules/connectionpool.py` SHALL 支持会话持久化，在创建连接时加载已保存的会话 Cookie。

#### Scenario: 使用会话创建连接
- **WHEN** 提供会话 ID 创建连接
- **THEN** 系统加载会话数据中的 Cookie 并应用到连接

### Requirement: V3 流媒体处理集成
V3 的 `modules/stream/handle.py` SHALL 在流媒体请求中集成 WAF 检测。

#### Scenario: 流媒体请求拦截检测
- **WHEN** 流媒体请求返回 403/503 状态码
- **THEN** 系统检测是否被 WAF 拦截

### Requirement: V4 流量控制器集成
V4 的 `modules/controler.py` SHALL 集成 WAF 穿透策略，实现自适应请求调度。

#### Scenario: 自适应请求调度
- **WHEN** 调度请求
- **THEN** 系统根据历史成功率计算延迟，应用绕过请求头

### Requirement: 配置文件扩展
`databases/config.json` SHALL 添加 WAF 穿透相关配置项。

#### Scenario: WAF 穿透配置
- **WHEN** 配置文件包含 `waf_evasion` 字段
- **THEN** 系统启用对应的绕过策略

## REMOVED Requirements
无移除的需求。
