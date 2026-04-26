/**
 * 图片缩放脚本 - SilkRoad Image Zoom
 * 
 * 功能：
 * 1. 点击图片放大查看
 * 2. 支持鼠标滚轮缩放
 * 3. 支持拖拽移动
 * 4. 按 ESC 或点击背景关闭
 * 
 * 作者: SilkRoad-Next Team
 * 版本: 2.0.0
 */

(function() {
    'use strict';
    
    // 避免重复初始化
    if (window.silkroadZoomInitialized) {
        return;
    }
    window.silkroadZoomInitialized = true;
    
    // 创建遮罩层
    function createOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'silkroad-zoom-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 999999;
            display: none;
            justify-content: center;
            align-items: center;
            cursor: zoom-out;
        `;
        
        const zoomedImage = document.createElement('img');
        zoomedImage.id = 'silkroad-zoomed-image';
        zoomedImage.style.cssText = `
            max-width: 90%;
            max-height: 90%;
            object-fit: contain;
            cursor: move;
            transition: transform 0.2s ease;
        `;
        
        // 关闭按钮
        const closeBtn = document.createElement('div');
        closeBtn.innerHTML = '&times;';
        closeBtn.style.cssText = `
            position: absolute;
            top: 20px;
            right: 20px;
            width: 40px;
            height: 40px;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            font-size: 30px;
            display: flex;
            justify-content: center;
            align-items: center;
            border-radius: 50%;
            cursor: pointer;
            transition: background 0.2s;
        `;
        closeBtn.addEventListener('mouseenter', function() {
            this.style.background = 'rgba(255, 255, 255, 0.3)';
        });
        closeBtn.addEventListener('mouseleave', function() {
            this.style.background = 'rgba(255, 255, 255, 0.2)';
        });
        
        // 缩放提示
        const hint = document.createElement('div');
        hint.textContent = 'Scroll to zoom, drag to move, ESC to close';
        hint.style.cssText = `
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            color: rgba(255, 255, 255, 0.6);
            font-size: 12px;
            font-family: Arial, sans-serif;
        `;
        
        overlay.appendChild(zoomedImage);
        overlay.appendChild(closeBtn);
        overlay.appendChild(hint);
        document.body.appendChild(overlay);
        
        return { overlay, zoomedImage, closeBtn };
    }
    
    // 初始化
    function initZoom() {
        const { overlay, zoomedImage, closeBtn } = createOverlay();
        
        let scale = 1;
        let translateX = 0;
        let translateY = 0;
        let isDragging = false;
        let startX, startY;
        
        // 更新图片变换
        function updateTransform() {
            zoomedImage.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
        }
        
        // 重置状态
        function resetState() {
            scale = 1;
            translateX = 0;
            translateY = 0;
            updateTransform();
        }
        
        // 显示图片
        function showImage(src) {
            zoomedImage.src = src;
            overlay.style.display = 'flex';
            resetState();
            document.body.style.overflow = 'hidden';
        }
        
        // 隐藏图片
        function hideImage() {
            overlay.style.display = 'none';
            document.body.style.overflow = '';
        }
        
        // 为所有图片添加点击事件
        function addImageListeners() {
            const images = document.querySelectorAll('img:not([data-silkroad-zoom])');
            
            images.forEach(img => {
                img.setAttribute('data-silkroad-zoom', 'true');
                img.style.cursor = 'zoom-in';
                
                img.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showImage(this.src);
                });
            });
        }
        
        // 初始添加监听器
        addImageListeners();
        
        // 监听 DOM 变化，为新添加的图片添加监听器
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.tagName === 'IMG' && !node.hasAttribute('data-silkroad-zoom')) {
                            node.setAttribute('data-silkroad-zoom', 'true');
                            node.style.cursor = 'zoom-in';
                            node.addEventListener('click', function(e) {
                                e.preventDefault();
                                e.stopPropagation();
                                showImage(this.src);
                            });
                        }
                        
                        // 检查子节点
                        if (node.querySelectorAll) {
                            const imgs = node.querySelectorAll('img:not([data-silkroad-zoom])');
                            imgs.forEach(img => {
                                img.setAttribute('data-silkroad-zoom', 'true');
                                img.style.cursor = 'zoom-in';
                                img.addEventListener('click', function(e) {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    showImage(this.src);
                                });
                            });
                        }
                    });
                }
            });
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        
        // 关闭按钮点击
        closeBtn.addEventListener('click', hideImage);
        
        // 点击遮罩层关闭
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                hideImage();
            }
        });
        
        // ESC 键关闭
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && overlay.style.display === 'flex') {
                hideImage();
            }
        });
        
        // 鼠标滚轮缩放
        overlay.addEventListener('wheel', function(e) {
            if (overlay.style.display !== 'flex') return;
            
            e.preventDefault();
            
            const delta = e.deltaY > 0 ? -0.1 : 0.1;
            scale = Math.max(0.5, Math.min(5, scale + delta));
            updateTransform();
        });
        
        // 拖拽移动
        zoomedImage.addEventListener('mousedown', function(e) {
            e.preventDefault();
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
            zoomedImage.style.cursor = 'grabbing';
        });
        
        document.addEventListener('mousemove', function(e) {
            if (!isDragging) return;
            
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            updateTransform();
        });
        
        document.addEventListener('mouseup', function() {
            isDragging = false;
            zoomedImage.style.cursor = 'move';
        });
    }
    
    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initZoom);
    } else {
        initZoom();
    }
})();
