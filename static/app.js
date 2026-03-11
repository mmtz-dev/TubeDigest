const urlsInput = document.getElementById('urls');
const timestampsCheckbox = document.getElementById('timestamps');
const btnStart = document.getElementById('btn-start');
const btnFolder = document.getElementById('btn-folder');
const progressSection = document.getElementById('progress-section');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const logPanel = document.getElementById('log-panel');

async function loadAppInfo() {
    try {
        const res = await fetch('/api/info');
        const info = await res.json();
        log(`Transcriptions directory: ${info.transcriptions_dir}`);
        log(`Summaries directory: ${info.summaries_dir}`);
        log(`Today's YT API usage: ${info.yt_api_count} / ${info.yt_api_daily_limit}`);
    } catch (err) {
        log('Could not load app info.', 'error');
    }
}

loadAppInfo();

function log(message, type = 'status') {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    logPanel.appendChild(entry);
    logPanel.scrollTop = logPanel.scrollHeight;
}

function clearLog() {
    logPanel.innerHTML = '';
}

function setProgress(current, total) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    progressBar.style.width = pct + '%';
    progressText.textContent = `${current} / ${total} (${pct}%)`;
}

btnStart.addEventListener('click', async () => {
    const urls = urlsInput.value.trim();
    if (!urls) return;

    clearLog();
    btnStart.disabled = true;
    progressSection.hidden = false;
    setProgress(0, 0);
    log('Starting job...');

    try {
        const res = await fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                urls: urls,
                include_timestamps: timestampsCheckbox.checked,
            }),
        });

        const data = await res.json();
        if (!res.ok) {
            log(data.error || 'Failed to start job', 'error');
            btnStart.disabled = false;
            return;
        }

        listenToProgress(data.job_id);
    } catch (err) {
        log('Network error: ' + err.message, 'error');
        btnStart.disabled = false;
    }
});

function listenToProgress(jobId) {
    const source = new EventSource(`/api/progress/${jobId}`);
    let total = 0;

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        switch (msg.type) {
            case 'total':
                total = msg.count;
                setProgress(0, total);
                log(`Found ${total} video(s) to process.`);
                break;

            case 'status':
                log(msg.message);
                break;

            case 'progress':
                setProgress(msg.current, msg.total);
                break;

            case 'success':
                if (msg.skipped) {
                    log(`Skipped (already processed): ${msg.title}`, 'status');
                } else {
                    log(`Saved: ${msg.title}`, 'success');
                }
                break;

            case 'warning':
                log(msg.message, 'warning');
                break;

            case 'error':
                log(`Error${msg.video_id ? ` (${msg.video_id})` : ''}: ${msg.message}`, 'error');
                break;

            case 'summary':
                log(`Done — ${msg.succeeded} succeeded, ${msg.failed} failed out of ${msg.total} total.`, 'summary');
                setProgress(msg.total, msg.total);
                break;

            case 'done':
                source.close();
                btnStart.disabled = false;
                break;
        }
    };

    source.onerror = () => {
        source.close();
        log('Connection lost.', 'error');
        btnStart.disabled = false;
    };
}

btnFolder.addEventListener('click', async () => {
    try {
        const res = await fetch('/api/open-folder', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            if (data.path) {
                log(`Transcriptions folder: ${data.path}`, 'status');
            } else {
                log(data.error || 'Could not open folder', 'error');
            }
        }
    } catch (err) {
        log('Could not open folder: ' + err.message, 'error');
    }
});

/* ── Summarization Section ── */
const btnRefresh = document.getElementById('btn-refresh');
const btnCheckAll = document.getElementById('btn-check-all');
const btnSummarize = document.getElementById('btn-summarize');
const btnSummariesFolder = document.getElementById('btn-summaries-folder');
const transcriptList = document.getElementById('transcript-list');
const summaryProgressSection = document.getElementById('summary-progress-section');
const summaryProgressBar = document.getElementById('summary-progress-bar');
const summaryProgressText = document.getElementById('summary-progress-text');
const summaryLogPanel = document.getElementById('summary-log-panel');

let allCheckboxes = [];

function summaryLog(message, type = 'status') {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    summaryLogPanel.appendChild(entry);
    summaryLogPanel.scrollTop = summaryLogPanel.scrollHeight;
}

function clearSummaryLog() {
    summaryLogPanel.innerHTML = '';
}

function setSummaryProgress(current, total) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    summaryProgressBar.style.width = pct + '%';
    summaryProgressText.textContent = `${current} / ${total} (${pct}%)`;
}

