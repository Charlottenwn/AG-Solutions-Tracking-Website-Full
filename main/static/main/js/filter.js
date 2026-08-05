function initFilters() {
    const searchInput = document.getElementById('searchInput');
    const filterSelect = document.getElementById('filterSelect');
    const orderList = document.getElementById('orderList');

    if (!searchInput || !filterSelect || !orderList) return;

    let originalCards = Array.from(orderList.querySelectorAll('.order-card'));
    let cards = [...originalCards];

    function applyFilters() {
        const term = searchInput.value.trim().toLowerCase();
        const filterValue = filterSelect.value;

        // Handle sort-only options separately from show/hide filters
        if (filterValue === 'date-newest' || filterValue === 'date-oldest' ||
            filterValue === 'production-end-newest' || filterValue === 'production-end-oldest') {
            const sorted = [...originalCards].sort((a, b) => {
                let valueA;
                let valueB;

                if (
                    filterValue === "production-end-newest" ||
                    filterValue === "production-end-oldest"
                ) {
                    valueA = a.dataset.productionEndDate;
                    valueB = b.dataset.productionEndDate;
                } else {
                    valueA = a.dataset.contractDate;
                    valueB = b.dataset.contractDate;
                }

                const timeA = valueA ? new Date(valueA).getTime() : -Infinity;
                const timeB = valueB ? new Date(valueB).getTime() : -Infinity;

                if (
                    filterValue === "date-newest" ||
                    filterValue === "production-end-newest"
                ) {
                    return timeB - timeA;
                }

                return timeA - timeB;
            });
            sorted.forEach(card => orderList.appendChild(card));

            cards = sorted;

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