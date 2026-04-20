const grid = document.getElementById('explore-grid');
const countEl = document.getElementById('explore-count');
const searchInput = document.getElementById('explore-search');
const filterSelect = document.getElementById('explore-filter');
const btnRefresh = document.getElementById('btn-explore-refresh');
const chipRow = document.getElementById('chip-row');
const btnCategoryChat = document.getElementById('btn-category-chat');

let allItems = [];
let categories = [];
let selectedCategoryKey = null;

const DATE_SUFFIX = /_(\d{4}-\d{2}-\d{2})$/;

function prettyTitle(filename) {
    const base = filename.replace(/\.txt$/, '');
    const m = base.match(DATE_SUFFIX);
    const withoutDate = m ? base.slice(0, m.index) : base;
    return withoutDate.replace(/_/g, ' ').trim();
}

function extractDate(filename) {
    const base = filename.replace(/\.txt$/, '');
    const m = base.match(DATE_SUFFIX);
    return m ? m[1] : null;
}

function encodePath(p) {
    return p.split('/').map(encodeURIComponent).join('/');
}

function currentCategoryFromURL() {
    const params = new URLSearchParams(window.location.search);
    const k = params.get('category');
    return k && k.trim() ? k.trim() : null;
}

function updateURL(key) {
    const url = new URL(window.location);
    if (key) {
        url.searchParams.set('category', key);
    } else {
        url.searchParams.delete('category');
    }
    window.history.pushState({}, '', url);
}

function updateCategoryChatButton() {
    if (!btnCategoryChat) return;
    if (selectedCategoryKey) {
        btnCategoryChat.hidden = false;
        btnCategoryChat.href = '/chat/category/' + encodeURIComponent(selectedCategoryKey);
    } else {
        btnCategoryChat.hidden = true;
        btnCategoryChat.removeAttribute('href');
    }
}

function renderChips() {
    updateCategoryChatButton();
    chipRow.innerHTML = '';
    const chips = [{ key: null, display: 'All', count: allItems.length }]
        .concat(categories.map(c => ({
            key: c.key,
            display: c.display,
            count: c.count,
        })));

    for (const c of chips) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'chip';
        chip.dataset.key = c.key == null ? '' : c.key;
        chip.textContent = `${c.display} (${c.count})`;
        if ((c.key || null) === selectedCategoryKey) {
            chip.classList.add('active');
        }
        chip.addEventListener('click', () => {
            selectedCategoryKey = c.key || null;
            updateURL(selectedCategoryKey);
            renderChips();
            renderGrid();
        });
        chipRow.appendChild(chip);
    }
}

function renderGrid() {
    const query = searchInput.value.trim().toLowerCase();
    const filter = filterSelect.value;

    const items = allItems.filter(t => {
        if (selectedCategoryKey && t.category_key !== selectedCategoryKey) return false;
        if (filter === 'summarized' && !t.has_summary) return false;
        if (filter === 'unsummarized' && t.has_summary) return false;
        if (query) {
            const hay = (t.filename + ' ' + (t.subfolder || '')).toLowerCase();
            if (!hay.includes(query)) return false;
        }
        return true;
    });

    countEl.textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
    grid.innerHTML = '';

    if (items.length === 0) {
        grid.innerHTML = '<p class="empty-hint">No items match.</p>';
        return;
    }

    for (const t of items) {
        const card = document.createElement('a');
        card.className = 'explore-card';
        card.href = '/chat/' + encodePath(t.path);

        const title = document.createElement('h3');
        title.className = 'card-title';
        title.textContent = prettyTitle(t.filename);
        card.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'card-meta';

        if (t.subfolder) {
            const tag = document.createElement('span');
            tag.className = 'card-tag';
            tag.textContent = t.subfolder.replace(/_/g, ' ');
            meta.appendChild(tag);
        }

        const date = extractDate(t.filename);
        if (date) {
            const dateEl = document.createElement('span');
            dateEl.className = 'card-date';
            dateEl.textContent = date;
            meta.appendChild(dateEl);
        }

        if (t.has_summary) {
            const badge = document.createElement('span');
            badge.className = 'summary-badge';
            badge.textContent = 'summarized';
            meta.appendChild(badge);
        }

        card.appendChild(meta);
        grid.appendChild(card);
    }
}

async function loadAll() {
    grid.innerHTML = '<p class="empty-hint">Loading...</p>';
    try {
        const [itemsRes, catsRes] = await Promise.all([
            fetch('/api/transcripts'),
            fetch('/api/categories'),
        ]);
        const itemsData = await itemsRes.json();
        const catsData = await catsRes.json();
        allItems = itemsData.transcripts || [];
        categories = catsData.categories || [];
        selectedCategoryKey = currentCategoryFromURL();
        renderChips();
        renderGrid();
    } catch (err) {
        grid.innerHTML = '<p class="empty-hint">Failed to load items.</p>';
    }
}

searchInput.addEventListener('input', renderGrid);
filterSelect.addEventListener('change', renderGrid);
btnRefresh.addEventListener('click', loadAll);
window.addEventListener('popstate', () => {
    selectedCategoryKey = currentCategoryFromURL();
    renderChips();
    renderGrid();
});

loadAll();
