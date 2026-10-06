/**
 * Alpine.js application state & controller for Telegram Archive Cleaner
 * Forensic, accessible, zero-slop architecture with non-blocking toast notifications
 */

function cleanerApp() {
  return {
    dbHealthy: true,
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

    // Toast Notification System
    toasts: [],
    toastCounter: 0,

    async init() {
      await this.checkHealth();
      await this.checkAuthStatus();
      await this.checkRelayStatus();
      await this.loadChats();
      await this.loadBackups();
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
          this.showToast('Interactive demo archive loaded successfully', 'success');
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
          this.showToast(`Error: ${err.detail || 'Failed to dispatch code'}`, 'error');
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
        this.showToast(`Sign-in network error: ${e.message}`, 'error');
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

    async runScan() {
      if (!this.selectedChat) return;
      this.scanning = true;
      try {
        const res = await fetch(`/api/scan/${this.selectedChat.id}`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.stats = data.stats;
          await this.loadChatDetails(this.selectedChat.id);
          this.showToast(`Full audit completed: ${this.candidates.length} candidates flagged`, 'success');
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
          this.showToast(`${modeStr} finished: ${result.deleted_count} messages processed. Verified backup created.`, 'success', 5000);
          this.showDeleteModal = false;
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
  };
}
