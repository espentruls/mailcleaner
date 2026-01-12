// MailCleaner Frontend Application

// State
let state = {
    currentView: 'overview',
    currentCategory: null,
    currentEmail: null,
    emails: [],
    groups: [],
    stats: {},
    readFilter: 'all'
};

// DOM Elements Container
const elements = {};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Cache DOM elements
    elements.pageTitle = document.getElementById('page-title');
    elements.readFilter = document.getElementById('read-filter');
    elements.fetchBtn = document.getElementById('fetch-btn');
    elements.accentPicker = document.getElementById('accent-picker');
    elements.resetBtn = document.getElementById('reset-btn');
    elements.stopSyncBtn = document.getElementById('stop-sync-btn');
    elements.loadingOverlay = document.getElementById('loading-overlay');
    elements.loadingText = document.getElementById('loading-text');
    elements.toastContainer = document.getElementById('toast-container');
    elements.modal = document.getElementById('email-modal');

    // Setup App
    setupNavigation();
    setupEventListeners();
    loadStats();

    // Initialize Settings
    loadSettings();
    setupSettingsListeners();
});

// Navigation
function setupNavigation() {
    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            switchView(view);
        });
    });
}

function switchView(view) {
    // Update nav
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === view);
    });

    // Update views
    document.querySelectorAll('.view').forEach(v => {
        v.classList.toggle('active', v.id === `${view}-view`);
    });

    // Update title
    const titles = {
        overview: 'Overview',
        categories: 'Categories',
        senders: 'By Sender',
        uncertain: 'Review Uncertain',
        settings: 'Settings'
    };
    if (elements.pageTitle) {
        elements.pageTitle.textContent = titles[view] || 'Dashboard';
    }

    // Toggle Header Controls
    const headerActions = document.getElementById('header-actions');
    if (headerActions) {
        headerActions.style.display = view === 'settings' ? 'none' : 'flex';
    }

    state.currentView = view;

    // Load view-specific data
    switch (view) {
        case 'categories':
            loadCategories();
            break;
        case 'senders':
            loadSenderGroups();
            break;
        case 'uncertain':
            loadUncertainEmails();
            break;
    }
}

// Event Listeners
function setupEventListeners() {
    if (elements.fetchBtn) {
        elements.fetchBtn.addEventListener('click', fetchEmails);
    }
    if (elements.resetBtn) {
        elements.resetBtn.addEventListener('click', resetAccount);
    }

    if (elements.stopSyncBtn) {
        elements.stopSyncBtn.addEventListener('click', stopSync);
    }

    // Setup custom dropdown for filter
    setupCustomDropdown();


    const spamBtn = document.getElementById('delete-all-spam');
    if (spamBtn) spamBtn.addEventListener('click', () => deleteByCategory('spam'));

    const newsletterBtn = document.getElementById('delete-newsletters');
    if (newsletterBtn) newsletterBtn.addEventListener('click', () => deleteByCategory('newsletter'));

    const trainBtn = document.getElementById('train-model');
    if (trainBtn) trainBtn.addEventListener('click', trainModel);

    // Close modal on backdrop click
    if (elements.modal) {
        elements.modal.addEventListener('click', (e) => {
            if (e.target === elements.modal) {
                closeModal();
            }
        });
    }
}

// API Functions
async function api(endpoint, options = {}) {
    // Add cache buster for GET requests to prevent stale data
    if ((!options.method || options.method === 'GET') && endpoint.startsWith('/')) {
        const separator = endpoint.includes('?') ? '&' : '?';
        endpoint += `${separator}_t=${Date.now()}`;
    }

    const response = await fetch(`/api${endpoint}`, {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'API Error');
    }

    return response.json();
}

// Loading States
function showLoading(message, showProgress = false) {
    if (elements.loadingText) elements.loadingText.textContent = message;
    if (elements.loadingOverlay) elements.loadingOverlay.classList.add('active');

    // Toggle progress bar and stop button
    const progressContainer = document.getElementById('sync-progress-container');
    const stopBtn = document.getElementById('stop-sync-btn');
    const loadingIcon = document.getElementById('loading-icon');

    if (progressContainer) progressContainer.style.display = showProgress ? 'block' : 'none';
    if (stopBtn) stopBtn.style.display = showProgress ? 'block' : 'none';

    if (showProgress) {
        // Reset progress bar
        const progressBar = document.getElementById('sync-progress-bar');
        if (progressBar) progressBar.style.width = '0%';
        document.getElementById('sync-count').textContent = '0 / 0';
        document.getElementById('sync-percent').textContent = '0%';
    }
}

