/**
 * 进度条脚本 - SilkRoad Progress Bar
 * 
 * 功能：
 * 1. 在页面顶部显示加载进度条
 * 2. 模拟页面加载进度
 * 3. 加载完成后自动隐藏
 * 
 * 作者: SilkRoad-Next Team
 * 版本: 2.0.0
 */

(function() {
    'use strict';
    
    // 避免重复创建
    if (document.getElementById('silkroad-progress')) {
        return;
    }
    
    // 创建进度条
    function createProgressBar() {
        // 创建进度条容器
        const progressContainer = document.createElement('div');
        progressContainer.id = 'silkroad-progress-container';
        progressContainer.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 3px;
            background: transparent;
            z-index: 999999;
            transition: opacity 0.3s ease;
        `;
        
        // 创建进度条
        const progressBar = document.createElement('div');
        progressBar.id = 'silkroad-progress';
        progressBar.style.cssText = `
            width: 0%;
            height: 100%;
            background: linear-gradient(to right, #2196F3, #21CBF3, #2196F3);
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite linear;
            transition: width 0.3s ease;
        `;
        
        // 添加动画样式
        const style = document.createElement('style');
        style.textContent = `
            @keyframes shimmer {
                0% { background-position: 200% 0; }
                100% { background-position: -200% 0; }
            }
        `;
        document.head.appendChild(style);
        
        progressContainer.appendChild(progressBar);
        document.head.appendChild(progressContainer);
        
        // 模拟加载进度
        let progress = 0;
        let isComplete = false;
        
        const interval = setInterval(() => {
            if (isComplete) {
                clearInterval(interval);
                return;
            }
            
            // 使用非线性进度
            const increment = Math.random() * 15 * (1 - progress / 100);
            progress += increment;
            
            if (progress >= 100) {
                progress = 100;
                isComplete = true;
                clearInterval(interval);
                
                // 加载完成，短暂停留后隐藏进度条
                setTimeout(() => {
                    progressContainer.style.opacity = '0';
                    setTimeout(() => {
                        progressContainer.remove();
                    }, 300);
                }, 500);
            }
            
            progressBar.style.width = progress + '%';
        }, 150);
        
        // 页面加载完成时快速完成进度
        window.addEventListener('load', function() {
            if (!isComplete) {
                progress = 90;
                progressBar.style.width = progress + '%';
                
                setTimeout(() => {
                    progress = 100;
                    progressBar.style.width = '100%';
                    isComplete = true;
                    
                    setTimeout(() => {
                        progressContainer.style.opacity = '0';
                        setTimeout(() => {
                            progressContainer.remove();
                        }, 300);
                    }, 500);
                }, 200);
            }
        });
    }
    
    // 页面加载时创建进度条
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createProgressBar);
    } else {
        createProgressBar();
    }
})();
