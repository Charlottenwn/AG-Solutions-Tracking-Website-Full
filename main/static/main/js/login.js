function initLoginForm() {
    const form = document.getElementById('loginForm');
    if (!form) return;

    form.addEventListener('submit', function (event) {
        event.preventDefault();

        if (form.checkValidity()) {
            form.reportValidity();
            return;
        }

        window.location.href = '/main_offer_page/';
    });
}

initLoginForm();