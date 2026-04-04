(function() {
    'use strict';
    
    function enableImageZoom() {
        const images = document.querySelectorAll('img');
        
        images.forEach(img => {
            img.style.cursor = 'zoom-in';
            
            img.addEventListener('click', function(e) {
                e.preventDefault();
                
                const overlay = document.createElement('div');
                overlay.style.cssText = `
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.9);
                    z-index: 999999;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: zoom-out;
                `;
                
                const zoomedImg = document.createElement('img');
                zoomedImg.src = img.src;
                zoomedImg.style.cssText = `
                    max-width: 90%;
                    max-height: 90%;
                    object-fit: contain;
                `;
                
                overlay.appendChild(zoomedImg);
                document.body.appendChild(overlay);
                
                overlay.addEventListener('click', function() {
                    overlay.remove();
                });
            });
        });
        
        console.log('SilkRoad: Enabled zoom for ' + images.length + ' images');
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', enableImageZoom);
    } else {
        enableImageZoom();
    }
})();
