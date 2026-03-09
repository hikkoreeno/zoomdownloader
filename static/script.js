const downloadBtn = document.getElementById('download-btn');
const urlInput = document.getElementById('url-input');
const statusContainer = document.getElementById('status-container');
const statusMessage = document.getElementById('status-message');
const statusPercent = document.getElementById('status-percent');
const progressBarFill = document.getElementById('progress-bar-fill');
const statusDetail = document.getElementById('status-detail');

let activeJobId = null;
let pollInterval = null;

downloadBtn.addEventListener('click', async () => {
    const url = urlInput.value.trim();
    if (!url) {
        alert('Please enter a Zoom URL');
        return;
    }

    // Reset UI
    downloadBtn.disabled = true;
    statusContainer.classList.remove('h-hidden');
    statusMessage.textContent = 'Starting Download...';
    statusMessage.classList.add('loading');
    statusPercent.textContent = '0%';
    progressBarFill.style.width = '0%';
    statusDetail.textContent = 'Contacting server...';

    try {
        const response = await fetch('/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await response.json();
        if (data.status === 'ok') {
            activeJobId = data.job_id;
            startPolling();
        } else {
            throw new Error(data.message || 'Failed to start download');
        }
    } catch (err) {
        handleError(err.message);
    }
});

function startPolling() {
    pollInterval = setInterval(async () => {
        if (!activeJobId) return;

        try {
            const response = await fetch(`/status/${activeJobId}`);
            const data = await response.json();

            updateUI(data);

            if (data.status === 'completed' || data.status === 'error') {
                stopPolling();
                downloadBtn.disabled = false;
                statusMessage.classList.remove('loading');
            }
        } catch (err) {
            console.error('Polling error:', err);
        }
    }, 1000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

function updateUI(data) {
    statusMessage.textContent = data.status === 'running' ? 'Processing...' : 
                               data.status === 'completed' ? 'Success!' : 'Error';
    
    if (data.status === 'error') {
        statusMessage.style.color = '#ef4444';
    } else if (data.status === 'completed') {
        statusMessage.style.color = '#10b981';
    } else {
        statusMessage.style.color = '';
    }

    statusPercent.textContent = `${data.progress}%`;
    progressBarFill.style.width = `${data.progress}%`;
    statusDetail.textContent = data.message;
}

function handleError(msg) {
    statusContainer.classList.remove('h-hidden');
    statusMessage.textContent = 'Error';
    statusMessage.style.color = '#ef4444';
    statusMessage.classList.remove('loading');
    statusDetail.textContent = msg;
    downloadBtn.disabled = false;
}
