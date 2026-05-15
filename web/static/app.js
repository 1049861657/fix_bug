/**
 * app.js — Alpine.js 根组件入口
 *
 * 将各模块（timer / api / task / config / modal）的状态与方法
 * 展开合并为单一 Alpine data 对象，保持各模块独立可维护。
 */
function app() {
  const m = window._AppModules;
  return {
    // ── 全局 Tab 状态 ─────────────────────────────────────────
    tab: 'new',

    // ── 各模块展开 ────────────────────────────────────────────
    ...m.timer,
    ...m.api,
    ...m.task,
    ...m.config,
    ...m.modal,

    // ── 初始化 ────────────────────────────────────────────────
    async init() {
      await Promise.all([
        this.loadConfigs(),
        this.loadJobs(),
        this.loadReports(),
        this.loadAiderCfg(),
      ]);
    },
  };
}
