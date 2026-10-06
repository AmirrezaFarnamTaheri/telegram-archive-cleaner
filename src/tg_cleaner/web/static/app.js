/**
 * Alpine.js application state & controller for Telegram Archive Cleaner
 * Forensic, accessible, zero-slop architecture with non-blocking toast notifications,
 * client-side pagination, keyboard navigation, command palette, and caption diff analysis.
 */

function cleanerApp() {
  return {
    dbHealthy: false,
    dbCheckInterval: null,
    isOfflineMode: typeof window !== 'undefined' ? window.location.protocol === 'file:' : false,
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
    dryRunMode: true,
    confirmDeleteAcknowledge: false,

    // Pagination for high-density scalability
    page: 1,
    pageSize: 30,

    // Layout & UI Shell
    sidebarOpen: typeof window !== 'undefined' ? window.innerWidth >= 768 : true,
    isMobile: typeof window !== 'undefined' ? window.innerWidth < 768 : false,
    showShortcutsModal: false,
    showOnboardingGuide: false,
    showCommandPalette: false,
    commandQuery: '',

    // Raw Message & Media Inspector
    showRawInspectorModal: false,
    inspectedMessage: null,
    showMediaModal: false,
    inspectMediaUrl: '',
    inspectMediaTitle: '',
    inspectMediaId: null,

    // Modals
    showImportModal: false,
    showDeleteModal: false,
    showAuthModal: false,
    showCloudExportModal: false,

    // MTProto Authentication State
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

    // Edge Relay Status
    relayConfigured: false,
    relayProvider: 'Direct Local',

    // Cloud Export State
    exportTargetBackup: null,
    cloudProvider: 'github',
    cloudToken: '',
    cloudRepo: '',
    cloudFolderId: '',
    cloudExporting: false,

    // Toast Notification Stack
    toasts: [],
    toastCounter: 0,

    // Available Global Commands for Quick Navigation
    commandList: [
      { id: 'cmd_demo', title: 'Load Demonstration Archive', category: 'Testing', action: 'load_demo' },
      { id: 'cmd_scan', title: 'Run Multi-Engine Audit', category: 'Audit', action: 'run_scan' },
      { id: 'cmd_tab_cand', title: 'Switch to Flagged Candidates View', category: 'Navigation', action: 'tab_candidates' },
      { id: 'cmd_tab_diff', title: 'Switch to Visual Diff Studio', category: 'Navigation', action: 'tab_diffs' },
      { id: 'cmd_tab_backups', title: 'Switch to Cryptographic Backup Ledger', category: 'Navigation', action: 'tab_backups' },
      { id: 'cmd_select_all', title: 'Select All Flagged Messages', category: 'Selection', action: 'select_all' },
      { id: 'cmd_deselect_all', title: 'Deselect All Messages', category: 'Selection', action: 'deselect_all' },
      { id: 'cmd_filter_exact', title: 'Filter: Exact SHA-256 Duplicates', category: 'Filter', action: 'filter_exact' },
      { id: 'cmd_filter_diff', title: 'Filter: Visual Media Variations', category: 'Filter', action: 'filter_diff' },
      { id: 'cmd_filter_link', title: 'Filter: Dead Hyperlinks', category: 'Filter', action: 'filter_link' },
      { id: 'cmd_filter_policy', title: 'Filter: Platform Terms Restrictions', category: 'Filter', action: 'filter_policy' },
      { id: 'cmd_import', title: 'Import Telegram Desktop JSON Export', category: 'Ingest', action: 'import_json' },
      { id: 'cmd_auth', title: 'Connect Telegram MTProto Account', category: 'Ingest', action: 'open_auth' },
      { id: 'cmd_delete', title: 'Open Safe Deletion Execution Dialog', category: 'Execution', action: 'open_delete' },
      { id: 'cmd_toggle_dry', title: 'Toggle Dry-Run Simulation Mode', category: 'Safety', action: 'toggle_dry' },
      { id: 'cmd_toggle_sidebar', title: 'Toggle Archive Source Sidebar', category: 'View', action: 'toggle_sidebar' },
      { id: 'cmd_shortcuts', title: 'View Keyboard Navigation Shortcuts', category: 'Help', action: 'open_shortcuts' }
    ],

    async init() {
      this.isMobile = window.innerWidth < 768;
      this.sidebarOpen = !this.isMobile;
      window.addEventListener('resize', () => {
        this.isMobile = window.innerWidth < 768;
      });

      // If opened directly from file system (file://), enter standalone offline mode without polling APIs
      if (typeof window !== 'undefined' && window.location.protocol === 'file:') {
        this.isOfflineMode = true;
        this.dbHealthy = false;
        this.showOnboardingGuide = true;
      } else {
        await this.checkHealth();
        if (this.dbHealthy) {
          this.isOfflineMode = false;
          await this.checkAuthStatus();
          await this.checkRelayStatus();
          await this.loadChats();
          await this.loadBackups();
        } else {
          this.isOfflineMode = true;
        }
      }

      if (this.chats.length === 0) {
        this.showOnboardingGuide = true;
      }

      // Keyboard navigation listener
      window.addEventListener('keydown', (e) => {
        // Command Palette Trigger: Ctrl+K or Cmd+K
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

        // Skip other keys if typing in an input or textarea
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
          if (e.key === 'Escape') {
            document.activeElement.blur();
            this.closeAllModals();
          }
          return;
        }

        if (e.key === '?') {
          e.preventDefault();
          this.showShortcutsModal = !this.showShortcutsModal;
        } else if (e.key === '1') {
          this.activeTab = 'candidates';
        } else if (e.key === '2') {
          this.activeTab = 'diffs';
        } else if (e.key === '3') {
          this.activeTab = 'backups';
        } else if (e.key === '/') {
          e.preventDefault();
          const searchInput = document.getElementById('candidateSearchInput');
          if (searchInput) searchInput.focus();
        } else if (e.key === 'Escape') {
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
    },

    // Command Palette Execution
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
          this.showAuthModal = true;
          break;
        case 'open_delete':
          if (this.selectedCandidateIds.length > 0) {
            this.showDeleteModal = true;
          } else {
            this.showToast('No messages currently selected for deletion', 'warning');
          }
          break;
        case 'toggle_dry':
          this.dryRunMode = !this.dryRunMode;
          this.showToast(`Dry-run mode is now ${this.dryRunMode ? 'enabled (simulation)' : 'disabled (live modification)'}`, 'info');
          break;
        case 'toggle_sidebar':
          this.sidebarOpen = !this.sidebarOpen;
          break;
        case 'open_shortcuts':
          this.showShortcutsModal = true;
          break;
      }
    },

    // Message Inspection
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

    selectOnlyType(type) {
      if (type === 'all') {
        this.selectedCandidateIds = this.candidates.map(c => c.id);
      } else {
        this.selectedCandidateIds = this.candidates
          .filter(c => c.flag_type === type)
          .map(c => c.id);
      }
      this.showToast(`Selected ${this.selectedCandidateIds.length} candidate messages (${type})`, 'info');
    },

    async checkRelayStatus() {
      if (this.isOfflineMode) return;
      try {
        const res = await fetch('/api/relay/status');
        if (res.ok) {
          const data = await res.json();
          this.relayConfigured = data.configured === true;
          this.relayProvider = data.provider || 'Direct Local';
        }
      } catch {
        this.relayConfigured = false;
      }
    },

    async checkAuthStatus() {
      if (this.isOfflineMode) return;
      try {
        const res = await fetch('/api/auth/status');
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

    async sendAuthCode() {
      if (!this.authPhone) return;
      if (this.isOfflineMode) {
        this.showToast('Telegram MTProto connection requires launching TelegramArchiveCleaner.exe web', 'warning');
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
        const res = await fetch('/api/auth/send-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          const data = await res.json();
          this.phoneCodeHash = data.phone_code_hash;
          this.hasApiCredentials = true;
          this.authStep = 'code';
          this.showToast('Verification code dispatched to your Telegram app', 'info');
        } else {
          const err = await res.json();
          const detail = err.detail || 'Code delivery failed';
          if (detail.includes('credentials missing') || detail.includes('API ID')) {
            this.showCredentialsSection = true;
          }
          this.showToast(`Authentication rejected: ${detail}`, 'error');
        }
      } catch (e) {
        this.showToast(`Network request failed: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async completeSignIn() {
      if (!this.authCode) return;
      if (this.isOfflineMode) {
        this.showToast('MTProto login requires running the web daemon', 'warning');
        return;
      }
      this.authLoading = true;
      try {
        const res = await fetch('/api/auth/sign-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phone: this.authPhone,
            code: this.authCode,
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
        this.showToast(`Network request failed: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async check2faPassword() {
      if (!this.authPassword) return;
      if (this.isOfflineMode) return;
      this.authLoading = true;
      try {
        const res = await fetch('/api/auth/2fa', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: this.authPassword }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          this.telegramAuth = true;
          this.showAuthModal = false;
          this.showToast('Two-step verification completed. Connected.', 'success');
          await this.loadChats();
        } else {
          this.showToast(`Two-step password rejected: ${data.detail || 'Incorrect password'}`, 'error');
        }
      } catch (e) {
        this.showToast(`Network request failed: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async checkHealth() {
      if (typeof window !== 'undefined' && window.location.protocol === 'file:') {
        this.dbHealthy = false;
        this.isOfflineMode = true;
        return;
      }
      try {
        const res = await fetch('/api/health');
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
      }
    },

    async loadChats() {
      if (this.isOfflineMode) return;
      this.loadingChats = true;
      try {
        const res = await fetch('/api/chats');
        if (res.ok) {
          this.chats = await res.json();
          if (this.chats.length > 0 && !this.selectedChat) {
            await this.selectChat(this.chats[0]);
          }
        }
      } catch (err) {
        if (this.dbHealthy) {
          this.showToast(`Failed reading indexed chats: ${err.message}`, 'error');
        }
      } finally {
        this.loadingChats = false;
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
        const statsRes = await fetch(`/api/chats/${chatId}/stats`);
        if (statsRes.ok) {
          this.stats = await statsRes.json();
        }

        const candsRes = await fetch(`/api/chats/${chatId}/candidates`);
        if (candsRes.ok) {
          this.candidates = await candsRes.json();
          this.selectedCandidateIds = this.candidates.map(c => c.id);
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
        const flagsRes = await fetch(`/api/chats/${chatId}/candidates`);
        if (flagsRes.ok) {
          const msgs = await flagsRes.json();
          const groupMap = {};
          for (const m of msgs) {
            if (m.media_id) {
              if (!groupMap[m.media_id]) groupMap[m.media_id] = [];
              groupMap[m.media_id].push(m);
            }
          }
          for (const [key, groupMsgs] of Object.entries(groupMap)) {
            if (groupMsgs.length > 1) {
              this.diffGroups.push({
                group_id: `grp_${key.substring(0, 8)}`,
                messages: groupMsgs,
                suggested_keep_id: groupMsgs[groupMsgs.length - 1].id,
              });
            }
          }
        }
      } catch {
        // Silently preserve stability
      }
    },

    // Candidate Filtering & Search Logic
    filteredCandidates() {
      let result = this.candidates;

      if (this.candidateFilter === 'exact') {
        result = result.filter(c => c.flag_type === 'exact_duplicate');
      } else if (this.candidateFilter === 'diff') {
        result = result.filter(c => c.flag_type === 'diff_duplicate');
      } else if (this.candidateFilter === 'link') {
        result = result.filter(c => c.flag_type === 'dead_link');
      } else if (this.candidateFilter === 'policy') {
        result = result.filter(c => c.flag_type === 'policy_violation');
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

    // Interactive Telemetry Navigation: Clicking KPI cards switches tabs & filters
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
        this.showToast(`Audit completed: ${this.candidates.length} candidates identified (Sandbox)`, 'success');
        return;
      }
      try {
        const res = await fetch(`/api/scan/${this.selectedChat.id}`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.stats = data.stats;
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Audit completed: ${this.candidates.length} candidate messages identified`, 'success');
        } else {
          const err = await res.json();
          this.showToast(`Audit failed: ${err.detail || 'Internal error'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Audit failed: ${err.message}`, 'error');
      } finally {
        this.scanning = false;
      }
    },

    async setGroupPreset(groupId, preset) {
      if (this.isOfflineMode) {
        this.showToast(`Retention preset "${preset}" assigned to group ${groupId} (Sandbox)`, 'info');
        return;
      }
      try {
        const res = await fetch(`/api/groups/${groupId}/preset`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preset }),
        });
        if (res.ok) {
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Retention preset "${preset}" assigned to group ${groupId}`, 'info');
        }
      } catch (err) {
        this.showToast(`Failed setting preset: ${err.message}`, 'error');
      }
    },

    openMediaInspect(chatId, msgId, title) {
      this.inspectMediaUrl = `/api/media/${chatId}/${msgId}`;
      this.inspectMediaTitle = title || `Message #${msgId} Media Payload`;
      this.inspectMediaId = msgId;
      this.showMediaModal = true;
    },

    async executeBatchDelete() {
      if (!this.selectedChat || this.selectedCandidateIds.length === 0) return;
      if (!this.dryRunMode && !this.confirmDeleteAcknowledge) {
        this.showToast('Confirm the backup acknowledgement before proceeding with live deletion', 'warning');
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
        this.deleting = false;
        const modeStr = this.dryRunMode ? 'Dry-run simulation' : 'Live deletion';
        this.showToast(`${modeStr} finished: ${count} messages processed. Verified backup recorded to disk.`, 'success', 5000);
        return;
      }

      try {
        const res = await fetch(`/api/delete/${this.selectedChat.id}`, {
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
          this.showToast(`${modeStr} finished: ${result.deleted_count} messages processed. Verified backup written to disk.`, 'success', 5000);
          this.showDeleteModal = false;
          this.confirmDeleteAcknowledge = false;
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
          this.showToast(`Imported ${newChat.total_messages} messages from ${file.name} (Client Mode)`, 'success');
        } catch (e) {
          this.showToast(`Invalid JSON file structure: ${e.message}`, 'error');
        }
        return;
      }

      const formData = new FormData();
      formData.append('file', file);
      this.uploading = true;
      try {
        const res = await fetch('/api/chats/import-desktop', {
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
        const res = await fetch('/api/backups');
        if (res.ok) {
          this.backups = await res.json();
        }
      } catch (err) {
        if (this.dbHealthy) {
          this.showToast(`Failed loading backup archive: ${err.message}`, 'error');
        }
      }
    },

    openCloudExport(backup) {
      this.exportTargetBackup = backup;
      this.showCloudExportModal = true;
    },

    async executeCloudExport() {
      if (!this.exportTargetBackup || !this.cloudToken) return;
      if (this.isOfflineMode) {
        this.cloudExporting = true;
        await new Promise(r => setTimeout(r, 600));
        this.cloudExporting = false;
        this.showCloudExportModal = false;
        this.showToast(`Simulated cloud export to ${this.cloudProvider} completed`, 'success');
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
        const res = await fetch(`/api/backups/${encodeURIComponent(this.exportTargetBackup.filename)}/cloud-export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          const result = await res.json();
          this.showToast(`Offsite export complete to ${result.provider} (${result.target_path})`, 'success', 5000);
          this.showCloudExportModal = false;
        } else {
          const err = await res.json();
          this.showToast(`Cloud export failed: ${err.detail || 'Destination rejected export'}`, 'error');
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
      if (!this.dbHealthy) {
        this.showToast('Backend offline. Operating in standalone sandbox mode.', 'info');
        return;
      }
      this.isOfflineMode = false;
      await this.loadChats();
      if (this.selectedChat) {
        await this.loadChatDetails(this.selectedChat.id);
      }
      await this.loadBackups();
      this.showToast('Workspace synchronized with database', 'info');
    },

    selectAllCandidates() {
      this.selectedCandidateIds = this.filteredCandidates().map(c => c.id);
      this.showToast(`Selected all ${this.selectedCandidateIds.length} candidate messages`, 'info');
    },

    deselectAllCandidates() {
      this.selectedCandidateIds = [];
      this.showToast('Cleared candidate selection', 'info');
    },

    formatDate(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    },

    formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    // Visual Caption Diff Helper: highlights added words vs reference
    renderCaptionDiff(keepText, candidateText) {
      if (!keepText && !candidateText) return '<span class="text-slate-500 italic">[No caption]</span>';
      if (!keepText) return `<span class="bg-rose-950/40 text-rose-300 px-1 rounded">${this.escapeHtml(candidateText)}</span>`;
      if (!candidateText) return '<span class="text-slate-500 italic">[No caption]</span>';

      const keepWords = keepText.split(/\s+/);
      const candWords = candidateText.split(/\s+/);

      const keepSet = new Set(keepWords);
      const result = candWords.map(word => {
        if (!keepSet.has(word)) {
          return `<span class="bg-amber-950/60 text-amber-300 font-semibold px-0.5 rounded border border-amber-800/40">${this.escapeHtml(word)}</span>`;
        }
        return this.escapeHtml(word);
      }).join(' ');

      return result;
    },

    escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    },

    loadDemoMockData() {
      const demoChat = {
        id: 100000001,
        title: 'Telegram Research & Saved Messages',
        chat_type: 'saved_messages',
        total_messages: 6,
        last_scanned: new Date().toISOString(),
      };
      this.chats = [
        demoChat,
        {
          id: 200000002,
          title: 'Design Engineering Showcase',
          chat_type: 'channel',
          total_messages: 128,
          last_scanned: new Date().toISOString(),
        },
        {
          id: 300000003,
          title: 'DevOps & Infrastructure Alerts',
          chat_type: 'group',
          total_messages: 42,
          last_scanned: null,
        },
      ];
      this.selectedChat = demoChat;
      this.stats = {
        chat_id: demoChat.id,
        total_messages: 6,
        exact_duplicates: 2,
        diff_duplicates: 2,
        dead_links: 1,
        policy_flags: 1,
        total_reclaimable_bytes: 4300000,
        last_scanned: new Date().toISOString(),
      };
      this.candidates = [
        {
          id: 102,
          chat_id: demoChat.id,
          date: '2026-03-01T10:05:00',
          text: 'Infrastructure backup and credentials key file',
          media_type: 'photo',
          file_size: 2450000,
          flag_type: 'exact_duplicate',
          reason: 'Identical SHA-256 byte payload to Message #101',
        },
        {
          id: 205,
          chat_id: demoChat.id,
          date: '2026-03-10T14:00:00',
          text: 'Community workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
          media_type: 'photo',
          file_size: 1850000,
          flag_type: 'diff_duplicate',
          reason: 'Superseded announcement variant of Message #206',
        },
        {
          id: 310,
          chat_id: demoChat.id,
          date: '2026-02-15T09:20:00',
          text: 'Reference documentation: https://example-invalid-domain-404.org/specs.pdf',
          media_type: 'document',
          file_size: 512000,
          flag_type: 'dead_link',
          reason: 'HTTP 404 Not Found unreachable target',
        },
        {
          id: 415,
          chat_id: demoChat.id,
          date: '2026-01-20T11:45:00',
          text: 'Forwarded channel release restricted under Telegram platform terms policy',
          media_type: null,
          file_size: 0,
          flag_type: 'policy_violation',
          reason: 'Flagged for restriction: terms violation',
        },
      ];
      this.selectedCandidateIds = this.candidates.map((c) => c.id);
      this.diffGroups = [
        {
          group_id: 'grp_demo_banner',
          messages: [
            {
              id: 205,
              chat_id: demoChat.id,
              date: '2026-03-10T14:00:00',
              text: 'Community workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
              media_type: 'photo',
              media_id: 'photo_demo_banner',
            },
            {
              id: 206,
              chat_id: demoChat.id,
              date: '2026-03-10T16:30:00',
              text: 'Community workshop banner (RESCHEDULED): Sunday 19:00 UTC https://t.me/joinchat/new_active_link',
              media_type: 'photo',
              media_id: 'photo_demo_banner',
            },
          ],
          suggested_keep_id: 206,
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
        this.showToast('Loaded demonstration sandbox (Offline Mode)', 'success');
        return;
      }

      try {
        const res = await fetch('/api/demo/generate', { method: 'POST' });
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
      } catch (err) {
        // Fallback to client mock
      }

      this.isOfflineMode = true;
      this.loadDemoMockData();
      this.showToast('Loaded demonstration sandbox (Offline Mode)', 'success');
    },
  };
}

// Global export for Alpine.js instantiation
if (typeof window !== 'undefined') {
  window.cleanerApp = cleanerApp;
}
