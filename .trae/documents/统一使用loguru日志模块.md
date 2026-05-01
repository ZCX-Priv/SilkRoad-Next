# 修改计划：统一使用 loguru 日志模块

## 问题背景

项目已有完善的 loguru 封装模块 `modules/logging.py`，但以下 **9 个文件** 仍在使用标准 `logging` 模块：

| 序号 | 文件路径 |
|------|----------|
| 1 | `modules/stream/others.py` |
| 2 | `modules/stream/sse.py` |
| 3 | `modules/stream/media.py` |
| 4 | `modules/stream/handle.py` |
| 5 | `modules/sessions.py` |
| 6 | `modules/scripts.py` |
| 7 | `modules/websockets.py` |
| 8 | `modules/controler.py` |
| 9 | `modules/connectionpool.py` |

## 修改内容

### 1. 导入语句修改

```python
# 修改前
import logging

# 修改后
from loguru import logger
```

### 2. logger 初始化修改

```python
# 修改前
self.logger = logger or logging.getLogger(__name__)
# 或
self._logger = logger or logging.getLogger(__name__)

# 修改后
self.logger = logger
# 或
self._logger = logger
```

### 3. `exc_info=True` 参数修改

部分文件使用了 `exc_info=True` 参数，需要改为 loguru 的方式：

```python
# 修改前
self.logger.error(f"错误信息: {e}", exc_info=True)

# 修改后
self.logger.opt(exception=True).error(f"错误信息: {e}")
```

需要修改 `exc_info=True` 的位置：
- `modules/stream/others.py` 第 165 行
- `modules/stream/sse.py` 第 250 行
- `modules/stream/media.py` 第 194 行

### 4. 保持不变

- `if TYPE_CHECKING: from modules.logging import Logger` 类型检查导入保持不变
- 所有 `self.logger.info/debug/warning/error` 调用保持不变（loguru API 兼容）

## 执行步骤

1. 修改 `modules/stream/others.py`
2. 修改 `modules/stream/sse.py`
3. 修改 `modules/stream/media.py`
4. 修改 `modules/stream/handle.py`
5. 修改 `modules/sessions.py`
6. 修改 `modules/scripts.py`
7. 修改 `modules/websockets.py`
8. 修改 `modules/controler.py`
9. 修改 `modules/connectionpool.py`
10. 验证修改结果
