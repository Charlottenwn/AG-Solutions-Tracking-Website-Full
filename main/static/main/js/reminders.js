function initReminderForms() {
    document.querySelectorAll('.mark-sent-form').forEach(form => {
        let bypassIntercept = false;

        form.addEventListener('submit', event => {
            if (bypassIntercept) return;

            event.preventDefault();
            const kindMatch = form.action.match(/mark_reminder_sent\/(\w+)\//);
            const kind = kindMatch ? kindMatch[1] : '';
            const label = kind === 'furniture' ? 'furniture' : 'package clarification';

            if (!confirm(`Mark ${label} reminder as sent?`)) return;

            const button = form.querySelector('button');
            button.disabled = true;

            fetch(form.action, {
                method: 'POST',
                headers: { 'X-Requested-With': 'fetch' },
                body: new FormData(form),
            })
                .then(res => res.json())
                .then(data => {
                    if (!data.ok) {
                        alert('Something went wrong — please try again.');
                        button.disabled = false;
                        return;
                    }
                    const badge = document.getElementById(form.dataset.target);
                    const fadeTargets = [badge, form].filter(Boolean);
                    fadeTargets.forEach(el => el.classList.add('opacity-0'));
                    setTimeout(() => fadeTargets.forEach(el => el.remove()), 300);
                })
                .catch(() => {
                    bypassIntercept = true;
                    form.submit();
                });
        });
    });
}

initReminderForms();