# Dock.js 样式优化计划

## 问题分析

### 1. 样式被网页 CSS 覆盖
- 当前样式选择器优先级不够高
- 网页的全局样式（如 `button`、`svg`、`input` 等）会影响 Dock 栏
- 需要增加样式权重，防止被覆盖

### 2. "胖"的问题
- `padding: 12px 20px` - 内边距较大
- 按钮尺寸 `width: 40px; height: 40px` - 按钮偏大
- `gap: 15px` - 按钮间距较大
- `margin-left: 15px` - 元素间距较大

## 修改方案

### 1. 为所有样式添加 `!important` 声明
确保 Dock 栏样式不被网页 CSS 覆盖，关键属性添加 `!important`：

```css
.silkroad-dock {
    position: fixed !important;
    bottom: 20px !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    background-color: rgba(40, 44, 52, 0.95) !important;
    color: white !important;
    padding: 8px 16px !important;
    /* ... 其他属性 */
}
```

### 2. 减小尺寸使其更紧凑

| 属性 | 原值 | 新值 |
|------|------|------|
| `.silkroad-dock` padding | `12px 20px` | `8px 16px` |
| `.silkroad-dock-button` 尺寸 | `40px` | `36px` |
| `.silkroad-dock-theme` 尺寸 | `40px` | `36px` |
| `.silkroad-dock-clear` 尺寸 | `40px` | `36px` |
| `.silkroad-dock-handle` 尺寸 | `40px` | `36px` |
| `.silkroad-dock-buttons` gap | `15px` | `10px` |
| 各元素 margin-left | `15px` | `10px` |
| `.silkroad-dock-url` padding | `8px 15px` | `6px 12px` |
| `.silkroad-dock-url` margin-left | `20px` | `15px` |
| SVG 图标尺寸 | `20px` | `18px` |
| `.silkroad-dock-go` 尺寸 | `28px` | `24px` |
| `.silkroad-dock-go` SVG | `16px` | `14px` |
| 折叠状态尺寸 | `60px` | `50px` |

## 实施步骤

1. **为 `.silkroad-dock` 主容器添加 `!important`**
   - position, bottom, left, transform
   - background-color, color, padding
   - display, z-index, border-radius

2. **为按钮样式添加 `!important`**
   - `.silkroad-dock-button`
   - `.silkroad-dock-theme`
   - `.silkroad-dock-clear`
   - `.silkroad-dock-handle`

3. **为 URL 输入区域添加 `!important`**
   - `.silkroad-dock-url`
   - `.silkroad-dock-url-input`
   - `.silkroad-dock-go`

4. **为 SVG 图标添加 `!important`**
   - width, height, fill

5. **减小各元素尺寸和间距**

6. **为折叠状态添加 `!important`**

## 预期效果

- Dock 栏样式不再被网页 CSS 影响，保持一致性
- 整体尺寸减小约 15-20%，更加紧凑美观
- 所有功能正常运作
