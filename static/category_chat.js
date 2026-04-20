const catKey = window.CATEGORY_KEY;
const catDisplay = window.CATEGORY_DISPLAY;

const subtitleEl = document.getElementById('cat-subtitle');
const itemsList = document.getElementById('cat-items-list');
const messagesEl = document.getElementById('chat-messages');
const form = document.getElementById('chat-form');
const input = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const statusEl = document.getElementById('chat-status');

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

function renderMarkdown(text) {
    if (window.marked) return window.marked.parse(text || '');
    const d = document.createElement('div');
    d.textContent = text || '';
    return `<pre>${d.innerHTML}</pre>`;
}

function appendMessage(role, content, provider, retrieved) {
    const hint = messagesEl.querySelector('.empty-hint');
    if (hint) hint.remove();

    const wrapper = document.createElement('div');
    wrapper.className = `chat-msg chat-msg-${role}`;

    const label = document.createElement('div');
    label.className = 'chat-msg-label';
    label.textContent = role === 'user' ? 'You' : (provider ? `AI (${provider})` : 'AI');

    const body = document.createElement('div');
    body.className = 'chat-msg-body';
    if (role === 'assistant') {
        body.innerHTML = renderMarkdown(content);
    } else {
        body.textContent = content;
    }

    wrapper.appendChild(label);
    wrapper.appendChild(body);

    if (role === 'assistant' && Array.isArray(retrieved) && retrieved.length) {
        const srcs = document.createElement('div');
        srcs.className = 'chat-msg-sources';
        srcs.textContent = 'Pulled in full transcript for: ';
        retrieved.forEach((r, i) => {
            const a = document.createElement('a');
            a.href = '/chat/' + encodePath(r.path);
            a.textContent = prettyTitle(r.filename);
            srcs.appendChild(a);
            if (i < retrieved.length - 1) {
                srcs.appendChild(document.createTextNode(', '));
            }
        });
        wrapper.appendChild(srcs);
    }

    messagesEl.appendChild(wrapper);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderItems(items) {
    itemsList.innerHTML = '';
    if (!items.length) {
        itemsList.innerHTML = '<p class="empty-hint">No items.</p>';
        return;
    }
    for (const t of items) {
        const row = document.createElement('a');
        row.className = 'cat-item-row';
        row.href = '/chat/' + encodePath(t.path);
        row.title = t.path;
        const title = document.createElement('span');
        title.className = 'cat-item-title';
        title.textContent = prettyTitle(t.filename);
        row.appendChild(title);
        if (t.has_summary) {
            const badge = document.createElement('span');
            badge.className = 'summary-badge';
            badge.textContent = '✓';
            badge.title = 'summarized';
            row.appendChild(badge);
        }
        itemsList.appendChild(row);
    }
}

async function loadCategory() {
    try {
        const res = await fetch(`/api/category/${encodeURIComponent(catKey)}`);
        if (!res.ok) {
            statusEl.textContent = 'Category not found.';
            btnSend.disabled = true;
            return;
        }
        const data = await res.json();
        const summarizedText = data.summarized_count === data.count
            ? 'all summarized'
            : `${data.summarized_count} / ${data.count} summarized`;
        subtitleEl.textContent = `${data.count} items · ${summarizedText}`;

        renderItems(data.items || []);

        if (Array.isArray(data.history)) {
            for (const turn of data.history) {
                appendMessage(turn.role, turn.content, turn.provider, turn.retrieved);
            }
        }
    } catch (err) {
        statusEl.textContent = 'Failed to load category: ' + err.message;
        btnSend.disabled = true;
    }
}

async function sendMessage() {
    const message = input.value.trim();
    if (!message) return;

    appendMessage('user', message);
    input.value = '';
    btnSend.disabled = true;
    input.disabled = true;
    statusEl.textContent = 'Thinking...';

    try {
        const res = await fetch('/api/category_chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: catKey, message }),
        });
        const data = await res.json();
        if (!res.ok) {
            statusEl.textContent = data.error || `Error: ${res.status}`;
            return;
        }
        appendMessage('assistant', data.reply, data.provider, data.retrieved);
        statusEl.textContent = '';
    } catch (err) {
        statusEl.textContent = 'Network error: ' + err.message;
    } finally {
        btnSend.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

form.addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage();
});

input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

loadCategory();
