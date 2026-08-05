function initFilters() {
    const searchInput = document.getElementById('searchInput');
    const filterSelect = document.getElementById('filterSelect');
    const orderList = document.getElementById('orderList');

    if (!searchInput || !filterSelect || !orderList) return;

    const cards = Array.from(orderList.querySelectorAll('.order-card'));

    function applyFilters() {
        const term = searchInput.value.trim().toLowerCase();
        const filterValue = filterSelect.value;

        // Handle sort-only options separately from show/hide filters
        if (filterValue === 'date-newest' || filterValue === 'date-oldest') {
            const sorted = [...cards].sort((a, b) => {
                const dateA = a.dataset.contractDate || '';
                const dateB = b.dataset.contractDate || '';
                if (!dateA && !dateB) return 0;
                if (!dateA) return 1;  // cards with no parseable date sink to the end
                if (!dateB) return -1;
                return filterValue === 'date-newest'
                    ? dateB.localeCompare(dateA)
                    : dateA.localeCompare(dateB);
            });
            sorted.forEach(card => orderList.appendChild(card));

            // Still apply search term on top of the new sort order
            cards.forEach(card => {
                const searchText = (card.dataset.search || '').toLowerCase();
                card.style.display = (term === '' || searchText.includes(term)) ? '' : 'none';
            });
            return;
        }

        cards.forEach(card => {
            const searchText = (card.dataset.search || '').toLowerCase();
            const statuses = (card.dataset.statuses || '').split(' ');

            const matchesSearch = term === '' || searchText.includes(term);

            let matchesFilter = true;
            if (filterValue !== 'all') {
                if (filterValue === 'paid') {
                    matchesFilter = statuses.some(s => s.endsWith('-paid'));
                } else if (filterValue === 'unpaid') {
                    matchesFilter = statuses.some(s => s.endsWith('-due') || s.endsWith('-overdue'));
                } else if (filterValue === 'overdue') {
                    matchesFilter = statuses.some(s => s.endsWith('-overdue'));
                } else if (filterValue === 'furniture-due') {
                    matchesFilter = statuses.some(s => s === 'furniture-due' || s === 'furniture-overdue');
                } else if (filterValue === 'package-due') {
                    matchesFilter = statuses.some(s => s === 'package-due' || s === 'package-overdue');
                } else {
                    // transport-pending / transport-confirmed / transport-overdue
                    matchesFilter = statuses.includes(filterValue);
                }
            }

            card.style.display = (matchesSearch && matchesFilter) ? '' : 'none';
        });
    }

    searchInput.addEventListener('input', applyFilters);
    filterSelect.addEventListener('change', applyFilters);
}

initFilters();