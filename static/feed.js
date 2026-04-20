const grid = document.getElementById('feed-grid');
const countEl = document.getElementById('feed-count');
const btnMarkRead = document.getElementById('btn-mark-read');

const STORAGE_KEY = 'tubedigest.feed.lastSeenMtime';

const DATE_SUFFIX = /_(\d{4}-\d{2}-\d{2})$/;

function prettyTitle(filename) {
    const base = filename.replace(/\.txt$/, '');
    const m = base.match(DATE_SUFFIX);
    const withoutDate = m ? base.slice(0, m.index) : base;
    return withoutDate.replace(/_/g, ' ').trim();
}

function encodePath(p) {
    return p.split('/').map(encodeURIComponent).join('/');
}

function getLastSeen() {
    const v = parseFloat(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(v) ? v : 0;
}

function setLastSeen(mtime) {
    localStorage.setItem(STORAGE_KEY, String(mtime));
}

function formatRelativeDate(epochSeconds) {
    const then = new Date(epochSeconds * 1000);
    const now = new Date();
    const diffMs = now - then;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    const sameDay = then.toDateString() === now.toDateString();
    if (sameDay) return 'Today';

    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (then.toDateString() === yesterday.toDateString()) return 'Yesterday';

    if (diffDays < 7) return `${diffDays} days ago`;
    return then.toISOString().slice(0, 10);
}

let allItems = [];

function renderGrid() {
    const lastSeen = getLastSeen();
    const newest = allItems.reduce((m, t) => Math.max(m, t.mtime || 0), 0);
    const unreadCount = allItems.filter(t => (t.mtime || 0) > lastSeen).length;

    countEl.innerHTML = '';
    const total = document.createElement('span');
    total.textContent = `${allItems.length} item${allItems.length === 1 ? '' : 's'}`;
    countEl.appendChild(total);

    if (unreadCount > 0) {
        const sep = document.createElement('span');
        sep.textContent = ' · ';
        sep.style.color = '#666';
        countEl.appendChild(sep);
        const badge = document.createElement('span');
        badge.className = 'feed-unread-count';
        badge.textContent = `${unreadCount} new`;
        countEl.appendChild(badge);
    }

    btnMarkRead.disabled = unreadCount === 0;
    btnMarkRead.dataset.targetMtime = String(newest);

    grid.innerHTML = '';
    if (allItems.length === 0) {
        grid.innerHTML = '<p class="empty-hint">No transcripts yet.</p>';
        return;
    }

    for (const t of allItems) {
        const isNew = (t.mtime || 0) > lastSeen;

        const card = document.createElement('a');
        card.className = 'explore-card feed-card';
        if (isNew) card.classList.add('feed-card-new');
        card.href = '/chat/' + encodePath(t.path);

        if (isNew) {
            const badge = document.createElement('span');
            badge.className = 'feed-new-badge';
            badge.textContent = 'NEW';
            card.appendChild(badge);
        }

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

        if (t.mtime) {
            const dateEl = document.createElement('span');
            dateEl.className = 'card-date';
            dateEl.textContent = formatRelativeDate(t.mtime);
            meta.appendChild(dateEl);
        }

        if (t.has_summary) {
            const sb = document.createElement('span');
            sb.className = 'summary-badge';
            sb.textContent = 'summarized';
            meta.appendChild(sb);
        }

        card.appendChild(meta);
        grid.appendChild(card);
    }
}

async function load() {
    grid.innerHTML = '<p class="empty-hint">Loading...</p>';
    try {
        const res = await fetch('/api/transcripts');
        const data = await res.json();
        allItems = data.transcripts || [];
        renderGrid();
    } catch (err) {
        grid.innerHTML = '<p class="empty-hint">Failed to load feed.</p>';
    }
}

btnMarkRead.addEventListener('click', () => {
    const target = parseFloat(btnMarkRead.dataset.targetMtime || '0');
    if (target > 0) setLastSeen(target);
    renderGrid();
});

load();
