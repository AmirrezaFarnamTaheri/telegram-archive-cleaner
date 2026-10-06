/**
 * Alpine.js application state & controller for Telegram Archive Cleaner
 * Forensic, accessible, zero-slop architecture with non-blocking toast notifications,
 * client-side pagination, keyboard navigation, and caption diff analysis.
 */

function cleanerApp() {
  return {
    dbHealthy: true,
    dbCheckInterval: null,
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

    // Modals
    showImportModal: false,
    showDeleteModal: false,
    showAuthModal: false,
    showCloudExportModal: false,
    showMediaModal: false,
    inspectMediaUrl: '',
    inspectMediaTitle: '',
    inspectMediaId: null,

    // MTProto Authentication State
    telegramAuth: false,
    authStep: 'phone',
    authPhone: '',
    authCode: '',
    authPassword: '',
    phoneCodeHash: '',
    authLoading: false,

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

    async init() {
      this.isMobile = window.innerWidth < 768;
      this.sidebarOpen = !this.isMobile;
      window.addEventListener('resize', () => {
        this.isMobile = window.innerWidth < 768;
      });

      await this.checkHealth();
      await this.checkAuthStatus();
      await this.checkRelayStatus();
      await this.loadChats();
      await this.loadBackups();

      // Check if first-run without chats
      if (this.chats.length === 0) {
        this.showOnboardingGuide = true;
      }

      // Keyboard navigation listener
      window.addEventListener('keydown', (e) => {
        // Skip if typing in an input or textarea
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
      this.confirmDeleteAcknowledge = false;
    },

    async checkRelayStatus() {
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
      try {
        const res = await fetch('/api/auth/status');
        if (res.ok) {
          const data = await res.json();
          this.telegramAuth = data.authenticated === true;
        }
      } catch {
        this.telegramAuth = false;
      }
    },

    async generateDemoData() {
      try {
        const res = await fetch('/api/demo/generate', { method: 'POST' });
        if (res.ok) {
          await this.loadChats();
          const demoChat = this.chats.find(c => c.id === 9999);
          if (demoChat) {
            await this.selectChat(demoChat);
          }
          this.showOnboardingGuide = false;
          this.showToast('Interactive sandbox archive loaded with perceptual & link fixtures', 'success');
        } else {
          this.showToast('Failed to load demo data', 'error');
        }
      } catch (err) {
        this.showToast(`Demo load error: ${err.message}`, 'error');
      }
    },

    async sendAuthCode() {
      if (!this.authPhone) return;
      this.authLoading = true;
      try {
        const res = await fetch('/api/auth/send-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phone: this.authPhone }),
        });
        if (res.ok) {
          const data = await res.json();
          this.phoneCodeHash = data.phone_code_hash;
          this.authStep = 'code';
          this.showToast('Verification code dispatched to your Telegram app', 'info');
        } else {
          const err = await res.json();
          this.showToast(`Authentication error: ${err.detail || 'Failed to dispatch code'}`, 'error');
        }
      } catch (e) {
        this.showToast(`Network error: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async completeSignIn() {
      if (!this.authCode) return;
      this.authLoading = true;
      try {
        const res = await fetch('/api/auth/sign-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phone: this.authPhone,
            code: this.authCode,
            phone_code_hash: this.phoneCodeHash,
            password: this.authPassword || null,
          }),
        });
        if (res.ok) {
          this.showToast('Successfully authenticated Telegram MTProto session', 'success');
          this.showAuthModal = false;
          this.telegramAuth = true;
          this.authStep = 'phone';
          await this.loadChats();
        } else {
          const err = await res.json();
          if (err.detail && err.detail.includes('2FA')) {
            this.authStep = 'password';
            this.showToast('Two-Factor Authentication password required', 'warning');
          } else {
            this.showToast(`Sign-in failed: ${err.detail || 'Invalid code'}`, 'error');
          }
        }
      } catch (e) {
        this.showToast(`Sign-in error: ${e.message}`, 'error');
      } finally {
        this.authLoading = false;
      }
    },

    async checkHealth() {
      try {
        const res = await fetch('/api/health');
        const data = await res.json();
        this.dbHealthy = data.db_healthy === true;
      } catch {
        this.dbHealthy = false;
      }
    },

    async loadChats() {
      try {
        const res = await fetch('/api/chats');
        if (res.ok) {
          this.chats = await res.json();
          if (this.chats.length > 0 && !this.selectedChat) {
            this.selectChat(this.chats[0]);
          }
        }
      } catch (err) {
        this.showToast(`Failed to load chat index: ${err.message}`, 'error');
      }
    },

    async selectChat(chat) {
      this.selectedChat = chat;
      if (this.isMobile) {
        this.sidebarOpen = false;
      }
      this.page = 1;
      await this.loadChatDetails(chat.id);
    },

    async loadChatDetails(chatId) {
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
        this.showToast(`Failed loading chat records: ${err.message}`, 'error');
      }
    },

    async loadDiffGroups(chatId) {
      this.diffGroups = [];
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
    },

    filteredCandidates() {
      let list = this.candidates;
      if (this.candidateFilter === 'exact') {
        list = list.filter(c => c.media_type && !c.text);
      } else if (this.candidateFilter === 'diff') {
        list = list.filter(c => c.media_type && c.text);
      } else if (this.candidateFilter === 'link') {
        list = list.filter(c => c.text && c.text.includes('http'));
      }
      if (this.searchQuery && this.searchQuery.trim() !== '') {
        const q = this.searchQuery.toLowerCase();
        list = list.filter(c => (c.text || '').toLowerCase().includes(q) || String(c.id).includes(q));
      }
      return list;
    },

    paginatedCandidates() {
      const all = this.filteredCandidates();
      const start = (this.page - 1) * this.pageSize;
      return all.slice(start, start + this.pageSize);
    },

    totalPages() {
      const total = this.filteredCandidates().length;
      return Math.max(1, Math.ceil(total / this.pageSize));
    },

    nextPage() {
      if (this.page < this.totalPages()) {
        this.page++;
      }
    },

    prevPage() {
      if (this.page > 1) {
        this.page--;
      }
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
      try {
        const res = await fetch(`/api/scan/${this.selectedChat.id}`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.stats = data.stats;
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Full audit completed: ${this.candidates.length} candidates identified`, 'success');
        } else {
          const err = await res.json();
          this.showToast(`Audit failed: ${err.detail || 'Server error'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Audit failed: ${err.message}`, 'error');
      } finally {
        this.scanning = false;
      }
    },

    async setGroupPreset(groupId, preset) {
      try {
        const res = await fetch(`/api/groups/${groupId}/preset`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preset }),
        });
        if (res.ok) {
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Preset "${preset}" applied to group ${groupId}`, 'info');
        }
      } catch (err) {
        this.showToast(`Failed to update preset: ${err.message}`, 'error');
      }
    },

    openMediaInspect(chatId, msgId, title) {
      this.inspectMediaUrl = `/api/media/${chatId}/${msgId}`;
      this.inspectMediaTitle = title || `Message #${msgId} Visual Inspection`;
      this.inspectMediaId = msgId;
      this.showMediaModal = true;
    },

    async executeBatchDelete() {
      if (!this.selectedChat || this.selectedCandidateIds.length === 0) return;
      if (!this.dryRunMode && !this.confirmDeleteAcknowledge) {
        this.showToast('Please confirm the safety rollback acknowledgement before live deletion', 'warning');
        return;
      }

      this.deleting = true;
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
          const modeStr = result.dry_run ? 'Dry Run Simulation' : 'Live Deletion';
          this.showToast(`${modeStr} finished: ${result.deleted_count} messages processed. Verified backup recorded.`, 'success', 5000);
          this.showDeleteModal = false;
          this.confirmDeleteAcknowledge = false;
          await this.loadChatDetails(this.selectedChat.id);
          await this.loadBackups();
        } else {
          const err = await res.json();
          this.showToast(`Execution halted: ${err.detail || 'Unknown error'}`, 'error');
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

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/chats/import-desktop', {
          method: 'POST',
          body: formData,
        });

        if (res.ok) {
          const data = await res.json();
          this.showToast(`Imported archive: "${data.title}" (${data.imported_count} messages)`, 'success');
          this.showImportModal = false;
          this.showOnboardingGuide = false;
          await this.loadChats();
        } else {
          const err = await res.json();
          this.showToast(`Import rejected: ${err.detail || 'Invalid archive structure'}`, 'error');
        }
      } catch (err) {
        this.showToast(`Upload error: ${err.message}`, 'error');
      }
    },

    async loadBackups() {
      try {
        const res = await fetch('/api/backups');
        if (res.ok) {
          this.backups = await res.json();
        }
      } catch (err) {
        this.showToast(`Failed to load backup archive: ${err.message}`, 'error');
      }
    },

    openCloudExport(backup) {
      this.exportTargetBackup = backup;
      this.showCloudExportModal = true;
    },

    async executeCloudExport() {
      if (!this.exportTargetBackup || !this.cloudToken) return;
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
          this.showToast(`Cloud export failed: ${err.detail || 'Server rejected export'}`, 'error');
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
        this.showToast('Failed to copy to clipboard', 'warning');
      }
    },

    async refreshAll() {
      await this.checkHealth();
      await this.loadChats();
      if (this.selectedChat) {
        await this.loadChatDetails(this.selectedChat.id);
      }
      await this.loadBackups();
      this.showToast('Workspace synchronized with database', 'info');
    },

    selectAllCandidates() {
      this.selectedCandidateIds = this.filteredCandidates().map(c => c.id);
    },

    deselectAllCandidates() {
      this.selectedCandidateIds = [];
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

      // Simple set comparison for altered wording
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

    async generateDemoData() {
      let backendSuccess = false;
      try {
        const demoPayload = {
          name: 'Telegram Research & Saved Messages',
          type: 'saved_messages',
          id: 100000001,
          messages: [
            {
              id: 101,
              type: 'message',
              date: '2026-03-01T10:00:00',
              text: 'Infrastructure backup and credentials key file',
              media_type: 'photo',
              file_size: 2450000,
            },
            {
              id: 102,
              type: 'message',
              date: '2026-03-01T10:05:00',
              text: 'Infrastructure backup and credentials key file',
              media_type: 'photo',
              file_size: 2450000,
            },
            {
              id: 205,
              type: 'message',
              date: '2026-03-10T14:00:00',
              text: 'Community workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
              media_type: 'photo',
              file_size: 1850000,
            },
            {
              id: 206,
              type: 'message',
              date: '2026-03-10T16:30:00',
              text: 'Community workshop banner (RESCHEDULED): Sunday 19:00 UTC https://t.me/joinchat/new_active_link',
              media_type: 'photo',
              file_size: 1850000,
            },
            {
              id: 310,
              type: 'message',
              date: '2026-02-15T09:20:00',
              text: 'Reference documentation: https://example-invalid-domain-404.org/specs.pdf',
              media_type: 'document',
              file_size: 512000,
            },
            {
              id: 415,
              type: 'message',
              date: '2026-01-20T11:45:00',
              text: 'Forwarded channel release restricted under Telegram platform terms policy',
              media_type: null,
              file_size: 0,
            }
          ]
        };

        const res = await fetch('/api/chats/import-desktop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(demoPayload)
        });

        if (res.ok) {
          backendSuccess = true;
          await this.loadChats();
          if (this.chats.length > 0) {
            await this.selectChat(this.chats[0]);
            await this.runFullScan();
          }
        }
      } catch (e) {
        // Fallback to client-side mock if backend is offline or opened via file://
      }

      if (!backendSuccess) {
        const demoChat = {
          id: 100000001,
          title: 'Telegram Research & Saved Messages',
          chat_type: 'saved_messages',
          total_messages: 6,
          last_scanned: new Date().toISOString()
        };
        this.chats = [
          demoChat,
          {
            id: 200000002,
            title: 'Design Engineering Showcase',
            chat_type: 'channel',
            total_messages: 128,
            last_scanned: null
          }
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
          last_scanned: new Date().toISOString()
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
            reason: 'Identical SHA-256 byte payload to Message #101'
          },
          {
            id: 205,
            chat_id: demoChat.id,
            date: '2026-03-10T14:00:00',
            text: 'Community workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
            media_type: 'photo',
            file_size: 1850000,
            flag_type: 'diff_duplicate',
            reason: 'Superseded announcement variant of Message #206'
          },
          {
            id: 310,
            chat_id: demoChat.id,
            date: '2026-02-15T09:20:00',
            text: 'Reference documentation: https://example-invalid-domain-404.org/specs.pdf',
            media_type: 'document',
            file_size: 512000,
            flag_type: 'dead_link',
            reason: 'HTTP 404 Not Found unreachable target'
          },
          {
            id: 415,
            chat_id: demoChat.id,
            date: '2026-01-20T11:45:00',
            text: 'Forwarded channel release restricted under Telegram platform terms policy',
            media_type: null,
            file_size: 0,
            flag_type: 'policy_violation',
            reason: 'Flagged for restriction: terms violation'
          }
        ];
        this.selectedCandidateIds = this.candidates.map(c => c.id);
        this.diffGroups = [
          {
            group_id: 'grp_demo_cluster',
            messages: [
              {
                id: 205,
                chat_id: demoChat.id,
                date: '2026-03-10T14:00:00',
                text: 'Community workshop banner: Saturday 18:00 UTC https://t.me/joinchat/old_expired_link',
                media_type: 'photo',
                media_id: 'hash_demo_banner'
              },
              {
                id: 206,
                chat_id: demoChat.id,
                date: '2026-03-10T16:30:00',
                text: 'Community workshop banner (RESCHEDULED): Sunday 19:00 UTC https://t.me/joinchat/new_active_link',
                media_type: 'photo',
                media_id: 'hash_demo_banner'
              }
            ],
            suggested_keep_id: 206
          }
        ];
        this.backups = [
          {
            filename: 'chat_100000001_demo_snapshot.json',
            created_at: new Date().toISOString(),
            message_count: 4,
            sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
            size_bytes: 18432
          }
        ];
      }

      this.showOnboardingGuide = false;
      if (this.isMobile) {
        this.sidebarOpen = false;
      }
      this.showToast('Loaded interactive demo sandbox with sample Telegram archives', 'success');
    }
  };
}

// Global export for Alpine.js instantiation
if (typeof window !== 'undefined') {
  window.cleanerApp = cleanerApp;
}
