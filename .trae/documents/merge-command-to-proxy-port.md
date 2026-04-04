# 合并 Command 接口到代理端口计划

## 目标
将 `/command` 管理接口从独立的 8081 端口合并到代理服务器的 8080 端口，实现统一入口。

## 架构变更

### 变更前
```
代理服务器 (ProxyServer) → 0.0.0.0:8080 → 代理转发
命令服务器 (CommandHandler) → 127.0.0.1:8081 → /command/* 处理
```

### 变更后
```
统一代理服务器 (ProxyServer) → 0.0.0.0:8080
  ├── /command/status  → 状态查询
  ├── /command/pause   → 暂停服务
  ├── /command/resume  → 恢复服务
  ├── /command/exit    → 优雅退出
  └── 其他路径         → 代理转发
```

## 实施步骤

### 步骤 1: 修改 modules/command.py
**目标**: 将 CommandHandler 从独立服务器改为被 ProxyServer 调用的处理器

**修改内容**:
1. 移除 `start_server()` 方法（不再需要独立启动服务器）
2. 移除 `aiohttp.web.Application` 相关代码
3. 保留并优化核心处理方法:
   - `handle_status()` - 返回状态信息
   - `handle_pause()` - 暂停服务
   - `handle_resume()` - 恢复服务
   - `handle_exit()` - 优雅退出
4. 添加 `handle_request(path, method)` 统一入口方法
5. 返回格式改为字典，由 ProxyServer 转换为 HTTP 响应

### 步骤 2: 修改 modules/proxy.py
**目标**: 在代理服务器中添加命令路径处理

**修改内容**:
1. 在 `handle_request()` 方法开头添加路径判断:
   ```python
   if path.startswith('/command/'):
       return await self._handle_command(path, method, headers)
   ```
2. 添加 `_handle_command()` 私有方法:
   - 解析命令类型 (status/pause/resume/exit)
   - 调用 CommandHandler 处理
   - 返回 JSON 响应

### 步骤 3: 修改 SilkRoad.py
**目标**: 移除独立的命令服务器启动逻辑

**修改内容**:
1. 移除 CommandHandler 服务器创建和启动代码
2. 保留 CommandHandler 实例创建（传递给 ProxyServer）
3. 更新启动信息显示:
   - 移除 "管理接口: http://127.0.0.1:8081/command" 
   - 更新为 "管理接口: http://127.0.0.1:8080/command/*"
4. 更新可用命令提示信息

### 步骤 4: 修改 databases/config.json
**目标**: 简化 command 配置

**修改内容**:
```json
{
  "server": {
    "proxy": {
      "host": "0.0.0.0",
      "port": 8080,
      ...
    },
    "command": {
      "enabled": true
    }
  },
  ...
}
```
- 移除 `host` 和 `port` 配置
- 命令接口访问控制自动与代理服务器 host 保持一致

### 步骤 5: 更新错误页面和静态文件
**目标**: 确保错误页面正常工作

**检查内容**:
- 确认 PageServer 仍然正常工作
- 确认错误页面路径不与 /command 冲突

## 文件修改清单

| 文件 | 操作 | 主要变更 |
|------|------|----------|
| `modules/command.py` | 重构 | 移除服务器逻辑，改为处理器模块 |
| `modules/proxy.py` | 修改 | 添加 /command 路径处理 |
| `SilkRoad.py` | 修改 | 移除独立命令服务器启动 |
| `databases/config.json` | 修改 | 简化 command 配置 |

## 验证步骤

1. **语法检查**: 确保所有修改后的文件语法正确
2. **启动测试**: 运行 `python SilkRoad.py` 确认服务正常启动
3. **命令测试**:
   - `curl http://127.0.0.1:8080/command/status` → 返回状态
   - `curl http://127.0.0.1:8080/command/pause` → 暂停服务
   - `curl http://127.0.0.1:8080/command/resume` → 恢复服务
4. **代理测试**: 确认普通代理请求仍然正常工作

## 风险评估

- **低风险**: 代码重构，不涉及核心代理逻辑变更
- **向后兼容**: 配置文件格式变更，但保持可选字段
- **回滚方案**: Git 可随时回滚到之前版本