function hideLoading() {
    if (elements.loadingOverlay) elements.loadingOverlay.classList.remove('active');
}

// Toast Notifications
function showToast(message, type = 'info') {
    if (!elements.toastContainer) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<i class="ri-${type === 'success' ? 'check' : type === 'error' ? 'error-warning' : 'information'}-line"></i><span>${message}</span>`;

    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 4000);
}

// Fetch Emails
async function fetchEmails() {
    try {
        showLoading('Connecting to Gmail...');

        // 0. Refresh stats to ensure local count is up to date
        await loadStats();

        // 1. Get total count first
        const totalResult = await api('/fetch', {
            method: 'POST',
            body: JSON.stringify({ get_total: true })
        });

        const totalEmails = (totalResult && typeof totalResult.total === 'number') ? totalResult.total : 30000;
        const localCount = (state.stats && typeof state.stats.total_emails === 'number') ? state.stats.total_emails : 0;

        // Calculate remaining to sync (approximate)
        let remaining = Math.max(0, totalEmails - localCount);
        if (isNaN(remaining)) remaining = 500;

        // Ensure we request at least a batch to check for new emails even if counts match
        if (remaining < 500) remaining = 500;

        // 2. Start sync with dynamic total
        showLoading(`Syncing ${remaining.toLocaleString()} Emails...`, true);
        await api('/fetch', {
            method: 'POST',
            body: JSON.stringify({
                max_emails: remaining,
                read_filter: state.readFilter,
                fresh: false
            })
        });

        // 3. Poll for status
        return new Promise((resolve, reject) => {
            const pollInterval = setInterval(async () => {
                try {
                    const status = await api('/fetch/status');

                    if (status.status === 'fetching') {
                        const percent = Math.min(100, Math.round((status.current / status.total) * 100));
                        const progressBar = document.getElementById('sync-progress-bar');
                        if (progressBar) progressBar.style.width = `${percent}%`;
                        document.getElementById('sync-count').textContent = `${status.current.toLocaleString()} / ${status.total.toLocaleString()}`;
                        document.getElementById('sync-percent').textContent = `${percent}%`;
                    } else if (status.status === 'completed') {
                        clearInterval(pollInterval);
                        hideLoading();
                        showToast(`Sync completed! Fetched ${status.current.toLocaleString()} emails.`, 'success');
                        refreshData();
                        resolve();
                    } else if (status.status === 'stopped') {
                        clearInterval(pollInterval);
                        hideLoading();
                        showToast(`Sync stopped. ${status.current.toLocaleString()} emails fetched so far.`, 'info');
                        refreshData();
                        resolve();
                    } else if (status.status === 'error') {
                        clearInterval(pollInterval);
                        hideLoading();
                        showToast(`Sync error: ${status.error}`, 'error');
                        reject(new Error(status.error));
                    }
                } catch (error) {
                    clearInterval(pollInterval);
                    hideLoading();
                    reject(error);
                }
            }, 1000);
        });

    } catch (error) {
        showToast(error.message, 'error');
        hideLoading();
    }
}

// Stop Sync
async function stopSync() {
    try {
        // Update UI immediately to show we are stopping
        const loadingText = document.querySelector('.loading-content p');
        if (loadingText) loadingText.textContent = 'Stopping sync... finishing current batch...';

        await api('/fetch/stop', { method: 'POST' });
        showToast('Signal sent to stop sync...', 'info');
    } catch (error) {
        showToast('Failed to stop sync', 'error');
    }
}

// Refresh Data
async function refreshData() {
    console.log('[refreshData] Refreshing all data...');
    try {
        await loadStats();

        // Refresh based on current view
        if (state.currentView === 'overview') {
            loadCategories();
            loadSenderGroups();
        } else if (state.currentView === 'categories') {
            loadCategories();
        } else if (state.currentView === 'senders') {
            loadSenderGroups();
        } else if (state.currentView === 'uncertain') {
            loadUncertainEmails();
        }
    } catch (error) {
        console.error('AI check failed:', error);
    }
}

// AI Cleanup Logic
async function loadCleanupSuggestions() {
    const intro = document.getElementById('cleanup-intro');
    const loading = document.getElementById('cleanup-loading');
    const results = document.getElementById('cleanup-results');

    if (intro) intro.style.display = 'none';
    if (loading) loading.style.display = 'block';
    results.innerHTML = '';

    try {
        const data = await api('/suggestions/deletion', { method: 'POST' });

        if (loading) loading.style.display = 'none';

        if (!data.suggestions || data.suggestions.length === 0) {
            results.innerHTML = '<div class="empty-state"><i class="ri-check-double-line"></i><p>No junk found! Your inbox is clean.</p></div>';
            return;
        }

        // Fetch full email objects for these IDs to render cards
        // Ideally API should return objects, but I returned IDs. 
        // Wait, web_app.py returns IDs in 'suggestions' list.
        // I need to update web_app.py to return objects or fetch them here.
        // In Step 3250 I returned `delete_ids` (List[str]).
        // I should have returned the OBJECTS or mapped them.

        // Since I only have IDs, I can't render cards easily without refetching.
        // It's better if the API returns the email objects or summaries.
        // I'll assume for now I show count, or I iterate state?
        // But state might not have them.

        // Render suggestions
        if (typeof renderEmailList === 'function') {
            renderEmailList(data.suggestions, 'cleanup-results', true);
        } else {
            console.error('renderEmailList not found');
            results.innerHTML = data.suggestions.map(e => `<div>${e.subject}</div>`).join('');
        }

    } catch (error) {
        if (loading) loading.style.display = 'none';
        showToast(error.message, 'error');
        if (intro) intro.style.display = 'block';
    }
}

// Load Stats
async function loadStats() {
    try {
        console.log('[loadStats] Fetching stats...');
        const stats = await api('/stats');
        console.log('[loadStats] Received stats:', stats);
        state.stats = stats;

        const totalEl = document.getElementById('total-emails');
        const unreadEl = document.getElementById('total-unread');
        const deletableEl = document.getElementById('deletable');
        const keepEl = document.getElementById('would-keep');

        console.log('[loadStats] DOM elements:', { totalEl, unreadEl, deletableEl, keepEl });

        if (totalEl) totalEl.textContent = stats.total_emails || 0;
        if (unreadEl) unreadEl.textContent = stats.total_unread || 0;
        if (deletableEl) deletableEl.textContent = stats.deletable || 0;
        if (keepEl) keepEl.textContent = stats.would_keep || 0;

        console.log('[loadStats] Rendering categories:', stats.categories);
        renderCategoryList(stats.categories);
        console.log('[loadStats] Rendering top senders:', stats.top_senders);
        renderTopSenders(stats.top_senders);
        console.log('[loadStats] Done!');

    } catch (error) {
        console.error('[loadStats] Failed to load stats:', error);
    }
}


// Render Category List
function renderCategoryList(categories) {
    const container = document.getElementById('category-list');
    if (!categories || Object.keys(categories).length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 20px;">No emails fetched yet. Click "Fetch Emails" to start.</p>';
        return;
    }

    const icons = {
        spam: 'ri-spam-2-line',
        newsletter: 'ri-newspaper-line',
        ads: 'ri-advertisement-line',
        social: 'ri-group-line',
        promotions: 'ri-gift-line',
        important: 'ri-star-line',
        uncertain: 'ri-question-line',
        personal: 'ri-user-line'
    };

    container.innerHTML = Object.entries(categories).map(([cat, data]) => `
        <div class="category-item" onclick="viewCategory('${cat}')">
            <div class="category-info">
                <div class="category-icon ${cat}">
                    <i class="${icons[cat] || 'ri-mail-line'}"></i>
                </div>
                <span class="category-name">${cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
            </div>
            <div class="category-count">
                ${data.unread > 0 ? `<span class="category-unread">${data.unread} unread</span>` : ''}
                <span class="category-badge">${data.count}</span>
            </div>
        </div>
    `).join('');
}

// Render Top Senders
function renderTopSenders(senders) {
    const container = document.getElementById('top-senders');
    if (!senders || senders.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 20px;">No sender data available.</p>';
        return;
    }

    container.innerHTML = senders.map(sender => `
        <div class="sender-item">
            <div class="sender-info">
                <span class="sender-name">${sender.name || sender.email}</span>
                <span class="sender-email">${sender.email}</span>
            </div>
            <div class="sender-stats">
                ${sender.unread > 0 ? `<span style="color: var(--warning)">${sender.unread} unread</span>` : ''}
                <span class="sender-count">${sender.count}</span>
            </div>
        </div>
    `).join('');
}

// View Category
function viewCategory(category) {
    state.currentCategory = category;
    switchView('categories');
    loadCategoryEmails(category);
}

// Load Categories
async function loadCategories() {
    try {
        const data = await api('/emails/by-category');

        const tabsContainer = document.getElementById('category-tabs');

        let tabsHtml = Object.keys(data).map(cat => `
            <span class="category-tab ${cat === state.currentCategory ? 'active' : ''}"
                  onclick="loadCategoryEmails('${cat}')">${cat}</span>
        `).join('');

        // Add Summarize Button and AI Status
        tabsHtml += `
            <div class="category-tab-actions">
                <div class="ai-status" id="ai-status-indicator" title="Checking AI status...">
                    <div class="ai-status-dot"></div>
                    <span>AI Offline</span>
                </div>
                <button class="btn-summarize" onclick="summarizeCategory()" id="btn-summarize-category" disabled>
                    <i class="ri-magic-line"></i>
                    Summarize
                </button>
            </div>
        `;

        tabsContainer.innerHTML = tabsHtml;

        // Check AI Status
        checkAIStatus();

        if (state.currentCategory) {
            loadCategoryEmails(state.currentCategory);
        } else if (Object.keys(data).length > 0) {
            loadCategoryEmails(Object.keys(data)[0]);
        }

    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Load Category Emails
async function loadCategoryEmails(category) {
    state.currentCategory = category;

    // Update tab styles
    document.querySelectorAll('.category-tab').forEach(tab => {
        tab.classList.toggle('active', tab.textContent === category);
    });

    // Reset Summary Panel
    closeCategorySummary();

    // Enable/Disable Summarize Button based on AI status
    const btnSummarize = document.getElementById('btn-summarize-category');
    if (btnSummarize) {
        btnSummarize.disabled = !state.aiAvailable;
        btnSummarize.innerHTML = '<i class="ri-magic-line"></i> Summarize ' + category;
    }

    try {
        const data = await api(`/emails?category=${category}&read_filter=${state.readFilter}`);
        renderEmailList(data.emails, 'category-emails');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Load Sender Groups
async function loadSenderGroups() {
    try {
        showLoading('Loading sender groups...');
        const data = await api(`/emails/grouped?read_filter=${state.readFilter}`);
        state.groups = data.groups;
        renderSenderGroups(data.groups);
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Render Sender Groups
function renderSenderGroups(groups) {
    const container = document.getElementById('sender-list');
    if (!groups || groups.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">No emails loaded. Fetch emails first.</p>';
        return;
    }

    container.innerHTML = groups.map((group, idx) => `
        <div class="sender-group" id="group-${idx}">
            <div class="sender-group-header" onclick="toggleGroup(${idx})">
                <div class="sender-group-info">
                    <h4>${group.sender || group.sender_email}</h4>
                    <p>${group.sender_email}</p>
                </div>
                <div class="sender-group-stats">
                    <div class="sender-group-stat">
                        <span class="value">${group.total}</span>
                        <span class="label">Emails</span>
                    </div>
                    <div class="sender-group-stat">
                        <span class="value" style="color: var(--warning)">${group.unread}</span>
                        <span class="label">Unread</span>
                    </div>
                    <div class="sender-group-actions">
                        ${group.has_unsubscribe ? `
                            <button class="btn btn-sm btn-warning" onclick="event.stopPropagation(); unsubscribeSender('${group.sender_email}')">
                                <i class="ri-mail-close-line"></i>
                            </button>
                        ` : ''}
                        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteSender('${group.sender_email}')">
                            <i class="ri-delete-bin-line"></i>
                        </button>
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); summarizeSender('${group.sender_email}')">
                            <i class="ri-robot-line"></i>
                        </button>
                    </div>
                </div>
            </div>
            <div class="sender-group-emails">
                ${group.preview_emails ? group.preview_emails.map(email => renderEmailCard(email)).join('') : ''}
            </div>
        </div>
    `).join('');
}

// Toggle Sender Group
function toggleGroup(idx) {
    document.getElementById(`group-${idx}`).classList.toggle('expanded');
}

// Load Uncertain Emails
async function loadUncertainEmails() {
    try {
        const data = await api('/emails?category=uncertain');
        const container = document.getElementById('uncertain-emails');

        if (!data.emails || data.emails.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">No uncertain emails to review. Great job!</p>';
            return;
        }

        renderEmailList(data.emails, 'uncertain-emails', true);

    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Render Email List
function renderEmailList(emails, containerId, showReviewActions = false) {
    const container = document.getElementById(containerId);
    if (!emails || emails.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">No emails in this category.</p>';
        return;
    }

    container.innerHTML = emails.map(email => renderEmailCard(email, showReviewActions)).join('');
}

// Render Email Card
function renderEmailCard(email, showReviewActions = false) {
    const date = email.date ? new Date(email.date).toLocaleDateString() : '';
    const categoryColors = {
        spam: 'background: #fee2e2; color: #dc2626;',
        newsletter: 'background: #dbeafe; color: #2563eb;',
        ads: 'background: #fef3c7; color: #d97706;',
        social: 'background: #ddd6fe; color: #7c3aed;',
        promotions: 'background: #d1fae5; color: #059669;',
        important: 'background: #fce7f3; color: #db2777;',
        uncertain: 'background: #f1f5f9; color: #64748b;',
        personal: 'background: #ccfbf1; color: #0d9488;'
    };

    return `
        <div class="email-card ${!email.is_read ? 'unread' : ''}" onclick="openEmail('${email.id}')">
            <div class="email-header">
                <span class="email-sender">${email.sender || email.sender_email}</span>
                <span class="email-date">${date}</span>
            </div>
            <div class="email-subject">${email.subject || '(No Subject)'}</div>
            <div class="email-snippet">${email.snippet || ''}</div>
            <div class="email-footer">
                <span class="email-category" style="${categoryColors[email.category] || ''}">${email.category || 'unknown'}</span>
                <div class="email-actions">
                    ${showReviewActions ? `
                        <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); quickFeedback('${email.id}', 'keep')">
                            <i class="ri-check-line"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); quickFeedback('${email.id}', 'delete')">
                            <i class="ri-close-line"></i>
                        </button>
                    ` : `
                        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteEmail('${email.id}')">
                            <i class="ri-delete-bin-line"></i>
                        </button>
                    `}
                </div>
            </div>
        </div>
    `;
}

// Open Email Modal
async function openEmail(emailId) {
    try {
        const data = await api(`/emails?sender=`);
        const email = data.emails.find(e => e.id === emailId);

        if (!email) {
            // Fetch single email
            showToast('Loading email...', 'info');
            return;
        }

        state.currentEmail = email;

        document.getElementById('modal-subject').textContent = email.subject || '(No Subject)';
        document.getElementById('modal-sender').textContent = `From: ${email.sender} <${email.sender_email}>`;
        document.getElementById('modal-date').textContent = email.date ? new Date(email.date).toLocaleString() : '';
        document.getElementById('modal-preview').textContent = email.body_preview || email.snippet || '';

        // Show/hide unsubscribe button
        const unsubBtn = document.getElementById('modal-unsubscribe');
        unsubBtn.style.display = (email.unsubscribe_link || email.unsubscribe_email) ? 'flex' : 'none';

        // Load AI summary
        document.getElementById('modal-summary').innerHTML = '<i class="ri-loader-4-line" style="animation: spin 1s linear infinite;"></i><span>Loading AI summary...</span>';

        elements.modal.classList.add('active');

        // Set Category
        const catSelect = document.getElementById('modal-category-select');
        if (catSelect) {
            catSelect.value = email.category || 'uncertain';
        }

        // Fetch summary
        try {
            const summary = await api('/summarize', {
                method: 'POST',
                body: JSON.stringify({ email_id: emailId })
            });
            document.getElementById('modal-summary').innerHTML = `<i class="ri-robot-line"></i><span>${summary.summary}</span>`;
        } catch (e) {
            document.getElementById('modal-summary').innerHTML = `<i class="ri-robot-line"></i><span>${email.snippet}</span>`;
        }

    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Close Modal
function closeModal() {
    elements.modal.classList.remove('active');
    state.currentEmail = null;
}

// Modal Actions
async function markKeep() {
    if (!state.currentEmail) return;
    await submitFeedback(state.currentEmail.id, 'keep');
    closeModal();
    showToast('Marked as keep', 'success');
}

async function markDelete() {
    if (!state.currentEmail) return;
    await deleteEmail(state.currentEmail.id);
    closeModal();
}

async function unsubscribe() {
    if (!state.currentEmail) return;

    try {
        showLoading('Unsubscribing...');
        const result = await api('/unsubscribe', {
            method: 'POST',
            body: JSON.stringify({ email_id: state.currentEmail.id })
        });

        if (result.success) {
            showToast(result.message, 'success');
        } else {
            showToast(result.message, 'error');
        }
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Quick Feedback
async function quickFeedback(emailId, decision) {
    await submitFeedback(emailId, decision);
    showToast(`Marked as ${decision}`, 'success');

    if (decision === 'delete') {
        await deleteEmail(emailId);
    }

    // Refresh view
    if (state.currentView === 'uncertain') {
        loadUncertainEmails();
    }
}

// Submit Feedback
// Submit Feedback
async function submitFeedback(emailId, decision, correctCategory = null) {
    try {
        const payload = { email_id: emailId, decision };
        if (correctCategory) {
            payload.correct_category = correctCategory;
        }
        await api('/feedback', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    } catch (error) {
        console.error('Failed to submit feedback:', error);
    }
}

async function changeCategory(newCategory) {
    if (!state.currentEmail) return;

    // Optimistic update
    state.currentEmail.category = newCategory;

    await submitFeedback(state.currentEmail.id, 'move', newCategory);
    showToast(`Category updated to ${newCategory}`, 'success');
}

// Delete Email
async function deleteEmail(emailId) {
    try {
        await api('/delete', {
            method: 'POST',
            body: JSON.stringify({ email_ids: [emailId] })
        });
        showToast('Email deleted', 'success');
        loadStats();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Delete by Category
async function deleteByCategory(category) {
    if (!confirm(`Delete all ${category} emails? This cannot be undone.`)) return;

    try {
        showLoading(`Deleting ${category} emails...`);
        const result = await api('/delete/by-category', {
            method: 'POST',
            body: JSON.stringify({ category })
        });
        showToast(`Deleted ${result.success} emails`, 'success');
        loadStats();
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Delete Sender
async function deleteSender(senderEmail) {
    if (!confirm(`Delete all emails from ${senderEmail}?`)) return;

    try {
        showLoading('Deleting emails...');
        const result = await api('/delete/by-sender', {
            method: 'POST',
            body: JSON.stringify({ sender_email: senderEmail })
        });
        showToast(`Deleted ${result.success} emails from ${senderEmail}`, 'success');
        loadSenderGroups();
        loadStats();
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Unsubscribe Sender
async function unsubscribeSender(senderEmail) {
    if (!confirm(`Unsubscribe from ${senderEmail}?`)) return;

    try {
        showLoading('Unsubscribing...');
        const result = await api('/unsubscribe', {
            method: 'POST',
            body: JSON.stringify({ sender_email: senderEmail })
        });

        if (result.success) {
            showToast(result.message, 'success');
        } else {
            showToast(result.message, 'error');
        }
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Summarize Sender
// AI MODAL LOGIC
function showAIModal(title, content) {
    const titleEl = document.getElementById('ai-modal-title');
    if (titleEl) titleEl.innerHTML = `<i class="ri-sparkling-fill gradient-text"></i> ${title}`;

    const bodyEl = document.getElementById('ai-modal-body');
    if (bodyEl) bodyEl.innerHTML = content;

    const modal = document.getElementById('ai-modal');
    if (modal) modal.classList.add('active');
}

function closeAIModal() {
    const modal = document.getElementById('ai-modal');
    if (modal) modal.classList.remove('active');
}

// Train Model
async function trainModel() {
    showLoading('Training Model...');
    try {
        const result = await api('/train', { method: 'POST', body: JSON.stringify({}) });
        if (result.success) {
            showToast(result.message, 'success');
        } else {
            showToast(result.message, 'warning');
        }
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Ask AI (Individual Email)
async function askAI() {
    if (!state.currentEmail) return;

    try {
        showLoading('Asking AI to analyze this email...');
        const result = await api('/summarize', {
            method: 'POST',
            body: JSON.stringify({ email_id: state.currentEmail.id })
        });

        let content = '';
        if (result.suggested_category) {
            content = `
                <div class="ai-result">
                    <p><strong>Suggested Category:</strong> <span class="badge badge-${result.suggested_category}">${result.suggested_category}</span></p>
                    <p><strong>Reasoning:</strong> ${result.reasoning}</p>
                    <hr>
                    <p><strong>Summary:</strong> ${result.summary}</p>
                </div>
             `;
        } else {
            content = result.summary || JSON.stringify(result);
        }

        showAIModal('Email Analysis', content);

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Summarize Sender
async function summarizeSender(senderEmail) {
    try {
        showLoading('Generating AI summary...');
        const result = await api('/summarize', {
            method: 'POST',
            body: JSON.stringify({ sender_email: senderEmail })
        });

        // Simple formatting for now
        const content = `
            <div class="ai-summary-text" style="white-space: pre-wrap;">${result.summary}</div>
        `;

        showAIModal(`Summary: ${senderEmail}`, content);
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Train Model
async function trainModel() {
    try {
        showLoading('Retraining AI model...');
        const result = await api('/train', { method: 'POST' });
        showToast(result.message, result.success ? 'success' : 'info');
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// --- Settings Logic ---

function setupSettingsListeners() {
    // Theme Button Toggle
    const themeBtn = document.getElementById('theme-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const isLight = document.body.classList.contains('light-mode');
            if (isLight) {
                // Switch to Dark
                document.body.classList.remove('light-mode');
                saveSetting('theme', 'dark');
                updateThemeButton(false);
            } else {
                // Switch to Light
                document.body.classList.add('light-mode');
                saveSetting('theme', 'light');
                updateThemeButton(true);
            }
        });
    }

    // Color Picker
    const colorInput = document.getElementById('accent-color');
    if (colorInput) {
        // Live preview
        colorInput.addEventListener('input', (e) => {
            document.documentElement.style.setProperty('--primary', e.target.value);
        });

        // Save on change (final selection)
        colorInput.addEventListener('change', (e) => {
            saveSetting('accent_color', e.target.value);
        });
    }

    // Toggle Key Visibility
    const toggleBtn = document.getElementById('toggle-key');
    const keyInput = document.getElementById('gemini-key');
    if (toggleBtn && keyInput) {
        toggleBtn.addEventListener('click', () => {
            const type = keyInput.type === 'password' ? 'text' : 'password';
            keyInput.type = type;
            toggleBtn.innerHTML = type === 'password' ? '<i class="ri-eye-line"></i>' : '<i class="ri-eye-off-line"></i>';
        });
    }

    // Save API Key
    const saveApiBtn = document.getElementById('save-api-btn');
    if (saveApiBtn && keyInput) {
        saveApiBtn.addEventListener('click', () => {
            if (keyInput.value.trim()) {
                saveSetting('gemini_api_key', keyInput.value);
            } else {
                showToast('Please enter an API key', 'info');
            }
        });
    }

    // Delete API Key Button
    const deleteKeyBtn = document.getElementById('delete-key-btn');
    if (deleteKeyBtn && keyInput) {
        deleteKeyBtn.addEventListener('click', async () => {
            if (confirm('Are you sure you want to delete the API key?')) {
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ gemini_api_key: '' })
                    });
                    if (response.ok) {
                        keyInput.value = '';
                        showToast('API Key deleted', 'success');
                    } else {
                        showToast('Failed to delete API key', 'error');
                    }
                } catch (error) {
                    showToast('Error deleting API key', 'error');
                }
            }
        });
    }


    // Reset Account Button
    const resetBtn = document.getElementById('reset-account-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            if (confirm('Are you sure you want to reset your account? This will delete your Gmail credentials and log you out. You will need to set up again.')) {
                try {
                    const response = await fetch('/api/setup/reset', { method: 'POST' });
                    const result = await response.json();
                    if (result.success) {
                        window.location.href = '/';
                    } else {
                        showToast('Reset failed: ' + result.error, 'error');
                    }
                } catch (error) {
                    showToast('Error resetting account', 'error');
                }
            }
        });
    }
}

function updateThemeButton(isLight) {
    const btn = document.getElementById('theme-btn');
    if (btn) {
        if (isLight) {
            btn.innerHTML = '<i class="ri-sun-line"></i><span>Light Mode</span>';
        } else {
            btn.innerHTML = '<i class="ri-moon-line"></i><span>Dark Mode</span>';
        }
    }
}

async function saveSetting(key, value) {
    try {
        const data = { [key]: value };
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            if (key === 'gemini_api_key') {
                showToast('API Key saved successfully', 'success');
            }
        } else {
            showToast('Failed to save settings', 'error');
        }
    } catch (error) {
        showToast('Error saving settings', 'error');
    }
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();

        // Apply Theme
        if (settings.theme) {
            const isLight = settings.theme === 'light';
            if (isLight) {
                document.body.classList.add('light-mode');
            } else {
                document.body.classList.remove('light-mode');
            }
            updateThemeButton(isLight);
        } else {
            // Default Dark
            updateThemeButton(false);
        }

        // Apply Accent Color
        if (settings.accent_color) {
            const colorInput = document.getElementById('accent-color');
            if (colorInput) {
                colorInput.value = settings.accent_color;
            }
            document.documentElement.style.setProperty('--primary', settings.accent_color);
        }

        // Apply API Key
        const keyInput = document.getElementById('gemini-key');
        if (settings.gemini_api_key && keyInput) {
            keyInput.value = settings.gemini_api_key;
        }

    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

// Custom Dropdown Component
function setupCustomDropdown() {
    const dropdown = document.getElementById('filter-dropdown');
    if (!dropdown) return;

    const trigger = dropdown.querySelector('.dropdown-trigger');
    const menu = dropdown.querySelector('.dropdown-menu');
    const options = dropdown.querySelectorAll('.dropdown-option');
    const hiddenInput = document.getElementById('read-filter');
    const iconSpan = trigger.querySelector('.dropdown-icon');
    const textSpan = trigger.querySelector('.dropdown-text');
    const textShortSpan = trigger.querySelector('.dropdown-text-short');

    // Toggle dropdown
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('open');
    });

    // Handle option selection
    options.forEach(option => {
        option.addEventListener('click', () => {
            const value = option.dataset.value;
            const icon = option.dataset.icon || option.querySelector('.option-icon').textContent;
            const text = option.dataset.text || option.querySelector('.option-text').textContent;
            const textShort = option.dataset.short || text;

            // Update trigger display
            iconSpan.textContent = icon;
            textSpan.textContent = text;
            if (textShortSpan) textShortSpan.textContent = textShort;

            // Update hidden input
            if (hiddenInput) hiddenInput.value = value;

            // Update active state
            options.forEach(opt => opt.classList.remove('active'));
            option.classList.add('active');

            // Update app state
            state.readFilter = value;
            if (state.currentView !== 'overview') {
                switchView(state.currentView);
            }

            // Close dropdown
            dropdown.classList.remove('open');
        });

    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });

    // Close dropdown on escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            dropdown.classList.remove('open');
        }
    });
}
// ==========================================
// AI Features
// ==========================================

// Check AI Status
async function checkAIStatus() {
    try {
        const data = await api('/ai/status');
        state.aiAvailable = data.available && data.model_ready;

        const indicator = document.getElementById('ai-status-indicator');
        const btnSummarize = document.getElementById('btn-summarize-category');

        if (indicator) {
            const dot = indicator.querySelector('.ai-status-dot');
            const text = indicator.querySelector('span');

            if (state.aiAvailable) {
                dot.classList.add('online');
                text.textContent = 'AI Ready';
                indicator.title = `Model: ${data.model}`;
            } else {
                dot.classList.remove('online');
                text.textContent = 'AI Offline';
                indicator.title = data.error || 'AI service not available';
            }
        }

        if (btnSummarize) {
            btnSummarize.disabled = !state.aiAvailable;
        }

    } catch (error) {
        console.error('Failed to check AI status:', error);
        state.aiAvailable = false;
    }
}

// Summarize Category
async function summarizeCategory() {
    if (!state.currentCategory) return;

    const panel = document.getElementById('category-summary-panel');
    const content = document.getElementById('category-summary-content');
    const btn = document.getElementById('btn-summarize-category');

    // Show panel with loading state
    panel.style.display = 'block';
    content.innerHTML = `
        <div class="loading">
            <i class="ri-loader-4-line"></i>
            <span>Analyzing emails in ${state.currentCategory}... This may take a moment.</span>
        </div>
    `;

    if (btn) btn.disabled = true;

    try {
        const data = await api('/ai/summarize/category', {
            method: 'POST',
            body: JSON.stringify({ category: state.currentCategory })
        });

        // Format the summary (convert markdown-style lists to HTML if needed)
        // Simple formatter for now
        let formattedSummary = data.summary
            .replace(/\n/g, '<br>')
            .replace(/- /g, '• ');

        content.innerHTML = `
            <p><strong>${data.email_count} emails analyzed</strong></p>
            <div style="margin-top: 10px;">${formattedSummary}</div>
        `;

    } catch (error) {
        content.innerHTML = `
            <div style="color: var(--danger)">
                <i class="ri-error-warning-line"></i>
                Failed to generate summary: ${error.message}
            </div>
        `;
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Close Category Summary
function closeCategorySummary() {
    const panel = document.getElementById('category-summary-panel');
    if (panel) {
        panel.style.display = 'none';
        // clear content to save memory/DOM
        document.getElementById('category-summary-content').innerHTML = '';
    }
}
