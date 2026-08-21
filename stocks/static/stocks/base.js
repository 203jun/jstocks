// 클립보드 복사. 화면마다 따로 정의하고 있어서 여기로 올린다.
// HTTPS 가 아니면 navigator.clipboard 가 없어 textarea 로 되돌아간다.
function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); resolve(); }
        catch (err) { reject(err); }
        finally { document.body.removeChild(ta); }
    });
}

// 위 CSS 변수와 같은 값. 차트 라이브러리에는 문자열로 넘겨야 해서 한 번 더 적는다.
const INVESTOR_COLORS = {
    foreign: '#8b5cf6',
    institution: '#f59e0b',
    individual: '#14b8a6',
};

// ⓘ 아이콘은 어느 화면에서든 나중에 추가될 수 있으므로 위임으로 받는다.
(function () {
    const overlay = document.getElementById('helpOverlay');
    const close = () => overlay.classList.remove('show');
    function open(icon) {
        document.getElementById('helpTitle').textContent = icon.dataset.helpTitle || '';
        // 설명 본문은 코드가 쓴다(사용자 입력이 아니다). 그래서 서식을 허용해
        // 화면에 실제로 뜨는 색·배지를 설명 안에서 그대로 보여줄 수 있게 한다.
        document.getElementById('helpBody').innerHTML = icon.dataset.helpBody || '';
        overlay.classList.add('show');
    }
    // 캡처 단계에서 잡는다. 접기 헤더처럼 누를 수 있는 요소 안에 들어가도
    // 바깥 동작이 같이 일어나지 않게 하기 위해서다.
    document.addEventListener('click', e => {
        const icon = e.target.closest('.hlp');
        if (!icon) return;
        e.preventDefault();
        e.stopPropagation();
        open(icon);
    }, true);
    // span 이라 키보드 조작을 직접 붙여준다
    document.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const icon = e.target.closest && e.target.closest('.hlp');
        if (!icon) return;
        e.preventDefault();
        open(icon);
    });
    document.getElementById('helpClose').addEventListener('click', close);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && overlay.classList.contains('show')) close();
    });
})();
