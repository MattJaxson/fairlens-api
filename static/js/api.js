/* Project Libra — API helpers + page view tracking */

const API = window.location.origin;

// ── Page View Tracking ────────────────────────────
function trackPageView() {
    fetch(API + '/api/v1/track/pageview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: window.location.pathname }),
    }).catch(() => {}); // silent fail
}

// ── Public Stats ──────────────────────────────────
async function fetchPublicStats() {
    try {
        const res = await fetch(API + '/api/v1/stats/public');
        if (!res.ok) return null;
        return await res.json();
    } catch { return null; }
}

// ── Demo Analyze ──────────────────────────────────
async function demoAnalyze(text, categories) {
    const res = await fetch(API + '/api/v1/demo/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, categories }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Analysis failed' }));
        throw new Error(err.detail || `Error ${res.status}`);
    }
    return await res.json();
}

// ── Register ──────────────────────────────────────
async function registerUser(email) {
    const res = await fetch(API + '/api/v1/keys/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
        throw new Error(err.detail || `Error ${res.status}`);
    }
    return await res.json();
}

// ── Update Stats Strip ────────────────────────────
async function updateStatsStrip() {
    const stats = await fetchPublicStats();
    if (!stats) return;
    const el = (id) => document.getElementById(id);
    if (el('stat-analyses')) el('stat-analyses').textContent = stats.total_analyses.toLocaleString();
    if (el('stat-users')) el('stat-users').textContent = stats.total_users.toLocaleString();
    if (el('stat-communities')) el('stat-communities').textContent = stats.total_communities.toLocaleString();
    if (el('stat-pageviews')) el('stat-pageviews').textContent = stats.total_pageviews.toLocaleString();
}

// ── Init ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    trackPageView();
    updateStatsStrip();
});
