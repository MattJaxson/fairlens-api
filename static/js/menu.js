/* Project Libra — Shared menu bar logic */

// Close dropdowns when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.menu-item')) {
        document.querySelectorAll('.dropdown').forEach(d => d.style.display = '');
    }
});
