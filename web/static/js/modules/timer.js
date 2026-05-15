/**
 * timer.js — 计时器与工具函数模块
 * 挂载到 window._AppModules.timer，由 app.js 展开合并
 */
window._AppModules = window._AppModules || {};

window._AppModules.timer = {
  elapsedStr: '0s',
  _timerStart: null,
  _timerInterval: null,
  lastActivityMs: null,
  lastActivityStr: '',
  _activityInterval: null,

  fmtDuration(secs) {
    if (secs == null) return '—';
    const s = Math.floor(secs);
    return s >= 60
      ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
      : `${s}s`;
  },

  _startTimer() {
    this._timerStart = Date.now();
    this.elapsedStr = '0s';
    this._timerInterval = setInterval(() => {
      const s = Math.floor((Date.now() - this._timerStart) / 1000);
      this.elapsedStr = this.fmtDuration(s);
    }, 1000);
    this.lastActivityMs = Date.now();
    this.lastActivityStr = '刚刚';
    this._activityInterval = setInterval(() => {
      if (!this.lastActivityMs) return;
      const s = Math.floor((Date.now() - this.lastActivityMs) / 1000);
      if (s < 5) this.lastActivityStr = '刚刚';
      else if (s < 60) this.lastActivityStr = `${s}s 前`;
      else this.lastActivityStr = `${Math.floor(s / 60)}m ${s % 60}s 前`;
    }, 1000);
  },

  _stopTimer(durationS) {
    clearInterval(this._timerInterval);
    clearInterval(this._activityInterval);
    this._timerInterval = this._activityInterval = null;
    this.lastActivityMs = null;
    this.lastActivityStr = '';
    this.elapsedStr = durationS != null ? this.fmtDuration(durationS) : this.elapsedStr;
  },

  _touchActivity() {
    this.lastActivityMs = Date.now();
    this.lastActivityStr = '刚刚';
  },
};