async function loadTranscripts() {
    try {
        const res = await fetch('/api/transcripts');
        const data = await res.json();
        renderTranscriptList(data.transcripts || []);
    } catch (err) {
        transcriptList.innerHTML = '<p class="empty-hint">Failed to load transcripts.</p>';
    }
}

function renderTranscriptList(transcripts) {
    transcriptList.innerHTML = '';
    allCheckboxes = [];

    if (transcripts.length === 0) {
        transcriptList.innerHTML = '<p class="empty-hint">No transcripts found. Fetch some first!</p>';
        return;
    }

    // Group by subfolder
    const groups = {};
    for (const t of transcripts) {
        const key = t.subfolder || '';
        if (!groups[key]) groups[key] = [];
        groups[key].push(t);
    }

    // Render root-level items first, then subfolders
    const keys = Object.keys(groups).sort((a, b) => {
        if (a === '' && b !== '') return -1;
        if (a !== '' && b === '') return 1;
        return a.localeCompare(b);
    });

    for (const key of keys) {
        if (key) {
            const header = document.createElement('div');
            header.className = 'transcript-group-header';
            header.textContent = key;
            transcriptList.appendChild(header);
        }

        for (const t of groups[key]) {
            const item = document.createElement('label');
            item.className = 'transcript-item';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = t.path;
            allCheckboxes.push(cb);

            const name = document.createElement('span');
            name.className = 'name';
            name.textContent = t.filename;
            name.title = t.path;

            item.appendChild(cb);
            item.appendChild(name);

            if (t.has_summary) {
                const badge = document.createElement('span');
                badge.className = 'summary-badge';
                badge.textContent = 'summarized';
                item.appendChild(badge);
            }

            transcriptList.appendChild(item);
        }
    }
}

btnRefresh.addEventListener('click', loadTranscripts);

btnCheckAll.addEventListener('click', () => {
    const allChecked = allCheckboxes.length > 0 && allCheckboxes.every(cb => cb.checked);
    allCheckboxes.forEach(cb => cb.checked = !allChecked);
});

btnSummarize.addEventListener('click', async () => {
    const selected = allCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
    if (selected.length === 0) {
        summaryLog('No transcripts selected.', 'warning');
        return;
    }

    clearSummaryLog();
    btnSummarize.disabled = true;
    summaryProgressSection.hidden = false;
    setSummaryProgress(0, 0);
    summaryLog(`Starting summarization of ${selected.length} transcript(s)...`);

    try {
        const res = await fetch('/api/summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths: selected }),
        });

        const data = await res.json();
        if (!res.ok) {
            summaryLog(data.error || 'Failed to start summarization', 'error');
            btnSummarize.disabled = false;
            return;
        }

        listenToSummaryProgress(data.job_id);
    } catch (err) {
        summaryLog('Network error: ' + err.message, 'error');
        btnSummarize.disabled = false;
    }
});

function listenToSummaryProgress(jobId) {
    const source = new EventSource(`/api/progress/${jobId}`);
    let total = 0;

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        switch (msg.type) {
            case 'total':
                total = msg.count;
                setSummaryProgress(0, total);
                summaryLog(`Processing ${total} transcript(s)...`);
                break;

            case 'status':
                summaryLog(msg.message);
                break;

            case 'progress':
                setSummaryProgress(msg.current, msg.total);
                break;

            case 'success':
                if (msg.skipped) {
                    summaryLog(`Skipped (already summarized): ${msg.title}`, 'status');
                } else {
                    summaryLog(`Summarized: ${msg.title}`, 'success');
                }
                break;

            case 'warning':
                summaryLog(msg.message, 'warning');
                break;

            case 'error':
                summaryLog(`Error: ${msg.message}`, 'error');
                break;

            case 'summary':
                summaryLog(`Done — ${msg.succeeded} succeeded, ${msg.failed} failed out of ${msg.total} total.`, 'summary');
                setSummaryProgress(msg.total, msg.total);
                break;

            case 'done':
                source.close();
                btnSummarize.disabled = false;
                loadTranscripts();
                break;
        }
    };

    source.onerror = () => {
        source.close();
        summaryLog('Connection lost.', 'error');
        btnSummarize.disabled = false;
    };
}

btnSummariesFolder.addEventListener('click', async () => {
    try {
        const res = await fetch('/api/open-summaries-folder', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            if (data.path) {
                summaryLog(`Summaries folder: ${data.path}`, 'status');
            } else {
                summaryLog(data.error || 'Could not open folder', 'error');
            }
        }
    } catch (err) {
        summaryLog('Could not open folder: ' + err.message, 'error');
    }
});
