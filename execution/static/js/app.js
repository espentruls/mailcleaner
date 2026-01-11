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

// DOM Elements
const elements = {
    pageTitle: document.getElementById('page-title'),
    readFilter: document.getElementById('read-filter'),
    fetchBtn: document.getElementById('fetch-btn'),
    loadingOverlay: document.getElementById('loading-overlay'),
    loadingText: document.getElementById('loading-text'),
    toastContainer: document.getElementById('toast-container'),
    modal: document.getElementById('email-modal')
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupEventListeners();
    loadStats();
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
        uncertain: 'Review Uncertain'
    };
    elements.pageTitle.textContent = titles[view] || 'Dashboard';

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
    elements.fetchBtn.addEventListener('click', fetchEmails);
    elements.readFilter.addEventListener('change', (e) => {
        state.readFilter = e.target.value;
        if (state.currentView !== 'overview') {
            switchView(state.currentView);
        }
    });

    document.getElementById('delete-all-spam').addEventListener('click', () => deleteByCategory('spam'));
    document.getElementById('delete-newsletters').addEventListener('click', () => deleteByCategory('newsletter'));
    document.getElementById('train-model').addEventListener('click', trainModel);

    // Close modal on backdrop click
    elements.modal.addEventListener('click', (e) => {
        if (e.target === elements.modal) {
            closeModal();
        }
    });
}

// API Functions
async function api(endpoint, options = {}) {
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

// Loading
function showLoading(text = 'Loading...') {
    elements.loadingText.textContent = text;
    elements.loadingOverlay.classList.add('active');
}

function hideLoading() {
    elements.loadingOverlay.classList.remove('active');
}

// Toast Notifications
function showToast(message, type = 'info') {
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
        showLoading('Fetching emails from Gmail...');

        const result = await api('/fetch', {
            method: 'POST',
            body: JSON.stringify({
                max_emails: 1000,
                read_filter: state.readFilter,
                fresh: true
            })
        });

        showToast(`Fetched ${result.total_fetched} emails`, 'success');
        loadStats();

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        hideLoading();
    }
}

// Load Stats
async function loadStats() {
    try {
        const stats = await api('/stats');
        state.stats = stats;

        document.getElementById('total-emails').textContent = stats.total_emails || 0;
        document.getElementById('total-unread').textContent = stats.total_unread || 0;
        document.getElementById('deletable').textContent = stats.deletable || 0;
        document.getElementById('would-keep').textContent = stats.would_keep || 0;

        renderCategoryList(stats.categories);
        renderTopSenders(stats.top_senders);

    } catch (error) {
        console.error('Failed to load stats:', error);
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
        tabsContainer.innerHTML = Object.keys(data).map(cat => `
            <span class="category-tab ${cat === state.currentCategory ? 'active' : ''}"
                  onclick="loadCategoryEmails('${cat}')">${cat}</span>
        `).join('');

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
async function submitFeedback(emailId, decision) {
    try {
        await api('/feedback', {
            method: 'POST',
            body: JSON.stringify({ email_id: emailId, decision })
        });
    } catch (error) {
        console.error('Failed to submit feedback:', error);
    }
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
async function summarizeSender(senderEmail) {
    try {
        showLoading('Generating AI summary...');
        const result = await api('/summarize', {
            method: 'POST',
            body: JSON.stringify({ sender_email: senderEmail })
        });
        showToast(`Summary: ${result.summary}`, 'info');
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
