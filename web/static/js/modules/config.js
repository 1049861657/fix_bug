/**
 * config.js — 配置管理模块
 * 负责：Aider 全局配置 (aider.yaml) + 项目配置 (config/*.yaml)
 */
window._AppModules = window._AppModules || {};

window._AppModules.config = {
  aiderCfg: { model: '', api_base: '', api_key: '', context_tokens: 200000 },
  cfgFilename: '',
  cfgData: null,
  cfgSaving: false,
  cfgMsg: '',
  cfgMsgOk: true,
  cfgShowNew: false,
  cfgNewName: '',
  cfgNewType: 'python',
  cfgSubTab: 'aider',
  cfgAdvanced: false,
  cfgShowKey: false,
  cfgShowToken: false,

  // ── Aider 全局配置 ──────────────────────────────────────────
  async loadAiderCfg() {
    try {
      const r = await fetch('/api/aider-config');
      this.aiderCfg = await r.json();
    } catch (e) {
      this.cfgMsg = '读取 aider.yaml 失败：' + e.message;
      this.cfgMsgOk = false;
    }
  },

  async saveAiderCfg() {
    this.cfgSaving = true;
    this.cfgMsg = '';
    try {
      const r = await fetch('/api/aider-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.aiderCfg),
      });
      if (!r.ok) throw new Error(await r.text());
      this.cfgMsg = '✓ aider.yaml 已保存';
      this.cfgMsgOk = true;
    } catch (e) {
      this.cfgMsg = '保存失败：' + e.message;
      this.cfgMsgOk = false;
    } finally {
      this.cfgSaving = false;
    }
  },

  // ── 项目配置 ────────────────────────────────────────────────
  async loadCfgFile() {
    if (!this.cfgFilename) return;
    this.cfgData = null;
    this.cfgMsg = '';
    try {
      const r = await fetch(`/api/configs/${this.cfgFilename}`);
      if (!r.ok) throw new Error(await r.text());
      this.cfgData = await r.json();
    } catch (e) {
      this.cfgMsg = '读取失败：' + e.message;
      this.cfgMsgOk = false;
    }
  },

  async saveCfgFile() {
    if (!this.cfgFilename || !this.cfgData) return;
    this.cfgSaving = true;
    this.cfgMsg = '';
    try {
      const r = await fetch(`/api/configs/${this.cfgFilename}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.cfgData),
      });
      if (!r.ok) throw new Error(await r.text());
      this.cfgMsg = `✓ ${this.cfgFilename.replace(/\.yaml$/, '')} 已保存`;
      this.cfgMsgOk = true;
    } catch (e) {
      this.cfgMsg = '保存失败：' + e.message;
      this.cfgMsgOk = false;
    } finally {
      this.cfgSaving = false;
    }
  },

  async setCfgType(t) {
    if (!this.cfgData) return;
    this.cfgData.type = t;
    try {
      const r = await fetch(`/api/configs/defaults/${t}`);
      const d = await r.json();
      Object.assign(this.cfgData.test, {
        cmd: d.cmd,
        framework: d.framework,
        dir: d.dir,
        cmd_dir: d.cmd_dir || '',
        stack_filter: d.stack_filter || '',
      });
    } catch (e) { /* 保留现有值 */ }
  },

  async createCfgFile() {
    const raw = this.cfgNewName.trim().replace(/\.yaml$/i, '') || 'new';
    const name = raw + '.yaml';
    this.cfgMsg = '';
    let testDefaults = { cmd: 'pytest tests/ -x -q', framework: 'pytest', dir: 'tests/', cmd_dir: '', stack_filter: '' };
    try {
      const dr = await fetch(`/api/configs/defaults/${this.cfgNewType}`);
      testDefaults = await dr.json();
    } catch (e) {}

    const body = {
      type: this.cfgNewType,
      git: { repo_url: '', clone_base_dir: 'D:\\fixRepo', remote: 'origin', base_branch: 'main', github_token: '' },
      test: testDefaults,
    };
    try {
      const r = await fetch(`/api/configs?filename=${encodeURIComponent(name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(await r.text());
      this.cfgMsg = `✓ 已创建：${raw}`;
      this.cfgMsgOk = true;
      this.cfgShowNew = false;
      this.cfgNewName = '';
      this.cfgNewType = 'python';
      await this.loadConfigs();
      this.cfgFilename = name;
      await this.loadCfgFile();
    } catch (e) {
      this.cfgMsg = '创建失败：' + e.message;
      this.cfgMsgOk = false;
    }
  },
};
