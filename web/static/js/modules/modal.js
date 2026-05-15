/**
 * modal.js — Modal 弹窗模块
 * 负责：日志查看 / 报告查看
 */
window._AppModules = window._AppModules || {};

window._AppModules.modal = {
  modal: { open: false, title: '', mode: 'log', lines: [], html: '' },

  async viewJobLogs(job) {
    const r = await fetch(`/api/jobs/${job.id}/logs`);
    const data = await r.json();
    this.modal = {
      open: true,
      title: `日志 · ${job.id.slice(0, 8)}…  [${job.status}]  ${job.created_at.replace('T', ' ')}`,
      mode: 'log',
      lines: data.lines,
      html: '',
    };
  },

  async viewReport(reportId) {
    const r = await fetch(`/api/reports/${reportId}`);
    const data = await r.json();
    this.modal = {
      open: true,
      title: `报告 · ${reportId}`,
      mode: 'report',
      lines: [],
      html: marked.parse(data.content),
    };
  },
};
