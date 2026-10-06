/**
 * Alpine.js application state & controller for Telegram Archive Cleaner
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
    scanning: false,
    deleting: false,
    dryRunMode: true,
    showImportModal: false,
    showDeleteModal: false,
    showAuthModal: false,
    telegramAuth: false,
    authStep: 'phone',
    authPhone: '',
    authCode: '',
    authPassword: '',
    phoneCodeHash: '',
    authLoading: false,
    relayConfigured: false,
    relayProvider: 'Direct Local',
    showCloudExportModal: false,
    exportTargetBackup: null,
    cloudProvider: 'github',
    cloudToken: '',
    cloudRepo: '',
    cloudFolderId: '',
    cloudExporting: false,

    async init() {
      await this.checkHealth();
      await this.checkAuthStatus();
      await this.checkRelayStatus();
      await this.loadChats();
      await this.loadBackups();
    },

    async checkRelayStatus() {
      try {
        const res = await fetch('/api/relay/status');
        if (res.ok) {
          const data = await res.json();
          this.relayConfigured = data.configured === true;
          this.relayProvider = data.provider || 'Direct Local';
        }
      } catch (e) {
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
      } catch (e) {
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
        }
      } catch (err) {
        alert('Demo generation failed: ' + err.message);
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
        } else {
          const err = await res.json();
          alert('Error sending code: ' + (err.detail || 'Failed'));
        }
      } catch (e) {
        alert('Network error: ' + e.message);
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
          alert('Successfully authenticated with Telegram!');
          this.showAuthModal = false;
          this.telegramAuth = true;
          this.authStep = 'phone';
          await this.loadChats();
        } else {
          const err = await res.json();
          if (err.detail && err.detail.includes('2FA')) {
            this.authStep = 'password';
          } else {
            alert('Sign-in failed: ' + (err.detail || 'Invalid code'));
          }
        }
      } catch (e) {
        alert('Sign-in error: ' + e.message);
      } finally {
        this.authLoading = false;
      }
    },

    async checkHealth() {
      try {
        const res = await fetch('/api/health');
        const data = await res.json();
        this.dbHealthy = data.db_healthy === true;
      } catch (err) {
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
        console.error('Failed to load chats:', err);
      }
    },

    async selectChat(chat) {
      this.selectedChat = chat;
      await this.loadChatDetails(chat.id);
    },

    async loadChatDetails(chatId) {
      try {
        // Load stats
        const statsRes = await fetch(`/api/chats/${chatId}/stats`);
        if (statsRes.ok) {
          this.stats = await statsRes.json();
        }

        // Load deletion candidates
        const candsRes = await fetch(`/api/chats/${chatId}/candidates`);
        if (candsRes.ok) {
          this.candidates = await candsRes.json();
          this.selectedCandidateIds = this.candidates.map(c => c.id);
        }

        // Load duplicate groups for diff cards
        await this.loadDiffGroups(chatId);
      } catch (err) {
        console.error('Failed to load chat details:', err);
      }
    },

    async loadDiffGroups(chatId) {
      // In a full scan, we query groups from DB or populate from candidate flags
      this.diffGroups = [];
      const flagsRes = await fetch(`/api/chats/${chatId}/candidates`);
      if (flagsRes.ok) {
        const msgs = await flagsRes.json();
        // Check for groups
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

    async runScan() {
      if (!this.selectedChat) return;
      this.scanning = true;
      try {
        const res = await fetch(`/api/scan/${this.selectedChat.id}`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.stats = data.stats;
          await this.loadChatDetails(this.selectedChat.id);
        }
      } catch (err) {
        alert('Audit failed: ' + err.message);
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
        }
      } catch (err) {
        console.error('Failed to apply preset:', err);
      }
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
          alert(`${modeStr} finished! ${result.deleted_count} messages processed. Verified backup saved to: ${result.backup_file}`);
          this.showDeleteModal = false;
          await this.loadChatDetails(this.selectedChat.id);
          await this.loadBackups();
        } else {
          const err = await res.json();
          alert('Deletion failed: ' + (err.detail || 'Unknown error'));
        }
      } catch (err) {
        alert('Deletion error: ' + err.message);
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
          alert(`Successfully imported "${data.title}" (${data.imported_count} messages)!`);
          this.showImportModal = false;
          await this.loadChats();
        } else {
          const err = await res.json();
          alert('Import failed: ' + (err.detail || 'Invalid file'));
        }
      } catch (err) {
        alert('File upload error: ' + err.message);
      }
    },

    async loadBackups() {
      try {
        const res = await fetch('/api/backups');
        if (res.ok) {
          this.backups = await res.json();
        }
      } catch (err) {
        console.error('Failed to load backups:', err);
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
          alert(`Successfully exported to ${result.provider}! Target: ${result.target_path}\nChecksum: ${result.sha256.slice(0, 16)}...`);
          this.showCloudExportModal = false;
        } else {
          const err = await res.json();
          alert('Export failed: ' + (err.detail || 'Server error'));
        }
      } catch (err) {
        alert('Cloud export error: ' + err.message);
      } finally {
        this.cloudExporting = false;
      }
    },

    async refreshAll() {
      await this.checkHealth();
      await this.loadChats();
      if (this.selectedChat) {
        await this.loadChatDetails(this.selectedChat.id);
      }
      await this.loadBackups();
    },

    selectAllCandidates() {
      this.selectedCandidateIds = this.candidates.map(c => c.id);
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
