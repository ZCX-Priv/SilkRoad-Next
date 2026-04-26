/**
 * 浮动面板脚本 - SilkRoad Proxy Panel
 * 
 * 功能：
 * 1. 在页面右下角显示控制面板
 * 2. 显示代理状态信息
 * 3. 支持最小化/展开
 * 4. 支持拖拽移动
 * 
 * 作者: SilkRoad-Next Team
 * 版本: 2.0.0
 */

(function() {
    'use strict';
    
    // 避免重复创建
    if (document.getElementById('silkroad-dock')) {
        return;
    }
    
    // 创建浮动面板
    function createDock() {
        const dock = document.createElement('div');
        dock.id = 'silkroad-dock';
        dock.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 300px;
            background: rgba(0, 0, 0, 0.85);
            color: white;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            z-index: 999999;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            font-size: 13px;
            transition: all 0.3s ease;
        `;
        
        dock.innerHTML = `
            <div style="margin-bottom: 10px; font-weight: bold; font-size: 14px; display: flex; justify-content: space-between; align-items: center;">
                <span>SilkRoad Proxy Panel</span>
                <span style="font-size: 10px; color: #4CAF50;">v2.0</span>
            </div>
            <div style="margin-bottom: 8px; font-size: 12px;">
                <span style="color: #888;">Target: </span>
                <span id="silkroad-target" style="color: #2196F3;">${window.location.hostname}</span>
            </div>
            <div style="margin-bottom: 8px; font-size: 12px;">
                <span style="color: #888;">Status: </span>
                <span style="color: #4CAF50;">Connected</span>
            </div>
            <div style="margin-bottom: 8px; font-size: 12px;">
                <span style="color: #888;">Protocol: </span>
                <span style="color: #FF9800;">${window.location.protocol.replace(':', '')}</span>
            </div>
            <div style="margin-bottom: 10px; font-size: 12px;">
                <span style="color: #888;">Response Time: </span>
                <span id="silkroad-response-time" style="color: #9C27B0;">--</span>
            </div>
            <div style="display: flex; gap: 8px;">
                <button id="silkroad-toggle" style="
                    flex: 1;
                    background: #2196F3;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 12px;
                    transition: background 0.2s;
                ">Minimize</button>
                <button id="silkroad-close" style="
                    background: #f44336;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 12px;
                    transition: background 0.2s;
                ">Hide</button>
            </div>
        `;
        
        document.body.appendChild(dock);
        
        // 最小化功能
        const toggleBtn = document.getElementById('silkroad-toggle');
        let isMinimized = false;
        
        toggleBtn.addEventListener('click', function() {
            const content = dock.querySelectorAll('div:not(:first-child)');
            
            isMinimized = !isMinimized;
            
            content.forEach(div => {
                div.style.display = isMinimized ? 'none' : 'block';
            });
            
            toggleBtn.textContent = isMinimized ? 'Expand' : 'Minimize';
            dock.style.width = isMinimized ? '200px' : '300px';
        });
        
        // 关闭/隐藏功能
        const closeBtn = document.getElementById('silkroad-close');
        closeBtn.addEventListener('click', function() {
            dock.style.opacity = '0';
            dock.style.transform = 'translateY(20px)';
            setTimeout(() => {
                dock.style.display = 'none';
            }, 300);
        });
        
        // 拖拽功能
        let isDragging = false;
        let offsetX, offsetY;
        
        dock.addEventListener('mousedown', function(e) {
            if (e.target.tagName !== 'BUTTON') {
                isDragging = true;
                offsetX = e.clientX - dock.offsetLeft;
                offsetY = e.clientY - dock.offsetTop;
                dock.style.cursor = 'move';
            }
        });
        
        document.addEventListener('mousemove', function(e) {
            if (isDragging) {
                dock.style.left = (e.clientX - offsetX) + 'px';
                dock.style.top = (e.clientY - offsetY) + 'px';
                dock.style.right = 'auto';
                dock.style.bottom = 'auto';
            }
        });
        
        document.addEventListener('mouseup', function() {
            isDragging = false;
            dock.style.cursor = 'default';
        });
        
        // 按钮悬停效果
        const buttons = dock.querySelectorAll('button');
        buttons.forEach(btn => {
            btn.addEventListener('mouseenter', function() {
                this.style.opacity = '0.8';
            });
            btn.addEventListener('mouseleave', function() {
                this.style.opacity = '1';
            });
        });
        
        // 模拟响应时间更新
        function updateResponseTime() {
            const responseTimeEl = document.getElementById('silkroad-response-time');
            if (responseTimeEl) {
                const randomTime = Math.floor(Math.random() * 200 + 50);
                responseTimeEl.textContent = randomTime + 'ms';
            }
        }
        
        // 定期更新响应时间
        setInterval(updateResponseTime, 5000);
        updateResponseTime();
    }
    
    // 页面加载完成后创建面板
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createDock);
    } else {
        createDock();
    }
})();
