const urlsInput = document.getElementById('urls');
const timestampsCheckbox = document.getElementById('timestamps');
const btnStart = document.getElementById('btn-start');
const btnFolder = document.getElementById('btn-folder');
const progressSection = document.getElementById('progress-section');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const logPanel = document.getElementById('log-panel');

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
                log(`Saved: ${msg.title}`, 'success');
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
