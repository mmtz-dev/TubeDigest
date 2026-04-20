const grid = document.getElementById('categories-grid');
const countEl = document.getElementById('categories-count');

function render(categories) {
    grid.innerHTML = '';
    if (!categories.length) {
        grid.innerHTML = '<p class="empty-hint">No categories found yet.</p>';
        countEl.textContent = '0 categories';
        return;
    }

    countEl.textContent = `${categories.length} categor${categories.length === 1 ? 'y' : 'ies'}`;

    for (const cat of categories) {
        const wrap = document.createElement('div');
        wrap.className = 'category-card-wrap';

        const card = document.createElement('a');
        card.className = 'explore-card category-card';
        card.href = '/explore?category=' + encodeURIComponent(cat.key);

        const title = document.createElement('h3');
        title.className = 'card-title category-card-title';
        title.textContent = cat.display;
        card.appendChild(title);

        const count = document.createElement('div');
        count.className = 'category-card-count';
        count.textContent = `${cat.count} item${cat.count === 1 ? '' : 's'}`;
        card.appendChild(count);

        const meta = document.createElement('div');
        meta.className = 'card-meta';
        if (cat.summarized_count > 0) {
            const badge = document.createElement('span');
            badge.className = 'summary-badge';
            badge.textContent = `${cat.summarized_count} summarized`;
            meta.appendChild(badge);
        }
        card.appendChild(meta);

        if (cat.folders && cat.folders.length > 1) {
            const merged = document.createElement('div');
            merged.className = 'category-card-merged';
            merged.textContent = 'merged from: ' + cat.folders.join(', ');
            merged.title = merged.textContent;
            card.appendChild(merged);
        }

        const actions = document.createElement('div');
        actions.className = 'category-card-actions';

        const browseLink = document.createElement('a');
        browseLink.className = 'card-action';
        browseLink.href = '/explore?category=' + encodeURIComponent(cat.key);
        browseLink.textContent = 'Browse items';
        actions.appendChild(browseLink);

        const chatLink = document.createElement('a');
        chatLink.className = 'card-action card-action-primary';
        chatLink.href = '/chat/category/' + encodeURIComponent(cat.key);
        chatLink.textContent = 'Chat about category';
        actions.appendChild(chatLink);

        wrap.appendChild(card);
        wrap.appendChild(actions);
        grid.appendChild(wrap);
    }
}

async function load() {
    try {
        const res = await fetch('/api/categories');
        const data = await res.json();
        render(data.categories || []);
    } catch (err) {
        grid.innerHTML = '<p class="empty-hint">Failed to load categories.</p>';
    }
}

load();
