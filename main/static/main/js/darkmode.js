function initDarkMode() {
    const toggle = document.getElementById('darkToggle');
    const moon = document.getElementById('moonIcon');
    const sun = document.getElementById('sunIcon');
    const html = document.documentElement;

    if (localStorage.getItem('darkMode') === 'true') {
        html.classList.add('dark');
        moon.classList.add('hidden');
        sun.classList.remove('hidden');
    }

    toggle.addEventListener('click', () => {
        html.classList.toggle('dark');
        const isDark = html.classList.contains('dark');
        localStorage.setItem('darkMode', isDark);
        moon.classList.toggle('hidden', isDark);
        sun.classList.toggle('hidden', !isDark);
    });
}

initDarkMode();