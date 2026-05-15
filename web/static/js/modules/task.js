/**
 * task.js — 新建任务模块
 * 负责：submit / clearLogs / _startStream (SSE 实时日志)
 */
window._AppModules = window._AppModules || {};

window._AppModules.task = {
  selectedConfig: '',
  inputMode: 'text',
  errorText: '',
  uploadedFile: null,
  submitting: false,
  submitError: '',
  currentJob: null,
  logs: [],
  autoScroll: true,

  clearLogs() {
    this.logs = [];
    this.currentJob = null;
    this.submitting = false;
    this.submitError = '';
  },

  async submit() {
    this.submitError = '';
    if (!this.selectedConfig) { this.submitError = '请选择配置文件'; return; }
    if (this.inputMode === 'text' && !this.errorText.trim()) { this.submitError = '请输入报错信息'; return; }
    if (this.inputMode === 'file' && !this.uploadedFile) { this.submitError = '请选择日志文件'; return; }

    this.submitting = true;
    this.logs = [];
    this.currentJob = null;

    const fd = new FormData();
    fd.append('config_path', this.selectedConfig);
    if (this.inputMode === 'file') {
      fd.append('log_file', this.uploadedFile);
    } else {
      fd.append('error_text', this.errorText);
    }

    try {
      const r = await fetch('/api/jobs', { method: 'POST', body: fd });
      if (!r.ok) {
        const err = await r.json();
        this.submitError = err.detail || '提交失败';
        this.submitting = false;
        return;
      }
      const data = await r.json();
      this.currentJob = { id: data.id, status: 'running', branch: '', pr_url: '', error_msg: '', duration_s: null };
      this._startTimer();
      this._startStream(data.id);
    } catch (e) {
      this.submitError = '网络错误：' + e.message;
      this.submitting = false;
    }
  },

  _startStream(jobId) {
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.onmessage = (e) => {
      this.logs.push(e.data);
      this._touchActivity();
      if (this.autoScroll) {
        this.$nextTick(() => {
          const el = this.$refs.logBox;
          if (el) el.scrollTop = el.scrollHeight;
        });
      }
    };
    es.addEventListener('done', async () => {
      es.close();
      this.submitting = false;
      const r = await fetch(`/api/jobs/${jobId}`);
      this.currentJob = await r.json();
      this._stopTimer(this.currentJob.duration_s);
      this.loadJobs();
      this.loadReports();
    });
    es.onerror = () => {
      es.close();
      this.submitting = false;
      this._stopTimer(null);
    };
  },
};
