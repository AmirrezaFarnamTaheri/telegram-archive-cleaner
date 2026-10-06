/**
 * Alpine.js application controller for Telegram Archive Cleaner
 * Browser UI controller.
 * - Side-by-side caption comparison and retention choices
 * Handles backup verification and optional cloud upload.
 * Handles Telegram login and proxy settings.
 * - Demo data when the local service is unavailable
 */

function cleanerApp() {
  return {
    dbHealthy: false,
    isOfflineMode: false,
    apiAuthRequired: false,
    chats: [],
    selectedChat: null,
    stats: null,
    candidates: [],
    selectedCandidateIds: [],
    diffGroups: [],
    backups: [],
    activeTab: 'candidates',
    candidateFilter: 'all',
    searchQuery: '',
    scanning: false,
    deleting: false,
    uploading: false,
    dryRunMode: true,
    confirmDeleteAcknowledge: false,
    deleteConfirmationText: '',
    apiToken: '',

    // Review pagination
    page: 1,
    pageSize: 25,

    // Layout
    sidebarOpen: typeof window !== 'undefined' ? window.innerWidth >= 768 : true,
    isMobile: typeof window !== 'undefined' ? window.innerWidth < 768 : false,
    showShortcutsModal: false,
    showOnboardingGuide: false,
    showCommandPalette: false,
    commandQuery: '',

    // Message data and media preview
    showRawInspectorModal: false,
    inspectedMessage: null,
    showMediaModal: false,
    inspectMediaUrl: '',
    inspectMediaTitle: '',
    inspectMediaId: null,

    // Action dialogs
    showImportModal: false,
    showDeleteModal: false,
    showAuthModal: false,
    showCloudExportModal: false,

    // Telegram login
    telegramAuth: false,
    authStep: 'phone',
    authPhone: '',
    authCode: '',
    authPassword: '',
    phoneCodeHash: '',
    authLoading: false,
    authApiId: '',
    authApiHash: '',
    authProxyType: '',
    authProxyHost: '',
    authProxyPort: '',
    authProxyUser: '',
    authProxyPass: '',
    authProxySecret: '',
    hasApiCredentials: false,
    showCredentialsSection: false,
    showProxySection: false,

    // Relay status
    relayConfigured: false,
    relayProvider: 'Direct',

    // Backup upload
    exportTargetBackup: null,
    cloudProvider: 'github',
    cloudToken: '',
    cloudRepo: '',
    cloudFolderId: '',
    cloudExporting: false,

    // Notifications
    toasts: [],
    toastCounter: 0,

    // Command menu
    commandList: [
      { id: 'cmd_demo', title: 'Load Demo Archive', category: 'Testing', action: 'load_demo' },
      { id: 'cmd_scan', title: 'Run Analysis', category: 'Analysis', action: 'run_scan' },
      { id: 'cmd_tab_cand', title: 'Open Review', category: 'Navigation', action: 'tab_candidates' },
      { id: 'cmd_tab_diff', title: 'Open Compare View', category: 'Navigation', action: 'tab_diffs' },
      { id: 'cmd_tab_backups', title: 'Open Backups', category: 'Navigation', action: 'tab_backups' },
      { id: 'cmd_tab_auth', title: 'Open Connection Settings', category: 'Navigation', action: 'tab_auth' },
      { id: 'cmd_select_all', title: 'Stage All Ready Items', category: 'Selection', action: 'select_all' },
      { id: 'cmd_deselect_all', title: 'Clear Staged Items', category: 'Selection', action: 'deselect_all' },
      { id: 'cmd_filter_exact', title: 'Show Exact Duplicates', category: 'Filter', action: 'filter_exact' },
      { id: 'cmd_filter_diff', title: 'Show Media Variants', category: 'Filter', action: 'filter_diff' },
      { id: 'cmd_filter_link', title: 'Show Dead Links', category: 'Filter', action: 'filter_link' },
      { id: 'cmd_filter_policy', title: 'Show Telegram Restrictions', category: 'Filter', action: 'filter_policy' },
      { id: 'cmd_import', title: 'Import Telegram Desktop JSON', category: 'Import', action: 'import_json' },
      { id: 'cmd_auth', title: 'Set Up Telegram Login', category: 'Import', action: 'open_auth' },
      { id: 'cmd_delete', title: 'Review Deletion', category: 'Cleanup', action: 'open_delete' },
      { id: 'cmd_toggle_dry', title: 'Toggle Simulation', category: 'Cleanup', action: 'toggle_dry' },
      { id: 'cmd_toggle_sidebar', title: 'Toggle Source Sidebar', category: 'View', action: 'toggle_sidebar' },
      { id: 'cmd_shortcuts', title: 'Show Keyboard Shortcuts', category: 'Help', action: 'open_shortcuts' }
    ],

    async init() {
      try {
        this.apiToken = window.localStorage.getItem('tg_cleaner_api_token') || '';
      } catch {
        this.apiToken = '';
      }
      this.isMobile = window.innerWidth < 768;
      this.sidebarOpen = !this.isMobile;
      window.addEventListener('resize', () => {
        const wasMobile = this.isMobile;
        this.isMobile = window.innerWidth < 768;
        if (!wasMobile && this.isMobile) {
          this.sidebarOpen = false;
        } else if (wasMobile && !this.isMobile) {
          this.sidebarOpen = true;
        }
      });

      // Handle standalone filesystem launch (file://)
      if (typeof window !== 'undefined' && window.location.protocol === 'file:') {
        this.isOfflineMode = true;
        this.dbHealthy = false;
        this.loadDemoMockData();
      } else {
        await this.checkHealth();
        if (this.dbHealthy) {
          this.isOfflineMode = false;
          await this.checkAuthStatus();
          await this.checkRelayStatus();
          await this.loadChats();
          await this.loadBackups();
        } else if (this.apiAuthRequired) {
          this.isOfflineMode = false;
          this.chats = [];
          this.selectedChat = null;
          this.stats = null;
        } else {
          // Use demo data when the local service is unavailable.
          this.isOfflineMode = true;
          this.loadDemoMockData();
        }
      }

      // Register global keyboard shortcuts
      window.addEventListener('keydown', (e) => {
        // Toggle command palette via Ctrl+K or Cmd+K
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          this.showCommandPalette = !this.showCommandPalette;
          if (this.showCommandPalette) {
            this.$nextTick(() => {
              const el = document.getElementById('commandPaletteInput');
              if (el) el.focus();
            });
          }
          return;
        }

        // Toggle help via ? key when outside form inputs
        if (e.key === '?' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
          e.preventDefault();
          this.showShortcutsModal = !this.showShortcutsModal;
          return;
        }

        // Focus search input via / key
        if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
          e.preventDefault();
          this.activeTab = 'candidates';
          this.$nextTick(() => {
            const el = document.getElementById('candidateSearchInput');
            if (el) el.focus();
          });
          return;
        }

        // Close top modal via Escape key
        if (e.key === 'Escape') {
          this.closeAllModals();
        }
      });
    },

    showToast(message, type = 'info', duration = 4000) {
      const id = ++this.toastCounter;
      this.toasts.push({ id, message, type });
      setTimeout(() => {
        this.removeToast(id);
      }, duration);
    },

    removeToast(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    },

    closeAllModals() {
      this.showImportModal = false;
      this.showDeleteModal = false;
      this.showAuthModal = false;
      this.showCloudExportModal = false;
      this.showMediaModal = false;
      this.showShortcutsModal = false;
      this.showCommandPalette = false;
      this.showRawInspectorModal = false;
      this.confirmDeleteAcknowledge = false;
      this.deleteConfirmationText = '';
    },

    async apiFetch(input, init = {}) {
      const options = { ...init };
      const headers = new Headers(options.headers || {});
      if (this.apiToken) {
        headers.set('Authorization', `Bearer ${this.apiToken}`);
      }
      options.headers = headers;
      return window.fetch(input, options);
    },

    saveApiToken() {
      if (typeof window === 'undefined') return;
      const token = (this.apiToken || '').trim();
      this.apiToken = token;
      try {
        if (token) {
          window.localStorage.setItem('tg_cleaner_api_token', token);
          this.showToast('Dashboard API token saved locally in this browser', 'success');
        } else {
          window.localStorage.removeItem('tg_cleaner_api_token');
          this.showToast('Dashboard API token cleared', 'info');
        }
      } catch {
        this.showToast('Browser storage is unavailable; using the API token for this page only', 'warning');
      }
      this.refreshAll();
    },

    statValue(name) {
      if (!this.stats) return 0;
      const aliases = {
        same_media_diff_caption: ['same_media_diff_caption', 'diff_duplicates'],
        policy_restricted: ['policy_restricted', 'policy_flags'],
        estimated_reclaimable_bytes: ['estimated_reclaimable_bytes', 'total_reclaimable_bytes'],
        total_deletion_candidates: ['total_deletion_candidates'],
      };
      for (const key of aliases[name] || [name]) {
        if (this.stats[key] !== undefined && this.stats[key] !== null) return this.stats[key];
      }
      if (name === 'total_deletion_candidates') return this.candidates.length;
      return 0;
    },

    candidateHasCategory(candidate, category) {
      const types = Array.isArray(candidate.flag_types) && candidate.flag_types.length
        ? candidate.flag_types
        : [candidate.flag_type];
      const normalized = types.filter(Boolean).map(type => String(type).toUpperCase());
      const groups = {
        exact: ['DUPLICATE_EXACT_TEXT', 'DUPLICATE_EXACT_MEDIA', 'DUPLICATE_FUZZY_TEXT', 'DUPLICATE_FORWARD', 'EXACT_DUPLICATE'],
        diff: ['DUPLICATE_SAME_MEDIA_DIFF_CAPTION', 'DIFF_DUPLICATE'],
        link: ['STALE_DEAD_LINK', 'STALE_EXPIRED_INVITE', 'DEAD_LINK'],
        policy: ['POLICY_RESTRICTED', 'POLICY_EMPTY_MEDIA', 'POLICY_DELETED_ACCOUNT', 'POLICY_VIOLATION'],
      };
      return (groups[category] || []).some(type => normalized.includes(type));
    },

    candidateLabel(candidate) {
      if (this.candidateHasCategory(candidate, 'diff')) return 'Changed copy';
      if (this.candidateHasCategory(candidate, 'exact')) return 'Duplicate';
      if (this.candidateHasCategory(candidate, 'link')) return 'Dead link';
      if (this.candidateHasCategory(candidate, 'policy')) return 'Telegram issue';
      return 'Review';
    },

    candidateTone(candidate) {
      if (this.candidateHasCategory(candidate, 'link')) return 'amber';
      if (this.candidateHasCategory(candidate, 'policy')) return 'rose';
      if (this.candidateHasCategory(candidate, 'diff')) return 'violet';
      return 'sky';
    },

    candidateEligible(candidate) {
      return candidate && candidate.recommended_for_deletion !== false;
    },

    candidateStatusLabel(candidate) {
      return this.candidateEligible(candidate) ? 'Ready to stage' : 'Needs approval';
    },

    candidateScore(candidate) {
      const value = Number(candidate?.confidence ?? 0);
      return `${Math.max(0, Math.min(100, Math.round(value * 100)))}%`;
    },

    readyCount() {
      return this.candidates.filter(candidate => this.candidateEligible(candidate)).length;
    },

    reviewOnlyCount() {
      return this.candidates.filter(candidate => !this.candidateEligible(candidate)).length;
    },

    categoryCount(category) {
      return this.candidates.filter(candidate => this.candidateHasCategory(candidate, category)).length;
    },

    readyFilteredCandidates() {
      return this.filteredCandidates().filter(candidate => this.candidateEligible(candidate));
    },

    stageCandidate(candidate) {
      if (!this.candidateEligible(candidate)) {
        this.showToast('Approve this item before staging it', 'warning');
        return;
      }
      if (!this.selectedCandidateIds.includes(candidate.id)) {
        this.selectedCandidateIds = [...this.selectedCandidateIds, candidate.id];
      }
    },

    unstageCandidate(candidate) {
      this.selectedCandidateIds = this.selectedCandidateIds.filter(id => id !== candidate.id);
    },

    async setResultApproval(candidate, eligible) {
      if (!candidate || !this.selectedChat) return;
      if (eligible === false) {
        this.unstageCandidate(candidate);
      }

      if (this.isOfflineMode) {
        candidate.recommended_for_deletion = eligible;
        this.showToast(eligible ? 'Result approved for staging in demo mode' : 'Result now requires approval in demo mode', eligible ? 'success' : 'info');
        return;
      }

      try {
        const res = await this.apiFetch(`/api/chats/${this.selectedChat.id}/findings/${candidate.id}/eligibility`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ eligible }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || 'Approval update failed');
        }
        candidate.recommended_for_deletion = eligible;
        this.showToast(eligible ? 'Result approved for staging' : 'Result now requires approval', eligible ? 'success' : 'info');
      } catch (err) {
        this.showToast(`Could not update approval: ${err.message}`, 'error');
      }
    },

    openDeleteReview(preferLive = false) {
      if (this.selectedCandidateIds.length === 0) {
        this.showToast('Stage at least one message before continuing', 'warning');
        return;
      }
      this.dryRunMode = !preferLive;
      this.confirmDeleteAcknowledge = false;
      this.deleteConfirmationText = '';
      this.showDeleteModal = true;
    },

    filteredCommands() {
      if (!this.commandQuery || this.commandQuery.trim() === '') {
        return this.commandList;
      }
      const q = this.commandQuery.toLowerCase().trim();
      return this.commandList.filter(c =>
        c.title.toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q)
      );
    },

    executeCommand(cmd) {
      this.showCommandPalette = false;
      this.commandQuery = '';

      switch (cmd.action) {
        case 'load_demo':
          this.generateDemoData();
          break;
        case 'run_scan':
          this.runScan();
          break;
        case 'tab_candidates':
          this.activeTab = 'candidates';
          break;
        case 'tab_diffs':
          this.activeTab = 'diffs';
          break;
        case 'tab_backups':
          this.activeTab = 'backups';
          break;
        case 'tab_auth':
          this.activeTab = 'auth';
          break;
        case 'select_all':
          this.selectAllCandidates();
          break;
        case 'deselect_all':
          this.deselectAllCandidates();
          break;
        case 'filter_exact':
          this.filterByKpi('exact');
          break;
        case 'filter_diff':
          this.filterByKpi('diff');
          break;
        case 'filter_link':
          this.filterByKpi('link');
          break;
        case 'filter_policy':
          this.filterByKpi('policy');
          break;
        case 'import_json':
          this.showImportModal = true;
          break;
        case 'open_auth':
          this.activeTab = 'auth';
          break;
        case 'open_delete':
          this.openDeleteReview(false);
          break;
        case 'toggle_dry':
          this.dryRunMode = !this.dryRunMode;
          this.showToast(`Simulation mode is now ${this.dryRunMode ? 'enabled (dry-run)' : 'disabled (live modification)'}`, 'info');
          break;
        case 'toggle_sidebar':
          this.sidebarOpen = !this.sidebarOpen;
          break;
        case 'open_shortcuts':
          this.showShortcutsModal = true;
          break;
      }
    },

    openRawInspector(message) {
      this.inspectedMessage = message;
      this.showRawInspectorModal = true;
    },

    selectedCandidatesBytes() {
      let total = 0;
      for (const id of this.selectedCandidateIds) {
        const item = this.candidates.find(c => c.id === id);
        if (item && item.file_size) {
          total += item.file_size;
        }
      }
      return total;
    },

    async checkRelayStatus() {
      if (this.isOfflineMode) return;
      try {
        const res = await this.apiFetch('/api/relay/status');
        if (res.ok) {
          const data = await res.json();
          this.relayConfigured = data.configured === true;
          this.relayProvider = data.provider || 'Direct';
        }
      } catch {
        this.relayConfigured = false;
      }
    },

    async checkAuthStatus() {
      if (this.isOfflineMode) return;
      try {
        const res = await this.apiFetch('/api/auth/status');
        if (res.ok) {
          const data = await res.json();
          this.telegramAuth = data.authenticated === true;
          this.hasApiCredentials = data.has_credentials === true;
          if (data.api_id) this.authApiId = String(data.api_id);
          if (data.phone) this.authPhone = data.phone;
          if (data.proxy_type) this.authProxyType = data.proxy_type;
          if (data.proxy_host) this.authProxyHost = data.proxy_host;
          if (data.proxy_port) this.authProxyPort = String(data.proxy_port);
          if (!this.hasApiCredentials) {
            this.showCredentialsSection = true;
          }
        } else {
          this.telegramAuth = false;
        }
      } catch {
        this.telegramAuth = false;
      }
    },

    async saveCredentials() {
      if (!this.authApiId || !this.authApiHash) {
        this.showToast('Please provide both API ID and API Hash', 'warning');
        return;
      }
      if (this.isOfflineMode) {
        this.hasApiCredentials = true;
        this.showToast('API credentials saved for this demo session', 'success');
        return;
      }

      this.authLoading = true;
      try {
        const payload = {
          api_id: parseInt(this.authApiId, 10),
          api_hash: this.authApiHash.trim(),
        };
        if (this.authProxyType && this.authProxyHost) {
          payload.proxy_type = this.authProxyType;
          payload.proxy_host = this.authProxyHost.trim();
          if (this.authProxyPort) payload.proxy_port = parseInt(this.authProxyPort, 10);
          if (this.authProxyUser) payload.proxy_username = this.authProxyUser.trim();
          if (this.authProxyPass) payload.proxy_password = this.authProxyPass;
          if (this.authProxySecret) payload.proxy_secret = this.authProxySecret.trim();
        }
        const res = await this.apiFetch('/api/auth/credentials', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          this.hasApiCredentials = true;
          this.showCredentialsSection = false;
          this.showToast('Telegram API credentials persisted successfully', 'success');
        } else {
          const err = await res.json();
          this.showToast(`Credential persistence rejected: ${err.detail || 'Validation error'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Network error: ${err.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async sendAuthCode() {
      if (!this.authPhone) {
        this.showToast('Please enter an international telephone number', 'warning');
        return;
      }
      if (this.isOfflineMode) {
        this.authLoading = true;
        await new Promise(r => setTimeout(r, 600));
        this.authLoading = false;
        this.authStep = 'code';
        this.showToast('Verification code requested (Sandbox preview: enter any 5-digit code)', 'info');
        return;
      }
      if (!this.hasApiCredentials && (!this.authApiId || !this.authApiHash)) {
        this.showCredentialsSection = true;
        this.showToast('Please provide your Telegram API ID and API Hash from my.telegram.org', 'warning');
        return;
      }
      this.authLoading = true;
      try {
        const payload = {
          phone: this.authPhone.trim(),
        };
        if (this.authApiId) payload.api_id = parseInt(this.authApiId, 10);
        if (this.authApiHash) payload.api_hash = this.authApiHash.trim();
        if (this.authProxyType && this.authProxyHost) {
          payload.proxy_type = this.authProxyType;
          payload.proxy_host = this.authProxyHost.trim();
          if (this.authProxyPort) payload.proxy_port = parseInt(this.authProxyPort, 10);
          if (this.authProxyUser) payload.proxy_username = this.authProxyUser.trim();
          if (this.authProxyPass) payload.proxy_password = this.authProxyPass;
          if (this.authProxySecret) payload.proxy_secret = this.authProxySecret.trim();
        }
        const res = await this.apiFetch('/api/auth/send-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          const data = await res.json();
          this.phoneCodeHash = data.phone_code_hash;
          this.authStep = 'code';
          this.hasApiCredentials = true;
          this.showToast('Verification code sent to your Telegram application', 'info');
        } else {
          const err = await res.json();
          if (err.detail && err.detail.includes('Telegram API credentials missing')) {
            this.showCredentialsSection = true;
          }
          this.showToast(`Request rejected: ${err.detail || 'Failed sending code'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Network error: ${err.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async verifyAuthCode() {
      if (!this.authCode) return;
      if (this.isOfflineMode) {
        this.authLoading = true;
        await new Promise(r => setTimeout(r, 600));
        this.authLoading = false;
        this.telegramAuth = true;
        this.showAuthModal = false;
        this.showToast('MTProto authentication established (Sandbox)', 'success');
        return;
      }
      this.authLoading = true;
      try {
        const res = await this.apiFetch('/api/auth/sign-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phone: this.authPhone.trim(),
            code: this.authCode.trim(),
            phone_code_hash: this.phoneCodeHash,
          }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          this.telegramAuth = true;
          this.showAuthModal = false;
          this.showToast('Telegram MTProto authorization successful', 'success');
          await this.loadChats();
        } else if (data.status === '2fa_required') {
          this.authStep = '2fa';
          this.showToast('Two-step cloud password required', 'info');
        } else {
          this.showToast(`Sign in rejected: ${data.detail || 'Invalid code'}`, 'error');
        }
      } catch (e) {
        this.showToast(`Network error: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async check2faPassword() {
      if (!this.authPassword) return;
      if (this.isOfflineMode) {
        this.telegramAuth = true;
        this.showAuthModal = false;
        this.showToast('Two-step cloud authentication complete (Sandbox)', 'success');
        return;
      }
      this.authLoading = true;
      try {
        const res = await this.apiFetch('/api/auth/sign-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phone: this.authPhone.trim(),
            code: this.authCode.trim(),
            phone_code_hash: this.phoneCodeHash,
            password: this.authPassword,
          }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          this.telegramAuth = true;
          this.showAuthModal = false;
          this.showToast('Two-step verification completed. Connected.', 'success');
          await this.loadChats();
        } else {
          this.showToast(`Password rejected: ${data.detail || 'Incorrect password'}`, 'error');
        }
      } catch (e) {
        this.showToast(`Network error: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async checkHealth() {
      if (typeof window !== 'undefined' && window.location.protocol === 'file:') {
        this.dbHealthy = false;
        this.isOfflineMode = true;
        this.apiAuthRequired = false;
        return;
      }
      try {
        const res = await this.apiFetch('/api/health');
        if (res.status === 401) {
          this.dbHealthy = false;
          this.isOfflineMode = false;
          this.apiAuthRequired = true;
          return;
        }
        this.apiAuthRequired = false;
        if (res.ok) {
          const data = await res.json();
          this.dbHealthy = data.db_healthy === true;
          this.isOfflineMode = !this.dbHealthy;
        } else {
          this.dbHealthy = false;
          this.isOfflineMode = true;
        }
      } catch {
        this.dbHealthy = false;
        this.isOfflineMode = true;
        this.apiAuthRequired = false;
      }
    },

    async loadChats() {
      if (this.isOfflineMode) return;
      try {
        const res = await this.apiFetch('/api/chats');
        if (res.ok) {
          this.chats = await res.json();
          if (this.chats.length > 0 && !this.selectedChat) {
            await this.selectChat(this.chats[0]);
          }
        }
      } catch {
        // Fallback to offline demo data on network error
        if (this.chats.length === 0) {
          this.loadDemoMockData();
        }
      }
    },

    async selectChat(chat) {
      this.selectedChat = chat;
      if (this.isMobile) {
        this.sidebarOpen = false;
      }
      this.page = 1;
      if (this.isOfflineMode) {
        if (chat.id === 100000001) {
          this.loadDemoMockData();
        } else {
          this.stats = {
            chat_id: chat.id,
            total_messages: chat.total_messages,
            exact_duplicates: 0,
            diff_duplicates: 0,
            dead_links: 0,
            policy_flags: 0,
            total_reclaimable_bytes: 0,
            last_scanned: chat.last_scanned,
          };
          this.candidates = [];
          this.selectedCandidateIds = [];
          this.diffGroups = [];
        }
        return;
      }
      await this.loadChatDetails(chat.id);
    },

    async loadChatDetails(chatId) {
      if (this.isOfflineMode) return;
      try {
        const statsRes = await this.apiFetch(`/api/chats/${chatId}/stats`);
        if (statsRes.ok) {
          this.stats = await statsRes.json();
        }

        const candsRes = await this.apiFetch(`/api/chats/${chatId}/findings`);
        if (candsRes.ok) {
          this.candidates = await candsRes.json();
          this.selectedCandidateIds = [];
          this.deleteConfirmationText = '';
          this.confirmDeleteAcknowledge = false;
        }

        await this.loadDiffGroups(chatId);
      } catch (err) {
        if (this.dbHealthy) {
          this.showToast(`Failed loading chat records: ${err.message}`, 'error');
        }
      }
    },

    async loadDiffGroups(chatId) {
      if (this.isOfflineMode) return;
      this.diffGroups = [];
      try {
        const res = await this.apiFetch(`/api/chats/${chatId}/duplicate-groups`);
        if (res.ok) {
          const groups = await res.json();
          this.diffGroups = groups.filter(group =>
            group.group_type === 'SAME_MEDIA_DIFF_CAPTION' ||
            group.group_type === 'FUZZY_TEXT' ||
            group.group_type === 'EXACT_MEDIA' ||
            group.group_type === 'EXACT_TEXT'
          );
        }
      } catch (err) {
        if (this.dbHealthy) {
          this.showToast(`Failed loading duplicate groups: ${err.message}`, 'error');
        }
      }
    },

    filteredCandidates() {
      let result = this.candidates;

      if (['exact', 'diff', 'link', 'policy'].includes(this.candidateFilter)) {
        result = result.filter(c => this.candidateHasCategory(c, this.candidateFilter));
      }

      if (this.searchQuery && this.searchQuery.trim() !== '') {
        const q = this.searchQuery.toLowerCase().trim();
        result = result.filter(c => {
          const textMatch = c.text && c.text.toLowerCase().includes(q);
          const reasonMatch = c.reason && c.reason.toLowerCase().includes(q);
          const idMatch = String(c.id).includes(q);
          return textMatch || reasonMatch || idMatch;
        });
      }

      return result;
    },

    paginatedCandidates() {
      const filtered = this.filteredCandidates();
      const start = (this.page - 1) * this.pageSize;
      return filtered.slice(start, start + this.pageSize);
    },

    totalPages() {
      const filtered = this.filteredCandidates();
      return Math.max(1, Math.ceil(filtered.length / this.pageSize));
    },

    nextPage() {
      if (this.page < this.totalPages()) this.page++;
    },

    prevPage() {
      if (this.page > 1) this.page--;
    },

    filterByKpi(kpiType) {
      if (kpiType === 'exact') {
        this.activeTab = 'candidates';
        this.candidateFilter = 'exact';
      } else if (kpiType === 'diff') {
        this.activeTab = 'diffs';
      } else if (kpiType === 'link') {
        this.activeTab = 'candidates';
        this.candidateFilter = 'link';
      } else if (kpiType === 'policy') {
        this.activeTab = 'candidates';
        this.candidateFilter = 'policy';
      } else if (kpiType === 'candidates') {
        this.activeTab = 'candidates';
        this.candidateFilter = 'all';
      } else if (kpiType === 'backups') {
        this.activeTab = 'backups';
      }
    },

    async runScan() {
      if (!this.selectedChat) return;
      this.scanning = true;
      if (this.isOfflineMode) {
        await new Promise(r => setTimeout(r, 600));
        this.scanning = false;
        this.showToast(`Analysis complete: ${this.candidates.length} results found (Demo)`, 'success');
        return;
      }
      try {
        const res = await this.apiFetch(`/api/scan/${this.selectedChat.id}`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.stats = data.stats;
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Analysis complete: ${this.candidates.length} results found`, 'success');
        } else {
          const err = await res.json();
          this.showToast(`Analysis failed: ${err.detail || 'Internal error'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Analysis failed: ${err.message}`, 'error');
      } finally {
        this.scanning = false;
      }
    },

    async setGroupPreset(groupId, preset) {
      if (this.isOfflineMode) {
        this.showToast(`Retention policy "${preset}" assigned to cluster ${groupId} (Sandbox)`, 'info');
        return;
      }
      try {
        const res = await this.apiFetch(`/api/groups/${groupId}/preset`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preset }),
        });
        if (res.ok) {
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Retention policy "${preset}" assigned to cluster ${groupId}`, 'info');
        }
      } catch (err) {
        this.showToast(`Failed assigning preset: ${err.message}`, 'error');
      }
    },

    async openMediaInspect(chatId, msgId, title) {
      if (this.inspectMediaUrl && this.inspectMediaUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.inspectMediaUrl);
      }
      this.inspectMediaUrl = '';
      this.inspectMediaTitle = title || `Message #${msgId} media`;
      this.inspectMediaId = msgId;
      this.showMediaModal = true;
      if (this.isOfflineMode) return;
      try {
        const res = await this.apiFetch(`/api/media/${chatId}/${msgId}`);
        if (!res.ok) {
          this.showToast('No local preview is available for this message', 'info');
          return;
        }
        const blob = await res.blob();
        this.inspectMediaUrl = URL.createObjectURL(blob);
      } catch (err) {
        this.showToast(`Media preview failed: ${err.message}`, 'error');
      }
    },

    async executeBatchDelete() {
      if (!this.selectedChat || this.selectedCandidateIds.length === 0) return;
      if (!this.dryRunMode && !this.telegramAuth && !this.isOfflineMode) {
        this.activeTab = 'auth';
        this.showDeleteModal = false;
        this.showToast('Connect an authorized Telegram session before live deletion', 'warning');
        return;
      }
      if (!this.dryRunMode && !this.confirmDeleteAcknowledge) {
        this.showToast('Confirm the backup requirement before live deletion', 'warning');
        return;
      }
      const expectedPhrase = `DELETE ${this.selectedCandidateIds.length}`;
      if (!this.dryRunMode && this.deleteConfirmationText.trim() !== expectedPhrase) {
        this.showToast(`Type ${expectedPhrase} to confirm this live deletion`, 'warning');
        return;
      }

      this.deleting = true;
      if (this.isOfflineMode) {
        await new Promise(r => setTimeout(r, 600));
        const count = this.selectedCandidateIds.length;
        if (!this.dryRunMode) {
          this.candidates = this.candidates.filter(c => !this.selectedCandidateIds.includes(c.id));
          this.selectedCandidateIds = [];
          this.stats.total_messages = Math.max(0, this.stats.total_messages - count);
          this.backups.unshift({
            filename: `chat_${this.selectedChat.id}_snapshot_${Date.now()}.json`,
            created_at: new Date().toISOString(),
            message_count: count,
            sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
            size_bytes: count * 1024,
          });
        }
        this.showDeleteModal = false;
        this.confirmDeleteAcknowledge = false;
        this.deleteConfirmationText = '';
        this.deleting = false;
        const modeStr = this.dryRunMode ? 'Dry-run simulation' : 'Live deletion';
        this.showToast(`${modeStr} finished: ${count} messages processed. Verified backup recorded.`, 'success', 5000);
        return;
      }

      try {
        const res = await this.apiFetch(`/api/delete/${this.selectedChat.id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message_ids: this.selectedCandidateIds,
            dry_run: this.dryRunMode,
          }),
        });

        if (res.ok) {
          const result = await res.json();
          const modeStr = result.dry_run ? 'Dry-run simulation' : 'Live deletion';
          this.showToast(`${modeStr} finished: ${result.deleted_count} messages processed. Backup verified.`, 'success', 5000);
          this.showDeleteModal = false;
          this.confirmDeleteAcknowledge = false;
          this.deleteConfirmationText = '';
          await this.loadChatDetails(this.selectedChat.id);
          await this.loadBackups();
        } else {
          const err = await res.json();
          this.showToast(`Execution rejected: ${err.detail || 'Failed processing request'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Deletion error: ${err.message}`, 'error');
      } finally {
        this.deleting = false;
      }
    },

    async handleFileUpload(event) {
      const file = event.target.files[0];
      if (!file) return;

      if (this.isOfflineMode) {
        try {
          const text = await file.text();
          const parsed = JSON.parse(text);
          const chatName = parsed.name || file.name.replace(/\.[^/.]+$/, '');
          const newChat = {
            id: parsed.id || Date.now(),
            title: chatName,
            chat_type: parsed.type || 'desktop_export',
            total_messages: Array.isArray(parsed.messages) ? parsed.messages.length : 0,
            last_scanned: null
          };
          this.chats.unshift(newChat);
          await this.selectChat(newChat);
          this.showImportModal = false;
          this.showToast(`Imported ${newChat.total_messages} messages from ${file.name} (Demo)`, 'success');
        } catch (e) {
          this.showToast(`Invalid JSON file format: ${e.message}`, 'error');
        }
        return;
      }

      const formData = new FormData();
      formData.append('file', file);
      this.uploading = true;
      try {
        const res = await this.apiFetch('/api/chats/import-desktop', {
          method: 'POST',
          body: formData,
        });
        if (res.ok) {
          const data = await res.json();
          this.showToast(`Imported ${data.messages_imported} records from "${data.chat_title}"`, 'success');
          this.showImportModal = false;
          await this.loadChats();
        } else {
          const err = await res.json();
          this.showToast(`Import rejected: ${err.detail || 'Invalid archive structure'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Upload error: ${err.message}`, 'error');
      } finally {
        this.uploading = false;
      }
    },

    async loadBackups() {
      if (this.isOfflineMode) return;
      try {
        const res = await this.apiFetch('/api/backups');
        if (res.ok) {
          this.backups = await res.json();
        }
      } catch {
        // Silently preserve stability
      }
    },

    async downloadBackup(backup) {
      if (!backup) return;
      if (this.isOfflineMode) {
        this.showToast('Backup download is available when the local service is running', 'info');
        return;
      }
      try {
        const res = await this.apiFetch(`/api/backups/download/${encodeURIComponent(backup.filename)}`);
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          this.showToast(`Backup download failed: ${detail.detail || 'file unavailable'}`, 'error');
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = backup.filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        this.showToast(`Backup download failed: ${err.message}`, 'error');
      }
    },

    async verifyBackupChecksum(backup) {
      if (this.isOfflineMode) {
        this.showToast(`Backup verified for ${backup.filename} (Demo)`, 'success');
        return;
      }
      try {
        const res = await this.apiFetch(`/api/backups/${encodeURIComponent(backup.filename)}/verify`);
        if (res.ok) {
          const data = await res.json();
          if (data.valid) {
            this.showToast(`Backup verified: SHA-256 matches the file (${data.sha256.substring(0, 16)}...)`, 'success');
          } else {
            this.showToast('Backup check failed: the recorded SHA-256 does not match the file', 'error');
          }
        } else {
          this.showToast('Could not verify the backup', 'error');
        }
      } catch (e) {
        this.showToast(`Verification error: ${e.message}`, 'error');
      }
    },

    openCloudExport(backup) {
      this.exportTargetBackup = backup;
      this.showCloudExportModal = true;
    },

    async executeCloudExport() {
      if (!this.exportTargetBackup || !this.cloudToken) {
        this.showToast('Enter an access token to upload this backup', 'warning');
        return;
      }
      if (this.isOfflineMode) {
        this.cloudExporting = true;
        await new Promise(r => setTimeout(r, 600));
        this.cloudExporting = false;
        this.showCloudExportModal = false;
        this.showToast(`Demo upload to ${this.cloudProvider} completed`, 'success');
        return;
      }
      this.cloudExporting = true;
      try {
        const payload = {
          provider: this.cloudProvider,
          token: this.cloudToken,
          repo: this.cloudProvider === 'github' ? this.cloudRepo : null,
          folder_id: this.cloudProvider === 'google_drive' ? this.cloudFolderId : null,
        };
        const res = await this.apiFetch(`/api/backups/${encodeURIComponent(this.exportTargetBackup.filename)}/cloud-export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          const result = await res.json();
          this.showToast(`Backup uploaded to ${result.provider} (${result.target_path})`, 'success', 5000);
          this.showCloudExportModal = false;
        } else {
          const err = await res.json();
          this.showToast(`Upload failed: ${err.detail || 'Destination rejected the backup'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Export error: ${err.message}`, 'error');
      } finally {
        this.cloudExporting = false;
      }
    },

    async copyToClipboard(text, label = 'Checksum') {
      try {
        await navigator.clipboard.writeText(text);
        this.showToast(`${label} copied to clipboard`, 'info');
      } catch {
        this.showToast('Clipboard access was blocked by the browser', 'warning');
      }
    },

    async refreshAll() {
      await this.checkHealth();
      if (this.apiAuthRequired) {
        this.showToast('An API token is required. Add it in Connection settings.', 'warning');
        this.activeTab = 'auth';
        return;
      }
      if (!this.dbHealthy) {
        this.showToast('The local service is unavailable. Demo mode is using sample data only.', 'info');
        if (!this.isOfflineMode) {
          this.isOfflineMode = true;
          this.loadDemoMockData();
        }
        return;
      }
      this.isOfflineMode = false;
      await this.checkAuthStatus();
      await this.checkRelayStatus();
      await this.loadChats();
      if (this.selectedChat) {
        await this.loadChatDetails(this.selectedChat.id);
      }
      await this.loadBackups();
      this.showToast('Data refreshed', 'info');
    },

    selectAllCandidates() {
      this.selectedCandidateIds = this.filteredCandidates().filter(c => this.candidateEligible(c)).map(c => c.id);
      this.showToast(`Staged ${this.selectedCandidateIds.length} messages`, 'info');
    },

    deselectAllCandidates() {
      this.selectedCandidateIds = [];
      this.showToast('Cleared staged messages', 'info');
    },

    formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    },

    formatDate(dateString) {
      if (!dateString) return 'Pending';
      try {
        const d = new Date(dateString);
        return d.toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit'
        });
      } catch {
        return dateString;
      }
    },

    loadDemoMockData() {
      const demoChat = {
        id: 100000001,
        title: 'Archive Research & Saved Messages',
        chat_type: 'saved_messages',
        total_messages: 8,
        last_scanned: new Date().toISOString(),
      };
      this.chats = [
        demoChat,
        {
          id: 200000002,
          title: 'Design Systems & Engineering Channel',
          chat_type: 'channel',
          total_messages: 142,
          last_scanned: null,
        },
      ];
      this.selectedChat = demoChat;
      this.stats = {
        chat_id: demoChat.id,
        total_messages: 8,
        exact_duplicates: 2,
        same_media_diff_caption: 2,
        dead_links: 1,
        policy_restricted: 1,
        total_deletion_candidates: 2,
        estimated_reclaimable_bytes: 2962000,
      };
      this.candidates = [
        {
          id: 102,
          chat_id: demoChat.id,
          date: '2026-03-01T10:05:00',
          text: 'Infrastructure configuration snapshot and deployment keys',
          media_type: 'photo',
          file_size: 2450000,
          flag_type: 'DUPLICATE_EXACT_MEDIA',
          flag_types: ['DUPLICATE_EXACT_MEDIA'],
          recommended_for_deletion: true,
          confidence: 1.0,
          reason: 'Identical SHA-256 byte payload to Message #101',
        },
        {
          id: 205,
          chat_id: demoChat.id,
          date: '2026-03-10T14:00:00',
          text: 'Workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
          media_type: 'photo',
          file_size: 1850000,
          flag_type: 'DUPLICATE_SAME_MEDIA_DIFF_CAPTION',
          flag_types: ['DUPLICATE_SAME_MEDIA_DIFF_CAPTION'],
          recommended_for_deletion: false,
          confidence: 0.78,
          reason: 'Superseded announcement variant of Message #206',
        },
        {
          id: 310,
          chat_id: demoChat.id,
          date: '2026-02-15T09:20:00',
          text: 'Reference documentation: https://example-invalid-domain-404.org/specs.pdf',
          media_type: 'document',
          file_size: 512000,
          flag_type: 'STALE_DEAD_LINK',
          flag_types: ['STALE_DEAD_LINK'],
          recommended_for_deletion: true,
          confidence: 0.99,
          reason: 'HTTP 404 Not Found unreachable target',
        },
        {
          id: 415,
          chat_id: demoChat.id,
          date: '2026-01-20T11:45:00',
          text: 'Forwarded post restricted under Telegram platform terms policy',
          media_type: null,
          file_size: 0,
          flag_type: 'POLICY_RESTRICTED',
          flag_types: ['POLICY_RESTRICTED'],
          recommended_for_deletion: false,
          confidence: 1.0,
          reason: 'Flagged for restriction: terms violation',
        },
      ];
      this.selectedCandidateIds = [];
      this.diffGroups = [
        {
          group_id: 'grp_photo_banner',
          messages: [
            {
              id: 205,
              chat_id: demoChat.id,
              date: '2026-03-10T14:00:00',
              text: 'Workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
              media_type: 'photo',
              media_id: 'photo_demo_banner',
            },
            {
              id: 206,
              chat_id: demoChat.id,
              date: '2026-03-10T16:30:00',
              text: 'Workshop banner (UPDATED): Sunday 19:00 UTC https://t.me/joinchat/new_active_link',
              media_type: 'photo',
              media_id: 'photo_demo_banner',
            },
          ],
          primary_message_id: 206,
          suggested_keep_id: 206,
          recommended_preset: 'KEEP_NEWEST',
          group_type: 'SAME_MEDIA_DIFF_CAPTION',
          diff_summary: { similarity_ratio: 62.5, length_delta: 18 },
        },
      ];
      this.backups = [
        {
          filename: 'chat_100000001_snapshot_demo.json',
          created_at: new Date().toISOString(),
          message_count: 4,
          sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
          size_bytes: 18432,
        },
      ];
      this.showOnboardingGuide = false;
      if (this.isMobile) {
        this.sidebarOpen = false;
      }
    },

    async generateDemoData() {
      if (this.isOfflineMode) {
        this.loadDemoMockData();
        this.showToast('Loaded demo data', 'success');
        return;
      }

      try {
        const res = await this.apiFetch('/api/demo/generate', { method: 'POST' });
        if (res.ok) {
          await this.loadChats();
          const demoChat = this.chats.find((c) => c.id === 9999) || this.chats[0];
          if (demoChat) {
            await this.selectChat(demoChat);
          }
          this.showOnboardingGuide = false;
          this.showToast('Loaded demonstration archive with duplicate and link fixtures', 'success');
          return;
        }
      } catch {
        // Fallback to client mock
      }

      this.isOfflineMode = true;
      this.loadDemoMockData();
      this.showToast('Loaded demo data', 'success');
    },
  };
}

if (typeof window !== 'undefined') {
  window.cleanerApp = cleanerApp;
}
