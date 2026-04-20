const relPath = window.CHAT_REL_PATH;

const titleEl = document.getElementById('chat-title');
const subfolderEl = document.getElementById('chat-subfolder');
const summaryBody = document.getElementById('summary-body');
const transcriptBody = document.getElementById('transcript-body');
const transcriptPanel = document.getElementById('transcript-panel');
const messagesEl = document.getElementById('chat-messages');
const form = document.getElementById('chat-form');
const input = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const statusEl = document.getElementById('chat-status');

function escapeHtml(s) {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function renderMarkdown(text) {
    if (window.marked) {
        return window.marked.parse(text || '');
    }
    return `<pre>${escapeHtml(text || '')}</pre>`;
}

function appendMessage(role, content, provider) {
    const hint = messagesEl.querySelector('.empty-hint');
    if (hint) hint.remove();

    const wrapper = document.createElement('div');
    wrapper.className = `chat-msg chat-msg-${role}`;

    const label = document.createElement('div');
    label.className = 'chat-msg-label';
    if (role === 'user') {
        label.textContent = 'You';
    } else {
        label.textContent = provider ? `AI (${provider})` : 'AI';
    }

    const body = document.createElement('div');
    body.className = 'chat-msg-body';
    if (role === 'assistant') {
        body.innerHTML = renderMarkdown(content);
    } else {
        body.textContent = content;
    }

    wrapper.appendChild(label);
    wrapper.appendChild(body);
    messagesEl.appendChild(wrapper);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadItem() {
    try {
        const res = await fetch(`/api/item/${encodeURI(relPath)}`);
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            titleEl.textContent = 'Not found';
            statusEl.textContent = data.error || `Error: ${res.status}`;
            btnSend.disabled = true;
            return;
        }
        const data = await res.json();

        titleEl.textContent = data.filename;
        subfolderEl.textContent = data.subfolder || '';

        if (data.summary) {
            summaryBody.innerHTML = renderMarkdown(data.summary);
        } else {
            summaryBody.innerHTML = '<p class="empty-hint">No summary yet for this item.</p>';
        }

        transcriptBody.textContent = data.transcript || '';

        if (Array.isArray(data.history)) {
            for (const turn of data.history) {
                appendMessage(turn.role, turn.content, turn.provider);
            }
        }
    } catch (err) {
        statusEl.textContent = 'Failed to load item: ' + err.message;
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
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: relPath, message }),
        });
        const data = await res.json();
        if (!res.ok) {
            statusEl.textContent = data.error || `Error: ${res.status}`;
            return;
        }
        appendMessage('assistant', data.reply, data.provider);
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

loadItem();
