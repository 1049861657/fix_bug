/**
 * api.js — 通用数据加载与 Tab 切换模块
 * 负责：loadConfigs / loadJobs / loadReports / switchHistory / switchConfig
 */
window._AppModules = window._AppModules || {};

window._AppModules.api = {
  configs: [],
  jobs: [],
  reports: [],

  async loadConfigs() {
    const r = await fetch('/api/configs');
    this.configs = await r.json();
    if (this.configs.length) {
      this.selectedConfig = this.configs[0].path;
      if (!this.cfgFilename) this.cfgFilename = this.configs[0].path;
    }
  },

  async loadJobs() {
    const r = await fetch('/api/jobs');
    this.jobs = await r.json();
  },

  async loadReports() {
    const r = await fetch('/api/reports');
    this.reports = await r.json();
  },

  switchHistory() {
    this.tab = 'history';
    this.loadJobs();
    this.loadReports();
  },

  async switchConfig() {
    this.tab = 'config';
    await Promise.all([this.loadAiderCfg(), this.loadCfgFile()]);
  },
};
