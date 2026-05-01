# 修改计划：补充遗漏的 exc_info 修改

## 问题分析

在之前的修改中，我遗漏了两处 `exc_info=True` 参数的修改。loguru 不支持 `exc_info=True` 参数，需要使用 `opt(exception=True)` 方式。

## 需要修改的位置

| 文件 | 行号 | 当前代码 | 修改后代码 |
|------|------|----------|------------|
| `modules/stream/handle.py` | 329 | `self.logger.error(f"流处理错误 [{stream_id}]: {e}", exc_info=True)` | `self.logger.opt(exception=True).error(f"流处理错误 [{stream_id}]: {e}")` |
| `modules/proxy.py` | 1581 | `self.logger.error(f"流请求处理失败 [{target_url}]: {e}", exc_info=True)` | `self.logger.opt(exception=True).error(f"流请求处理失败 [{target_url}]: {e}")` |

## 执行步骤

1. 修改 `modules/stream/handle.py` 第 329 行
2. 修改 `modules/proxy.py` 第 1581 行
3. 验证修改结果
