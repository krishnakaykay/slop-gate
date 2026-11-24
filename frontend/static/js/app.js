// Slop Gate Frontend — Live FastAPI + EventSource SSE client implementing approved UX

const state = {
  stage: 'upload',           // 'upload' | 'waiting_intent' | 'report' | 'prep' | 'readthrough' | 'signoff'
  health: { has_live_llm: false, model_reasoning: 'gemini-3.1-pro-preview', model_fast: 'gemini-3-flash-preview', beta_code_required: false, daily_run_limit: 15 },
  apiKeyOverride: '',
  betaCode: sessionStorage.getItem('slop_beta_code') || '',
  modelReasoning: '',
  modelFast: '',
  samples: [],
  busy: false,
  lastTrackedStage: null,

  // 1-Click Feedback Capture
  feedback: {
    inlineIdByStage: {},     // stage -> feedback_id
    inlineRatingByStage: {}, // stage -> 'up' | 'down'
    inlineTagsByStage: {},   // stage -> Set<string>
    inlineCommentByStage: {},// stage -> string
    inlineExpanded: {},      // stage -> bool
    modalRating: 'up',
    modalTags: new Set(),
    modalFeedbackId: null,
  },

  // Active Document Session
  session: null,             // DocumentPreScanResponse
  docFormat: 'slide_deck',
  docPurpose: 'decide',
  targetPersona: 'leadership',
  customAudience: '',

  // Pre-Flight Run & Intent Wait
  runId: null,
  eventSource: null,
  streamStages: { polish: false, ghost: false, pass2: false },
  backendComplete: false,
  backendError: null,
  creatorIntent: '',
  intentSubmitted: false,
  report: null,              // Gate1Report

  // Gate 1 Triage UI
  leftTab: 'issues',         // 'issues' | 'mirror' | 'pages'
  polishOpen: false,
  selectedIssueId: null,
  activeSinglePage: 1,
  showExtractedText: false,
  intentionalPromptId: null,
  intentionalDraft: '',

  // Gate 2: Meeting Q&A Prep
  gate2: null,               // Gate2StateResponse
  prepIndex: 0,
  prepDrafts: {},            // question_id -> current unsaved textarea text
  prepInspectPage: null,
  prepDimmed: false,
  prepPinned: false,
  prepPasteHint: '',
  prepInSessionClip: '',
  prepBusy: false,

  // Final Read-Through & Sign-Off
  readCurrentPage: 1,
  reviewedPages: new Set(),
  ownerName: '',
  stampScope: 'all',         // 'all' | 'cover'
  stampResult: null,
};

const $ = (id) => document.getElementById(id);
window.$ = $;
window.state = state;

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => t.classList.add('hidden'), 3800);
}
window.showToast = showToast;
window._goStage = (stage) => { state.stage = stage; render(); };
window._triggerFileInput = (id) => { $(id)?.click(); };
window._returnToPreFlightPage = (p) => {
  state.stage = 'report';
  state.selectedIssueId = null;
  state.activeSinglePage = p;
  render();
};
window._warnIncompletePrep = () => {
  showToast(`Complete all ${state.gate2?.total_count || 0} Q&A Prep cards to begin Final Read-Through.`);
};
window._resumeReadThrough = () => {
  state.stage = 'readthrough';
  window.jumpNextUnreviewed();
};

function apiHeaders(extra = {}) {
  const h = { ...extra };
  if (state.apiKeyOverride.trim()) h['X-Gemini-Api-Key'] = state.apiKeyOverride.trim();
  if (state.betaCode.trim()) h['X-Beta-Code'] = state.betaCode.trim();
  return h;
}

const FEEDBACK_TAGS = [
  'Spot-on catch',
  'False alarm',
  'Q&A felt useful',
  'Too slow',
  'Confusing UI',
  'Bug',
];

function feedbackContext() {
  return {
    doc_format: state.docFormat,
    doc_purpose: state.docPurpose,
    target_persona: state.targetPersona,
    page_count: state.session?.page_count || 0,
    verdict: state.report?.verdict || '',
    mode: state.report?.mode || (state.health.has_live_llm || state.apiKeyOverride ? 'live_gemini' : 'local_demo'),
  };
}

function trackEvent(event, payload = {}, severity = 'INFO') {
  try {
    fetch('/api/telemetry/event', {
      method: 'POST',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event,
        severity,
        session_id: state.session?.session_id || null,
        revision: state.session?.revision || null,
        stage: state.stage,
        payload,
      }),
    }).catch(() => {});
  } catch {}
}

// Capture uncaught browser errors & rejected promises into Cloud Logging
window.addEventListener('error', (ev) => {
  trackEvent('client_js_error', {
    message: String(ev.message || 'Unknown error').slice(0, 400),
    filename: String(ev.filename || '').slice(0, 160),
    lineno: ev.lineno || 0,
    colno: ev.colno || 0,
  }, 'ERROR');
});
window.addEventListener('unhandledrejection', (ev) => {
  const reason = ev.reason?.message || String(ev.reason || 'Unhandled promise rejection');
  trackEvent('client_unhandled_rejection', { message: String(reason).slice(0, 400) }, 'ERROR');
});

async function apiJson(url, opts = {}) {
  const res = await fetch(url, { ...opts, headers: apiHeaders(opts.headers || {}) });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {}
    if (res.status === 401 && state.health.beta_code_required && !state.apiKeyOverride.trim()) {
      $('betaModal')?.classList.remove('hidden');
    }
    throw new Error(detail);
  }
  return res.json();
}

// =============================================================================
// INIT & SETTINGS
// =============================================================================
async function init() {
  try {
    state.health = await apiJson('/api/health');
    state.modelReasoning = state.health.model_reasoning;
    state.modelFast = state.health.model_fast;
  } catch (e) {
    showToast('Could not reach backend /api/health: ' + e.message);
  }
  try {
    state.samples = await apiJson('/api/samples');
  } catch {}
  updateModeBadge();
  bindGlobalControls();
  if (state.health.beta_code_required && !state.betaCode && !state.apiKeyOverride) {
    $('betaModal')?.classList.remove('hidden');
  }
  trackEvent('page_loaded', {
    viewport_w: window.innerWidth,
    viewport_h: window.innerHeight,
    has_live_llm: Boolean(state.health.has_live_llm),
  });
  render();
}

function updateModeBadge() {
  const live = Boolean(state.health.has_live_llm || state.apiKeyOverride.trim());
  const badge = $('modeBadge');
  badge.textContent = live ? `Live Gemini (${state.modelReasoning || state.health.model_reasoning})` : 'Local Demo Mode (Add Key for Gemini)';
  badge.className = live ? 'pill pill-ready' : 'pill pill-muted';
}

function bindGlobalControls() {
  $('btnTheme').onclick = () => {
    const html = document.documentElement;
    html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
    trackEvent('theme_toggled', { theme: html.dataset.theme });
  };

  // Feedback modal controls
  const openFeedbackModal = (defaultRating = null) => {
    if (defaultRating) state.feedback.modalRating = defaultRating;
    state.feedback.modalFeedbackId = state.feedback.inlineIdByStage[state.stage] || null;
    syncFeedbackModalUI();
    $('feedbackModal').classList.remove('hidden');
  };
  window._openFeedbackModal = openFeedbackModal;
  const syncFeedbackModalUI = () => {
    $('fbRateUp')?.classList.toggle('active', state.feedback.modalRating === 'up');
    $('fbRateDown')?.classList.toggle('active', state.feedback.modalRating === 'down');
    const tagsEl = $('fbModalTags');
    if (tagsEl) {
      tagsEl.innerHTML = FEEDBACK_TAGS.map(t => `
        <button type="button" class="choice-pill ${state.feedback.modalTags.has(t) ? 'active' : ''}"
                onclick="window._toggleModalFeedbackTag('${esc(t)}')">${esc(t)}</button>
      `).join('');
    }
  };
  window._modalFeedbackRate = (rating) => {
    state.feedback.modalRating = rating;
    syncFeedbackModalUI();
  };
  window._toggleModalFeedbackTag = (tag) => {
    if (state.feedback.modalTags.has(tag)) state.feedback.modalTags.delete(tag);
    else state.feedback.modalTags.add(tag);
    syncFeedbackModalUI();
  };
  $('btnFeedback').onclick = () => openFeedbackModal();
  $('btnCloseFeedback').onclick = () => $('feedbackModal').classList.add('hidden');
  $('btnCancelFeedback').onclick = () => $('feedbackModal').classList.add('hidden');
  $('btnSendFeedback').onclick = async () => {
    const comment = ($('fbModalComment')?.value || '').trim();
    try {
      const resp = await apiJson('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          feedback_id: state.feedback.modalFeedbackId,
          session_id: state.session?.session_id || null,
          revision: state.session?.revision || null,
          stage: state.stage,
          rating: state.feedback.modalRating || 'note',
          tags: Array.from(state.feedback.modalTags),
          comment,
          context: feedbackContext(),
        }),
      });
      state.feedback.inlineIdByStage[state.stage] = resp.feedback_id;
      state.feedback.inlineRatingByStage[state.stage] = resp.rating;
      state.feedback.modalTags = new Set();
      if ($('fbModalComment')) $('fbModalComment').value = '';
      $('feedbackModal').classList.add('hidden');
      showToast('✓ Feedback saved — thank you!');
      render();
    } catch (e) {
      showToast('Could not send feedback: ' + e.message);
    }
  };

  // Beta invite code modal controls
  const unlockBeta = async () => {
    const code = ($('inpBetaCode')?.value || '').trim();
    const errEl = $('betaErrorMsg');
    if (!code) {
      if (errEl) { errEl.textContent = 'Enter your beta invite code.'; errEl.style.display = 'block'; }
      return;
    }
    try {
      await apiJson('/api/beta/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      state.betaCode = code;
      sessionStorage.setItem('slop_beta_code', code);
      if (errEl) errEl.style.display = 'none';
      $('betaModal').classList.add('hidden');
      showToast('✓ Beta access unlocked!');
    } catch (e) {
      if (errEl) { errEl.textContent = e.message; errEl.style.display = 'block'; }
    }
  };
  $('btnUnlockBeta').onclick = unlockBeta;
  $('inpBetaCode').onkeydown = (e) => { if (e.key === 'Enter') unlockBeta(); };
  $('btnBetaUseOwnKey').onclick = () => {
    $('betaModal').classList.add('hidden');
    $('settingsModal').classList.remove('hidden');
  };

  $('btnSettings').onclick = () => {
    $('inpApiKey').value = state.apiKeyOverride;
    $('inpModelReasoning').value = state.modelReasoning;
    $('inpModelFast').value = state.modelFast;
    $('settingsModal').classList.remove('hidden');
  };
  $('btnCloseSettings').onclick = () => $('settingsModal').classList.add('hidden');
  $('btnClearKey').onclick = () => {
    state.apiKeyOverride = '';
    $('inpApiKey').value = '';
    updateModeBadge();
    showToast('API key override cleared.');
  };
  $('btnFetchModels').onclick = async () => {
    const key = $('inpApiKey').value.trim();
    const st = $('modelsFetchStatus');
    st.textContent = 'Querying v1beta models…';
    try {
      const res = await fetch('/api/models', { headers: key ? { 'X-Gemini-Api-Key': key } : {} });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      const list = $('geminiModelsList');
      list.innerHTML = (data.models || []).map(m => `<option value="${esc(m)}"></option>`).join('');
      st.textContent = `Found ${data.models.length} models (click inputs for dropdown)`;
    } catch (e) {
      st.textContent = e.message;
    }
  };
  $('btnSaveSettings').onclick = () => {
    state.apiKeyOverride = $('inpApiKey').value.trim();
    state.modelReasoning = $('inpModelReasoning').value.trim() || state.health.model_reasoning;
    state.modelFast = $('inpModelFast').value.trim() || state.health.model_fast;
    updateModeBadge();
    $('settingsModal').classList.add('hidden');
    showToast(state.apiKeyOverride ? 'Live Gemini key configured for this tab.' : 'Settings updated.');
  };

  $('fileInputMain').onchange = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (f) await uploadNewPdf(f);
  };
  $('fileInputRev').onchange = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (f) await uploadRevisionPdf(f);
  };

  document.addEventListener('keydown', (e) => {
    const tag = (e.target?.tagName || '').toLowerCase();
    if (e.key === 'Escape') {
      $('settingsModal').classList.add('hidden');
      $('feedbackModal')?.classList.add('hidden');
      if (state.intentionalPromptId) { state.intentionalPromptId = null; render(); }
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      if (state.stage === 'upload' && state.session && !state.busy) { e.preventDefault(); startPreFlight(); }
      else if (state.stage === 'waiting_intent') { e.preventDefault(); submitCreatorIntent(); }
      else if (state.stage === 'prep' && state.gate2 && !state.prepBusy) {
        e.preventDefault();
        const q = state.gate2.questions[state.prepIndex];
        if (q) window.submitPrepAnswer(q.id);
      }
      return;
    }
    if (tag === 'textarea' || tag === 'input') return;
    if (state.stage === 'readthrough') {
      if (e.key === 'ArrowRight') { e.preventDefault(); stepReadPage(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); stepReadPage(-1); }
    } else if (state.stage === 'report' && state.report) {
      const issues = state.report.issues || [];
      const idx = issues.findIndex(i => i.id === state.selectedIssueId);
      if ((e.key === 'j' || e.key === 'J') && issues.length) {
        const nxt = issues[(idx + 1) % issues.length];
        state.selectedIssueId = nxt.id; state.activeSinglePage = nxt.pages[0] || 1; render();
      } else if ((e.key === 'k' || e.key === 'K') && issues.length) {
        const prv = issues[(idx - 1 + issues.length) % issues.length];
        state.selectedIssueId = prv.id; state.activeSinglePage = prv.pages[0] || 1; render();
      } else if (e.key === 'ArrowRight') {
        state.selectedIssueId = null;
        state.activeSinglePage = Math.min(state.session.page_count, state.activeSinglePage + 1);
        render();
      } else if (e.key === 'ArrowLeft') {
        state.selectedIssueId = null;
        state.activeSinglePage = Math.max(1, state.activeSinglePage - 1);
        render();
      }
    }
  });
}

window.appReset = () => {
  closeSSE();
  state.stage = 'upload';
  state.session = null;
  state.report = null;
  state.runId = null;
  state.creatorIntent = '';
  state.intentSubmitted = false;
  state.stampResult = null;
  render();
};

function closeSSE() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

// =============================================================================
// API ACTIONS
// =============================================================================
async function uploadNewPdf(file) {
  state.busy = true;
  render();
  try {
    const fd = new FormData();
    fd.append('file', file);
    const data = await apiJson('/api/documents', { method: 'POST', body: fd });
    applyLoadedSession(data);
  } catch (e) {
    showToast('Upload failed: ' + e.message);
  } finally {
    state.busy = false;
    render();
  }
}

window.loadSample = async (sampleId) => {
  const meta = state.samples.find(s => s.id === sampleId);
  state.busy = true;
  render();
  try {
    const data = await apiJson(`/api/documents/sample/${encodeURIComponent(sampleId)}`, { method: 'POST' });
    applyLoadedSession(data, meta);
  } catch (e) {
    showToast('Could not load sample: ' + e.message);
  } finally {
    state.busy = false;
    render();
  }
};

function applyLoadedSession(data, sampleMeta = null) {
  closeSSE();
  state.session = data;
  state.docFormat = sampleMeta?.suggested_format || data.detected_format;
  state.docPurpose = sampleMeta?.suggested_purpose || 'decide';
  state.targetPersona = sampleMeta?.suggested_persona || 'leadership';
  state.report = null;
  state.runId = null;
  state.creatorIntent = '';
  state.intentSubmitted = false;
  state.gate2 = null;
  state.prepIndex = 0;
  state.prepDrafts = {};
  state.prepInspectPage = null;
  state.prepPasteHint = '';
  state.reviewedPages = new Set();
  state.readCurrentPage = 1;
  state.stampResult = null;
  state.feedback.inlineIdByStage = {};
  state.feedback.inlineRatingByStage = {};
  state.feedback.inlineTagsByStage = {};
  state.feedback.inlineCommentByStage = {};
  state.feedback.inlineExpanded = {};
  state.stage = 'upload';
}

async function uploadRevisionPdf(file) {
  if (!state.session) return;
  state.busy = true;
  render();
  try {
    const fd = new FormData();
    fd.append('file', file);
    const data = await apiJson(`/api/documents/${state.session.session_id}/revisions`, { method: 'POST', body: fd });
    state.session = data;
    state.stampResult = null;
    // Fetch preserved read-through state from server
    const rt = await apiJson(`/api/sessions/${data.session_id}/readthrough?revision=${data.revision}`);
    state.reviewedPages = new Set(rt.reviewed_pages || []);
    const diff = data.revision_diff;
    if (diff) {
      showToast(`v${data.revision} uploaded · ${diff.unchanged_pages.length} unchanged pages preserved · Re-running Pre-Flight…`);
    }
    // Re-run Pre-Flight automatically keeping current Format/Purpose/Persona & Intent!
    await startPreFlight(true);
  } catch (e) {
    showToast('Revision upload failed: ' + e.message);
    state.busy = false;
    render();
  }
}

window.startPreFlight = async (isRevisionRerun = false) => {
  if (!state.session) return;
  closeSSE();
  state.busy = false;
  state.streamStages = { polish: false, ghost: false, pass2: false };
  state.backendComplete = false;
  state.backendError = null;
  state.report = null;
  state.intentionalPromptId = null;
  if (!isRevisionRerun) {
    state.intentSubmitted = false;
    state.stage = 'waiting_intent';
  } else {
    state.intentSubmitted = true;
    state.stage = 'waiting_intent';
  }
  render();

  try {
    const created = await apiJson(`/api/sessions/${state.session.session_id}/gate1/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: state.session.revision,
        doc_format: state.docFormat,
        doc_purpose: state.docPurpose,
        target_persona: state.targetPersona,
        custom_audience: state.customAudience,
        creator_intent: state.creatorIntent,
        model_reasoning: state.modelReasoning || undefined,
        model_fast: state.modelFast || undefined,
      }),
    });
    state.runId = created.run_id;

    // Native GET EventSource SSE stream!
    const es = new EventSource(created.events_url);
    state.eventSource = es;

    es.addEventListener('stage', (ev) => {
      const payload = JSON.parse(ev.data);
      if (payload.stage === 'polish_ready') state.streamStages.polish = true;
      render();
    });

    es.addEventListener('ghost_deck', () => {
      state.streamStages.ghost = true;
      render();
    });

    es.addEventListener('complete', (ev) => {
      const payload = JSON.parse(ev.data);
      state.streamStages.polish = true;
      state.streamStages.ghost = true;
      state.streamStages.pass2 = true;
      state.backendComplete = true;
      state.report = payload.report;
      state.selectedIssueId = state.report.issues?.[0]?.id || null;
      state.activeSinglePage = state.report.issues?.[0]?.pages?.[0] || 1;
      closeSSE();
      // WAIT for user to finish typing their 1-sentence intent unless already submitted!
      if (state.intentSubmitted) {
        enterReportView();
      } else {
        render();
      }
    });

    es.addEventListener('error', (ev) => {
      let msg = 'Pre-Flight check failed.';
      try {
        if (ev.data) msg = JSON.parse(ev.data).error || msg;
      } catch {}
      if (!state.backendComplete) {
        state.backendError = msg;
        closeSSE();
        showToast(msg);
        render();
      }
    });
  } catch (e) {
    state.backendError = e.message;
    showToast('Failed to start Pre-Flight: ' + e.message);
    render();
  }
};

window.submitCreatorIntent = async () => {
  const txt = (state.creatorIntent || '').trim();
  if (!txt) {
    showToast('Jot 1 quick sentence on your intended decision or takeaway before viewing results.');
    $('intentBox')?.focus();
    return;
  }
  state.intentSubmitted = true;
  if (state.runId && state.session) {
    try {
      const resp = await apiJson(`/api/sessions/${state.session.session_id}/gate1/runs/${state.runId}/intent`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ creator_intent: txt }),
      });
      if (resp.report) state.report = resp.report;
    } catch {}
  }
  if (state.backendComplete && state.report) {
    enterReportView();
  } else {
    showToast('✓ Your intent captured — opening Pre-Flight report as soon as analysis finishes…');
    render();
  }
};

function enterReportView() {
  state.stage = 'report';
  state.leftTab = (state.report?.issues?.length || 0) > 0 ? 'issues' : 'mirror';
  render();
}

window.setDisposition = async (issueId, status, note = '') => {
  if (!state.session || !state.report) return;
  try {
    const updated = await apiJson(
      `/api/sessions/${state.session.session_id}/gate1/runs/${state.report.run_id}/issues/${issueId}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, note }),
      }
    );
    state.report = updated;
    state.intentionalPromptId = null;
    state.intentionalDraft = '';
    render();
  } catch (e) {
    showToast(e.message);
  }
};

window.handleIntentionalClick = (issueId, severity, currentDisp) => {
  if (currentDisp === 'intentional') {
    window.setDisposition(issueId, 'clear');
    return;
  }
  if (severity === 'critical') {
    state.intentionalPromptId = issueId;
    state.intentionalDraft = '';
    render();
    setTimeout(() => $('intentionalInput')?.focus(), 20);
  } else {
    window.setDisposition(issueId, 'intentional', 'Marked intentional');
  }
};

window.confirmCriticalIntentional = (issueId) => {
  const reason = (state.intentionalDraft || '').trim();
  if (reason.length < 5) {
    showToast('Add a brief 1-line reason why this Critical flag is intentional or a false alarm.');
    return;
  }
  window.setDisposition(issueId, 'intentional', reason);
};

window.startMeetingPrep = async () => {
  if (!state.session) return;
  state.prepBusy = true;
  state.stage = 'prep';
  state.prepInspectPage = null;
  state.prepDimmed = false;
  state.prepPasteHint = '';
  render();
  try {
    const res = await apiJson(`/api/sessions/${state.session.session_id}/gate2/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: state.session.revision,
        model_reasoning: state.modelReasoning || undefined,
        model_fast: state.modelFast || undefined,
      }),
    });
    state.gate2 = res;
    // Populate local drafts from any saved/preserved answers
    for (const q of res.questions) {
      const savedText = res.answers?.[q.id]?.answer_text || '';
      if (savedText && !state.prepDrafts[q.id]) {
        state.prepDrafts[q.id] = savedText;
      }
    }
    // Start on first unverified question if available
    const firstOpen = res.questions.findIndex(q => res.answers?.[q.id]?.status !== 'verified');
    state.prepIndex = firstOpen >= 0 ? firstOpen : 0;
    if (res.preserved_count > 0) {
      showToast(`✓ Page-Hash Continuity: ${res.preserved_count} of ${res.total_count} prep answers preserved!`);
    }
  } catch (e) {
    showToast(e.message);
    state.stage = 'report';
  } finally {
    state.prepBusy = false;
    render();
  }
};

window.submitPrepAnswer = async (qid) => {
  if (!state.session || !state.gate2) return;
  const text = (state.prepDrafts[qid] ?? state.gate2.answers?.[qid]?.answer_text ?? '').trim();
  state.prepBusy = true;
  state.prepPasteHint = '';
  render();
  try {
    const updated = await apiJson(`/api/sessions/${state.session.session_id}/gate2/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: state.session.revision,
        question_id: qid,
        answer_text: text,
        model_fast: state.modelFast || undefined,
      }),
    });
    state.gate2 = updated;
    state.prepDrafts[qid] = updated.answers?.[qid]?.answer_text ?? text;
    const ans = updated.answers?.[qid];
    if (ans?.status === 'verified') {
      showToast(`✓ Added to Meeting Q&A Prep Sheet (${updated.verified_count}/${updated.total_count})`);
      const nextIdx = updated.questions.findIndex(q => updated.answers?.[q.id]?.status !== 'verified');
      if (nextIdx >= 0 && nextIdx !== state.prepIndex) {
        setTimeout(() => {
          if (state.stage === 'prep') {
            state.prepIndex = nextIdx;
            state.prepInspectPage = null;
            state.prepDimmed = false;
            render();
          }
        }, 550);
      }
    }
  } catch (e) {
    showToast('Evaluation error: ' + e.message);
  } finally {
    state.prepBusy = false;
    render();
  }
};

window.enterReadThrough = async () => {
  if (!state.session) return;
  state.stage = 'readthrough';
  state.readCurrentPage = 1;
  state.reviewedPages.add(1);
  await syncReadThrough();
  render();
};

async function syncReadThrough() {
  if (!state.session) return;
  try {
    await apiJson(`/api/sessions/${state.session.session_id}/readthrough`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: state.session.revision,
        reviewed_pages: Array.from(state.reviewedPages),
      }),
    });
  } catch {}
}

window.stepReadPage = async (delta) => {
  if (!state.session) return;
  const total = state.session.page_count;
  const nxt = Math.min(total, Math.max(1, state.readCurrentPage + delta));
  state.readCurrentPage = nxt;
  state.reviewedPages.add(nxt);
  render();
  await syncReadThrough();
};

window.jumpReadPage = async (p) => {
  state.readCurrentPage = p;
  state.reviewedPages.add(p);
  render();
  await syncReadThrough();
};

window.jumpNextUnreviewed = async () => {
  const total = state.session.page_count;
  for (let p = 1; p <= total; p++) {
    if (!state.reviewedPages.has(p)) {
      await window.jumpReadPage(p);
      return;
    }
  }
};

window.stampAndDownload = async () => {
  if (!state.session) return;
  const name = (state.ownerName || '').trim();
  if (!name) {
    showToast('Enter your Owner Name before stamping the PDF.');
    $('ownerNameInput')?.focus();
    return;
  }
  state.busy = true;
  render();
  try {
    const res = await apiJson(`/api/sessions/${state.session.session_id}/stamp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        revision: state.session.revision,
        owner_name: name,
        scope: state.stampScope,
        reviewed_pages: Array.from(state.reviewedPages),
        enforce_all_reviewed: true,
      }),
    });
    state.stampResult = res;
    showToast(`✓ Stamped "${res.filename}" (${res.preferred_corner}) — downloading…`);
    const a = document.createElement('a');
    a.href = res.download_url;
    a.download = res.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    showToast('Stamping failed: ' + e.message);
  } finally {
    state.busy = false;
    render();
  }
};

// =============================================================================
// RENDERERS
// =============================================================================
function pageImgUrl(pageNum, thumb = false) {
  return `/api/documents/${state.session.session_id}/pages/${pageNum}/image?revision=${state.session.revision}&thumb=${thumb}`;
}

function unresolvedIssues() {
  return (state.report?.issues || []).filter(i => !i.disposition);
}

function renderBreadcrumb() {
  const steps = [
    ['upload', '1. Upload'],
    ['waiting_intent', '2. Intent'],
    ['report', '3. Pre-Flight'],
    ['prep', '4. Q&A Prep'],
    ['readthrough', '5. Final Read'],
    ['signoff', '6. Sign-Off'],
  ];
  $('stepBreadcrumb').innerHTML = steps
    .map(([k, label]) => `<span class="crumb ${state.stage === k ? 'active' : ''}">${label}</span>`)
    .join('');
}

function renderUpload() {
  const s = state.session;
  return `
    <div class="upload-shell">
      <div style="text-align:center; display:flex; flex-direction:column; gap:6px;">
        <h1 class="h1">Ship sharp documents you genuinely own.</h1>
        <p class="muted" style="margin:0;">Catch cross-page contradictions, see what a skimming leader absorbs, proof every page, and stamp your personal ownership.</p>
      </div>

      <div class="trust-strip">
        <span>ℹ</span>
        <span><strong>Public-safe demo:</strong> Only upload documents you would be comfortable pasting into ChatGPT or Gemini. Do not upload confidential enterprise documents.</span>
      </div>

      ${!s ? `
        <div id="dropzone" class="dropzone" onclick="window._triggerFileInput('fileInputMain')">
          <div style="font-size:28px; margin-bottom:8px;">📄</div>
          <div style="font-weight:700; font-size:15px;">${state.busy ? 'Scanning &amp; rendering PDF pages…' : 'Drop a PDF slide deck or narrative memo here, or click to browse'}</div>
          <div class="muted small" style="margin-top:6px;">Up to 40 pages · 25 MB max · Dual visual (PNG) + text inspection</div>
        </div>

        ${state.samples.length ? `
          <div style="display:flex; flex-direction:column; gap:8px;">
            <div class="label-caps">Or load a calibration sample PDF</div>
            <div class="sample-grid">
              ${state.samples.map(sm => `
                <button class="sample-btn" onclick="loadSample('${esc(sm.id)}')" ${state.busy ? 'disabled' : ''}>
                  <div style="display:flex; align-items:center; justify-content:space-between; gap:6px;">
                    <span style="font-weight:700; font-size:12.5px;">${esc(sm.label)}</span>
                  </div>
                  <span class="muted small">${esc(sm.description)}</span>
                </button>
              `).join('')}
            </div>
          </div>
        ` : ''}
      ` : `
        <div class="card card-pad" style="display:flex; flex-direction:column; gap:16px;">
          <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">
            <div>
              <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                <span class="h2">${esc(s.filename)}</span>
                <span class="pill pill-muted">${s.page_count} pages</span>
                <span class="pill pill-muted">Auto: ${s.detected_format === 'slide_deck' ? 'Slide Deck' : 'Narrative Memo'}</span>
              </div>
              <div class="muted small" style="margin-top:4px;">Confirm document format, purpose, and intended audience before running Pre-Flight.</div>
            </div>
            <button class="link-btn" onclick="appReset()">Change PDF</button>
          </div>

          <div class="thumb-preview-row">
            ${s.page_thumbnails.slice(0, 3).map((url, idx) => `
              <div class="thumb-mini">
                <img src="${url}" alt="Page ${idx + 1} preview" />
                <div class="small muted">Page ${idx + 1} · ${s.page_titles[idx]?.word_count || 0} words</div>
              </div>
            `).join('')}
          </div>

          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:14px; padding-top:12px; border-top:1px solid var(--border);">
            <div style="display:flex; flex-direction:column; gap:6px;">
              <div class="label-caps">Document Format</div>
              <div class="choice-group">
                ${choiceBtn('docFormat', 'slide_deck', 'Slide Deck')}
                ${choiceBtn('docFormat', 'narrative_memo', 'Narrative Memo')}
              </div>
            </div>
            <div style="display:flex; flex-direction:column; gap:6px;">
              <div class="label-caps">Document Purpose</div>
              <div class="choice-group">
                ${choiceBtn('docPurpose', 'decide', 'Decide / Approve')}
                ${choiceBtn('docPurpose', 'inform', 'Inform / Align')}
                ${choiceBtn('docPurpose', 'unblock', 'Unblock')}
              </div>
            </div>
            <div style="display:flex; flex-direction:column; gap:6px;">
              <div class="label-caps">Target Reader</div>
              <div class="choice-group">
                ${choiceBtn('targetPersona', 'leadership', 'Leadership')}
                ${choiceBtn('targetPersona', 'cross_org', 'Cross-Org Peer')}
                ${choiceBtn('targetPersona', 'custom', 'Custom')}
              </div>
              ${state.targetPersona === 'custom' ? `
                <input type="text" value="${esc(state.customAudience)}" oninput="window._setCustomAudience(this.value)" placeholder="e.g., CFO reviewing Q3 infra spend" style="margin-top:4px;" />
              ` : ''}
            </div>
          </div>

          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding-top:12px; border-top:1px solid var(--border);">
            <span class="muted small">Runs Ghost-Deck storyline check + multimodal contradiction &amp; chart audit</span>
            <button class="btn btn-primary" onclick="startPreFlight(false)">Run Pre-Flight Check (⌘↵)</button>
          </div>
        </div>
      `}
    </div>
  `;
}

function choiceBtn(field, val, label) {
  return `<button class="choice-pill ${state[field] === val ? 'active' : ''}" onclick="window._setChoice('${field}','${val}')">${label}</button>`;
}

window._setChoice = (f, v) => { state[f] = v; render(); };
window._setCustomAudience = (v) => { state.customAudience = v; };

function renderWaitingIntent() {
  const s = state.session;
  const done = state.backendComplete;
  return `
    <div style="max-width:960px; margin:16px auto; display:flex; flex-direction:column; gap:14px;">
      <div class="card sticky-bar" style="margin-bottom:0;">
        <div style="display:flex; align-items:center; gap:10px;">
          ${done
            ? '<span class="pill pill-ready">✓ Pre-Flight analysis complete</span>'
            : '<span class="pulse-dot"></span>'}
          <span style="font-size:13px; font-weight:600;">
            ${state.backendError
              ? `Error: ${esc(state.backendError)}`
              : done
                ? 'Results are ready — finish your 1-sentence intent below to view the report.'
                : `Analyzing ${s.page_count} pages in the background…`}
          </span>
        </div>
        ${state.backendError ? `<button class="btn btn-sm" onclick="startPreFlight(false)">Retry</button>` : '<span class="muted small">Waiting for your answer</span>'}
      </div>

      <div class="grid-2">
        <div class="card card-pad" style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; align-items:center; justify-content:space-between;">
            <span class="label-caps">Before You See AI Feedback</span>
            <span class="muted small">Diffs vs. 30s Skim</span>
          </div>
          <div class="h2">In 1 sentence, what decision or takeaway do you want your reader to leave with?</div>
          <textarea id="intentBox" rows="4" oninput="window._setIntent(this.value)" placeholder="State your core recommendation, ask, or takeaway in plain English…">${esc(state.creatorIntent)}</textarea>
          <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
            <span class="muted small">We hold AI output until you submit so it doesn't anchor your thinking.</span>
            <button class="btn btn-primary btn-sm" onclick="submitCreatorIntent()">
              ${done ? 'View Pre-Flight Results (⌘↵)' : (state.intentSubmitted ? '✓ Saved — Finishing…' : 'Lock In Intent (⌘↵)')}
            </button>
          </div>
        </div>

        <div class="card card-pad" style="display:flex; flex-direction:column; gap:10px;">
          <div class="label-caps">Background Pipeline Status</div>
          <div class="quote-box" style="display:flex; justify-content:space-between;">
            <span>1. Page visuals, text extraction &amp; Polish linters</span>
            <strong style="color:${state.streamStages.polish ? 'var(--success)' : 'var(--muted)'};">${state.streamStages.polish ? '✓ Done' : 'Running…'}</strong>
          </div>
          <div class="quote-box" style="display:flex; justify-content:space-between;">
            <span>2. Isolated title-only Ghost-Deck storyline</span>
            <strong style="color:${state.streamStages.ghost ? 'var(--success)' : 'var(--muted)'};">${state.streamStages.ghost ? '✓ Done' : 'Running…'}</strong>
          </div>
          <div class="quote-box" style="display:flex; justify-content:space-between;">
            <span>3. Cross-page numbers, dates &amp; chart audit</span>
            <strong style="color:${done ? 'var(--success)' : 'var(--muted)'};">${done ? '✓ Ready (held for you)' : 'Running…'}</strong>
          </div>
        </div>
      </div>
    </div>
  `;
}

window._setIntent = (v) => { state.creatorIntent = v; };

function renderReport() {
  const r = state.report;
  const s = state.session;
  const unres = unresolvedIssues();
  const unresCrit = unres.filter(i => i.severity === 'critical');
  const unresVer = unres.filter(i => i.severity === 'verify');
  const canProceed = unres.length === 0;

  let vClass = 'pill-ready';
  let vLabel = '✓ READY';
  if (r.verdict === 'NEEDS_REWORK') { vClass = 'pill-rework'; vLabel = '⊘ NEEDS REWORK'; }
  else if (unresCrit.length > 0) { vClass = 'pill-critical'; vLabel = `! FIX ${unresCrit.length} CRITICAL ISSUE${unresCrit.length > 1 ? 'S' : ''}`; }
  else if (unresVer.length > 0) { vClass = 'pill-verify'; vLabel = `▲ REVIEW ${unresVer.length} ITEM${unresVer.length > 1 ? 'S' : ''}`; }

  const selectedIssue = (r.issues || []).find(i => i.id === state.selectedIssueId) || null;

  return `
    <div>
      <div class="card sticky-bar">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <span class="pill ${vClass}">${vLabel}</span>
          <span style="font-weight:700;">${esc(s.filename)}</span>
          <span class="pill pill-muted mono">v${r.revision}</span>
          <span class="muted small">${r.doc_format === 'slide_deck' ? 'Slide Deck' : 'Memo'} · ${r.doc_purpose} · ${r.target_persona} · ${(r.latency_ms / 1000).toFixed(1)}s</span>
          ${r.mode === 'local_demo' ? '<span class="pill pill-verify">Local Demo Mode</span>' : ''}
        </div>
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <button class="btn btn-sm" onclick="window._triggerFileInput('fileInputRev')">↑ Re-upload v${r.revision + 1}</button>
          <button class="btn btn-sm ${canProceed ? 'btn-primary' : 'btn-ghost'}"
                  onclick="${canProceed ? 'startMeetingPrep()' : 'window._focusNextUnresolved()'}">
            ${canProceed ? '✓ Start Meeting Q&amp;A Prep →' : `Resolve ${unres.length} Issue${unres.length > 1 ? 's' : ''} to Start Q&amp;A`}
          </button>
        </div>
      </div>

      ${r.revision_diff ? `
        <div class="trust-strip" style="margin-bottom:12px; border-color:var(--success-border); background:var(--success-bg); color:var(--success);">
          <span>✓</span>
          <span><strong>v${r.revision_diff.from_revision} → v${r.revision_diff.to_revision} Page-Hash Diff:</strong> ${r.revision_diff.unchanged_pages.length} unchanged pages preserved · ${r.revision_diff.modified_pages.length} modified · ${r.revision_diff.inserted_pages.length} inserted.</span>
        </div>
      ` : ''}

      <div class="workspace-grid">
        <!-- LEFT TRIAGE RAIL -->
        <div class="rail">
          <div class="segmented" role="tablist">
            <button class="seg-btn ${state.leftTab === 'issues' ? 'active' : ''}" onclick="window._setLeftTab('issues')">Issues (${unres.length})</button>
            <button class="seg-btn ${state.leftTab === 'mirror' ? 'active' : ''}" onclick="window._setLeftTab('mirror')">Reader Mirror</button>
            <button class="seg-btn ${state.leftTab === 'pages' ? 'active' : ''}" onclick="window._setLeftTab('pages')">Pages (${s.page_count})</button>
          </div>

          ${state.leftTab === 'issues' ? renderIssuesList(r) : ''}
          ${state.leftTab === 'mirror' ? renderReaderMirror(r) : ''}
          ${state.leftTab === 'pages' ? renderPagesGrid(r) : ''}
        </div>

        <!-- RIGHT STICKY VISUAL EVIDENCE CANVAS -->
        <div class="card card-pad canvas-sticky desktop-only">
          ${renderEvidenceCanvas(selectedIssue, r)}
        </div>
      </div>

      <div style="margin-top:14px;">
        ${renderFeedbackStrip('report', 'How accurate was this Pre-Flight check?')}
      </div>
    </div>
  `;
}

window._setLeftTab = (t) => { state.leftTab = t; trackEvent('tab_switched', { tab: t }); render(); };
window._focusNextUnresolved = () => {
  const nxt = unresolvedIssues()[0];
  if (!nxt) return;
  state.leftTab = 'issues';
  state.selectedIssueId = nxt.id;
  state.activeSinglePage = nxt.pages[0] || 1;
  showToast('Resolve each non-Polish issue (Fix via v2, Intentional, or Ignore for now) before Final Read-Through.');
  render();
};

function renderIssuesList(r) {
  const cards = (r.issues || []).map(iss => {
    const isSel = state.selectedIssueId === iss.id;
    const isCrit = iss.severity === 'critical';
    const disp = iss.disposition;
    const isDual = iss.pages.length >= 2 && iss.pages[0] !== iss.pages[1];
    const pageTag = isDual ? `P${iss.pages[0]} ↔ P${iss.pages[1]}` : `P${iss.pages[0]}`;

    return `
      <div class="issue-card ${isSel ? 'selected' : ''} ${disp ? 'resolved' : ''}"
           onclick="window._selectIssue('${iss.id}', ${iss.pages[0] || 1})">
        <div class="issue-head">
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span class="pill ${isCrit ? 'pill-critical' : 'pill-verify'}" style="font-size:11px;">${isCrit ? '! CRITICAL' : '▲ VERIFY'}</span>
            <span class="muted small">${esc(iss.category.replace(/_/g, ' '))}</span>
            <span class="pill pill-muted mono" style="font-size:11px;">${pageTag}</span>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <button class="link-btn" onclick="event.stopPropagation(); handleIntentionalClick('${iss.id}','${iss.severity}','${disp?.status || ''}')">
              ${disp?.status === 'intentional' ? '✓ Intentional (Undo)' : 'Intentional'}
            </button>
            <button class="link-btn" onclick="event.stopPropagation(); setDisposition('${iss.id}','${disp?.status === 'ignored' ? 'clear' : 'ignored'}','Deferred for now')">
              ${disp?.status === 'ignored' ? '✓ Ignored (Undo)' : 'Ignore for now'}
            </button>
          </div>
        </div>

        <div class="issue-title">${esc(iss.title)}</div>
        <div class="muted small">${esc(iss.explanation)}</div>
        <div class="small" style="padding-top:6px; border-top:1px solid var(--border);">
          <strong>Fix:</strong> <span class="muted">${esc(iss.suggested_fix)}</span>
        </div>

        ${disp ? `
          <div class="quote-box"><strong>${disp.status === 'intentional' ? 'Intentional:' : 'Ignored for now:'}</strong> ${esc(disp.note)}</div>
        ` : ''}

        ${state.intentionalPromptId === iss.id ? `
          <div onclick="event.stopPropagation();" style="display:flex; flex-direction:column; gap:8px; padding:10px; background:var(--surface-2); border-radius:8px; border:1px solid var(--border);">
            <div class="small" style="font-weight:600;">Why is this Critical flag intentional (or a false alarm)?</div>
            <input id="intentionalInput" type="text" value="${esc(state.intentionalDraft)}"
                   oninput="window._setIntentionalDraft(this.value)"
                   onkeydown="if(event.key==='Enter') confirmCriticalIntentional('${iss.id}')"
                   placeholder="e.g., Slide 2 shows non-GAAP headline; Appendix shows GAAP" />
            <div style="display:flex; justify-content:flex-end; gap:8px;">
              <button class="btn btn-ghost btn-sm" onclick="window._cancelIntentional()">Cancel</button>
              <button class="btn btn-primary btn-sm" onclick="confirmCriticalIntentional('${iss.id}')">Mark Intentional</button>
            </div>
          </div>
        ` : ''}
      </div>
    `;
  }).join('');

  const polish = r.polish_tips || [];
  return `
    ${(r.issues || []).length === 0 ? `
      <div class="card card-pad" style="text-align:center;">
        <div style="font-weight:700; color:var(--success);">✓ Zero Critical or Verify issues detected!</div>
        <div class="muted small" style="margin-top:4px;">Your document is consistent and ready for Final Read-Through &amp; Owner Sign-Off.</div>
      </div>
    ` : cards}

    <div class="card" style="overflow:hidden;">
      <button onclick="window._togglePolish()" style="width:100%; border:none; background:transparent; color:var(--fg); padding:11px 14px; display:flex; align-items:center; justify-content:space-between; cursor:pointer; font-size:12.5px; font-weight:600;">
        <span>Polish Suggestions (${polish.length}) <span class="pill pill-muted" style="margin-left:6px; font-size:11px;">Non-blocking</span></span>
        <span>${state.polishOpen ? '▾' : '▸'}</span>
      </button>
      ${state.polishOpen ? `
        <div style="padding:0 14px 12px; display:flex; flex-direction:column; gap:8px; border-top:1px solid var(--border); padding-top:10px;">
          ${polish.length === 0 ? '<div class="muted small">No polish issues detected.</div>' : polish.map(t => `
            <div class="quote-box" style="cursor:pointer;" onclick="window._jumpCanvasPage(${t.page})">
              <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
                <strong style="color:var(--fg);">${esc(t.kind.replace(/_/g, ' '))} · Page ${t.page}</strong>
                <span class="mono">${esc(t.snippet)}</span>
              </div>
              <div>${esc(t.suggestion)}</div>
            </div>
          `).join('')}
        </div>
      ` : ''}
    </div>
    <div class="muted small">Shortcuts: <span class="mono">J</span>/<span class="mono">K</span> issues · <span class="mono">←</span>/<span class="mono">→</span> pages</div>
  `;
}

window._selectIssue = (id, p) => {
  state.selectedIssueId = id;
  state.activeSinglePage = p;
  const iss = (state.report?.issues || []).find(i => i.id === id);
  if (iss) {
    trackEvent('issue_selected', {
      issue_id: id,
      severity: iss.severity,
      category: iss.category,
      is_dual_compare: iss.pages.length >= 2 && iss.pages[0] !== iss.pages[1],
    });
  }
  render();
};
window._jumpCanvasPage = (p) => { state.selectedIssueId = null; state.activeSinglePage = p; render(); };
window._setIntentionalDraft = (v) => { state.intentionalDraft = v; };
window._cancelIntentional = () => { state.intentionalPromptId = null; render(); };
window._togglePolish = () => {
  state.polishOpen = !state.polishOpen;
  trackEvent('polish_drawer_toggled', { open: state.polishOpen });
  render();
};

function renderReaderMirror(r) {
  const gd = r.ghost_deck;
  return `
    <div class="card card-pad" style="display:flex; flex-direction:column; gap:10px;">
      <div class="label-caps">30-Second ${r.target_persona === 'leadership' ? 'Leadership' : 'Reader'} Skim</div>
      ${r.creator_intent ? `
        <div class="quote-box"><strong style="color:var(--fg);">Your Stated Intent:</strong> "${esc(r.creator_intent)}"</div>
      ` : ''}
      <div class="small"><strong>Perceived Purpose / Ask:</strong> <span class="muted">${esc(r.skim_30s.perceived_purpose_and_ask)}</span></div>
      <div class="small">
        <strong>What they'll remember:</strong>
        <ul style="margin:4px 0 0 18px; padding:0; color:var(--muted);">
          ${(r.skim_30s.remembered_takeaways || []).map(x => `<li>${esc(x)}</li>`).join('')}
        </ul>
      </div>
      ${(r.skim_30s.stall_points || []).length ? `
        <div class="small" style="padding-top:8px; border-top:1px solid var(--border);">
          <strong style="color:var(--warn);">Where they'll stall or push back:</strong>
          <ul style="margin:4px 0 0 18px; padding:0; color:var(--muted);">
            ${r.skim_30s.stall_points.map(x => `<li>${esc(x)}</li>`).join('')}
          </ul>
        </div>
      ` : ''}
    </div>

    ${gd ? `
      <div class="card card-pad" style="display:flex; flex-direction:column; gap:10px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="label-caps">Ghost-Deck Title Replay</span>
          <span class="small" style="font-weight:700; color:${gd.storyline_holds ? 'var(--success)' : 'var(--warn)'};">
            ${gd.storyline_holds ? '✓ Storyline holds' : '▲ Storyline gaps'}
          </span>
        </div>
        <div class="quote-box">${esc(gd.title_only_storyline)}</div>
        <div style="display:flex; flex-direction:column; gap:4px;">
          ${(gd.headings || []).map(h => `
            <button onclick="window._jumpCanvasPage(${h.page})" style="text-align:left; border:none; background:transparent; color:var(--fg); padding:5px 6px; border-radius:6px; cursor:pointer; display:flex; gap:8px; font-size:12px;">
              <span class="mono muted">P${h.page}</span>
              <span>${esc(h.text)}</span>
            </button>
          `).join('')}
        </div>
      </div>
    ` : ''}
  `;
}

function renderPagesGrid(r) {
  return `
    <div class="pages-grid">
      ${(r.pages || []).map(p => {
        const active = !state.selectedIssueId && state.activeSinglePage === p.page_number;
        const badge = p.status === 'critical'
          ? '<span style="color:var(--crit); font-weight:700;">! Critical</span>'
          : p.status === 'verify'
            ? '<span style="color:var(--warn); font-weight:700;">▲ Verify</span>'
            : '<span style="color:var(--success); font-weight:600;">✓ Clean</span>';
        return `
          <button class="page-tile ${active ? 'active' : ''}" onclick="window._jumpCanvasPage(${p.page_number})">
            <img src="${pageImgUrl(p.page_number, true)}" alt="Page ${p.page_number}" />
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <span class="mono" style="font-weight:700;">Page ${p.page_number}</span>
              ${badge}
            </div>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function renderEvidenceCanvas(selectedIssue, r) {
  // AUTO DUAL-PAGE COMPARE when a multi-page contradiction is selected!
  if (selectedIssue && selectedIssue.pages.length >= 2 && selectedIssue.pages[0] !== selectedIssue.pages[1]) {
    const [pA, pB] = selectedIssue.pages;
    return `
      <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:10px; border-bottom:1px solid var(--border); margin-bottom:12px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="pill pill-muted">Auto Dual-Page Compare</span>
          <strong class="small">Page ${pA} ↔ Page ${pB}</strong>
        </div>
        <span class="muted small">${esc(selectedIssue.category.replace(/_/g, ' '))}</span>
      </div>
      <div class="dual-compare">
        ${[pA, pB].map((p) => {
          const ev = (selectedIssue.evidence || []).find(e => e.page === p);
          return `
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div style="display:flex; justify-content:space-between; font-size:12px;">
                <strong>Page ${p}</strong>
                <button class="link-btn" onclick="window._jumpCanvasPage(${p})">Zoom single</button>
              </div>
              <div class="page-img-frame"><img src="${pageImgUrl(p, false)}" alt="Page ${p}" /></div>
              ${ev ? `<div class="quote-box"><strong>Quote (P${ev.page}):</strong> "${esc(ev.quote)}"</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  const p = selectedIssue ? (selectedIssue.pages[0] || 1) : state.activeSinglePage;
  const pageMeta = state.session.page_titles?.[p - 1];
  return `
    <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:10px; border-bottom:1px solid var(--border); margin-bottom:12px;">
      <strong>Page ${p} of ${state.session.page_count}</strong>
      <div style="display:flex; gap:6px;">
        <button class="btn btn-sm btn-ghost" onclick="window._jumpCanvasPage(${Math.max(1, p - 1)})">← Prev</button>
        <button class="btn btn-sm btn-ghost" onclick="window._jumpCanvasPage(${Math.min(state.session.page_count, p + 1)})">Next →</button>
      </div>
    </div>
    <div class="page-img-frame"><img src="${pageImgUrl(p, false)}" alt="Page ${p}" /></div>
    ${selectedIssue && selectedIssue.evidence?.length ? `
      <div style="display:flex; flex-direction:column; gap:6px; margin-top:10px;">
        ${selectedIssue.evidence.map(ev => `<div class="quote-box"><strong>Quote (P${ev.page}):</strong> "${esc(ev.quote)}"</div>`).join('')}
      </div>
    ` : ''}
    <div style="margin-top:10px; display:flex; justify-content:space-between; align-items:center;">
      <button class="link-btn" onclick="window._toggleExtracted()">${state.showExtractedText ? 'Hide extracted page text' : 'Read extracted page text (accessible)'}</button>
      <span class="muted small">${pageMeta?.word_count || 0} words</span>
    </div>
    ${state.showExtractedText ? `<div class="quote-box mono" style="margin-top:8px; max-height:160px; overflow:auto; white-space:pre-wrap;">${esc(pageMeta?.extracted_text || '')}</div>` : ''}
  `;
}

window._toggleExtracted = () => { state.showExtractedText = !state.showExtractedText; render(); };

// =============================================================================
// STAGE 4: MEETING Q&A PREP (HIGH-RELEVANCE GATE 2)
// =============================================================================
function renderPrep() {
  const g2 = state.gate2;
  if (!g2) {
    return `
      <div class="card card-pad" style="max-width:680px; margin:28px auto; text-align:center; display:flex; flex-direction:column; gap:10px; align-items:center;">
        <span class="pulse-dot"></span>
        <div class="h2">Preparing high-relevance Meeting Q&amp;A questions…</div>
        <div class="muted small">Selecting the 3–4 load-bearing assumptions, key charts, and late-section caveats from your document.</div>
      </div>
    `;
  }

  const qs = g2.questions;
  const q = qs[state.prepIndex] || qs[0];
  const ans = g2.answers?.[q.id] || { answer_text: '', status: 'idle', feedback: '' };
  const draft = state.prepDrafts[q.id] !== undefined ? state.prepDrafts[q.id] : (ans.answer_text || '');
  const inspecting = state.prepInspectPage;

  return `
    <div style="display:flex; flex-direction:column; gap:14px;">
      <div class="card sticky-bar" style="margin-bottom:0;">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <button class="link-btn" onclick="window._goStage('report')">← Back to Pre-Flight</button>
          <span class="h2">Meeting Q&amp;A Prep</span>
          <span class="pill ${g2.all_verified ? 'pill-ready' : 'pill-muted'}">Prep Sheet: ${g2.verified_count} / ${g2.total_count} ready</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <button class="btn btn-sm" onclick="window._triggerFileInput('fileInputRev')">↑ Re-upload v${state.session.revision + 1}</button>
          <button class="btn btn-sm ${g2.all_verified ? 'btn-primary' : 'btn-ghost'}"
                  onclick="${g2.all_verified ? 'enterReadThrough()' : 'window._warnIncompletePrep()'}">
            ${g2.all_verified ? '✓ Begin Final Read-Through →' : `Complete ${g2.total_count - g2.verified_count} More Card${g2.total_count - g2.verified_count > 1 ? 's' : ''}`}
          </button>
        </div>
      </div>

      ${g2.preserved_count > 0 ? `
        <div class="trust-strip" style="border-color:var(--success-border); background:var(--success-bg); color:var(--success);">
          <span>✓</span>
          <span><strong>Page-Hash Continuity:</strong> ${g2.preserved_count} of ${g2.total_count} verified answers preserved automatically on unchanged pages.</span>
        </div>
      ` : ''}

      <div class="prep-dots">
        ${qs.map((item, idx) => {
          const st = g2.answers?.[item.id]?.status;
          return `
            <button class="prep-dot-btn ${idx === state.prepIndex ? 'active' : ''}" onclick="window._selectPrepIndex(${idx})">
              <div style="display:flex; justify-content:space-between; font-size:12px;">
                <strong>Q${idx + 1}</strong>
                <span style="color:${st === 'verified' ? 'var(--success)' : 'var(--muted)'};">${st === 'verified' ? '✓' : (item.is_limitation ? '★' : '○')}</span>
              </div>
              <span class="muted small" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${esc(item.tag)}</span>
            </button>
          `;
        }).join('')}
      </div>

      <div class="${inspecting ? 'workspace-grid' : ''}" style="${inspecting ? 'grid-template-columns: minmax(0, 50%) minmax(0, 50%);' : 'max-width:780px; width:100%; margin:0 auto;'}">
        <!-- Question Card -->
        <div class="card card-pad" style="display:flex; flex-direction:column; gap:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <span class="pill pill-muted">Question ${state.prepIndex + 1} of ${qs.length} · ${esc(q.tag)}</span>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              ${q.pages.map(p => `
                <button class="btn btn-sm ${inspecting === p ? 'btn-primary' : 'btn-ghost'}" onclick="window._togglePrepInspect(${p})">
                  ${inspecting === p ? `Hide Page ${p}` : `Inspect Page ${p}`}
                </button>
              `).join('')}
            </div>
          </div>

          <div style="font-size:15.5px; font-weight:700; line-height:1.4;">${esc(q.question)}</div>

          <div style="display:flex; flex-direction:column; gap:8px;">
            <textarea id="prepTextarea" rows="4"
              onfocus="window._onPrepFocus(true)"
              onblur="window._onPrepFocus(false)"
              oncopy="window._capturePrepClip()"
              oncut="window._capturePrepClip()"
              onpaste="window._handleSmartPaste(event)"
              oninput="window._setPrepDraft('${q.id}', this.value)"
              placeholder="Jot 1–2 rough sentences in your own words — bullet fragments are great…">${esc(draft)}</textarea>

            ${state.prepPasteHint ? `<div class="quote-box">${esc(state.prepPasteHint)}</div>` : ''}

            ${ans.status === 'nudge' ? `
              <div class="quote-box" style="border-color:var(--warn-border); background:var(--warn-bg); color:var(--warn);">
                <strong>Quick nudge:</strong> ${esc(ans.feedback)}
              </div>
            ` : ''}

            ${ans.status === 'verified' ? `
              <div class="quote-box" style="border-color:var(--success-border); background:var(--success-bg); color:var(--success);">
                <strong>✓ Added to Prep Sheet:</strong> ${esc(ans.feedback)}
                ${ans.preserved_from_revision ? ` <span class="mono">(preserved from v${ans.preserved_from_revision})</span>` : ''}
              </div>
            ` : ''}
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; padding-top:8px; border-top:1px solid var(--border);">
            <span class="muted small">Rough notes in your own words · No copy-paste of long passages</span>
            <button class="btn btn-primary btn-sm" onclick="submitPrepAnswer('${q.id}')" ${state.prepBusy ? 'disabled' : ''}>
              ${state.prepBusy ? 'Checking…' : (ans.status === 'verified' ? 'Update Note (⌘↵)' : 'Save &amp; Verify (⌘↵)')}
            </button>
          </div>
        </div>

        <!-- On-Demand Slide Canvas (Hidden Until User Clicks Inspect Page N) -->
        ${inspecting ? `
          <div id="prepSlideCanvas" class="card card-pad ${state.prepDimmed && !state.prepPinned ? 'prep-canvas-dim' : 'prep-canvas-bright'}" style="display:flex; flex-direction:column; gap:10px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <strong class="small">Reference · Page ${inspecting}</strong>
              <div style="display:flex; gap:6px; align-items:center;">
                <button class="btn btn-sm ${state.prepPinned ? 'btn-primary' : 'btn-ghost'}" onclick="window._togglePrepPin()">
                  ${state.prepPinned ? '📌 Pinned (Bright)' : 'Pin Slide'}
                </button>
                <button class="btn btn-sm btn-ghost" onclick="window._togglePrepInspect(${inspecting})">✕</button>
              </div>
            </div>
            <div class="page-img-frame"><img src="${pageImgUrl(inspecting, false)}" alt="Reference Page ${inspecting}" /></div>
            <div class="muted small">${state.prepPinned ? 'Pinned — stays bright while typing.' : 'Softly dims while typing so you synthesize in your own words. Click Pin Slide to keep bright.'}</div>
          </div>
        ` : ''}
      </div>
    </div>
  `;
}

window._selectPrepIndex = (idx) => {
  state.prepIndex = idx;
  state.prepInspectPage = null;
  state.prepDimmed = false;
  state.prepPasteHint = '';
  render();
};
window._togglePrepInspect = (p) => {
  const opening = state.prepInspectPage !== p;
  state.prepInspectPage = opening ? p : null;
  state.prepDimmed = false;
  trackEvent('prep_slide_inspected', { page: p, open: opening });
  render();
};
window._togglePrepPin = () => {
  state.prepPinned = !state.prepPinned;
  state.prepDimmed = false;
  trackEvent('prep_slide_pinned', { pinned: state.prepPinned });
  render();
};
window._onPrepFocus = (focused) => {
  state.prepDimmed = focused && Boolean(state.prepInspectPage) && !state.prepPinned;
  const el = $('prepSlideCanvas');
  if (!el) return;
  el.classList.toggle('prep-canvas-dim', state.prepDimmed);
  el.classList.toggle('prep-canvas-bright', !state.prepDimmed);
};
window._setPrepDraft = (qid, val) => { state.prepDrafts[qid] = val; };
window._capturePrepClip = () => { state.prepInSessionClip = window.getSelection()?.toString() || ''; };
window._handleSmartPaste = (e) => {
  const pasted = (e.clipboardData || window.clipboardData)?.getData('text') || '';
  // Allow short pastes (<20 chars for exact numbers/acronyms) & internal in-session edits
  if (pasted.length < 20 || (state.prepInSessionClip && pasted.trim() === state.prepInSessionClip.trim())) {
    state.prepPasteHint = '';
    return;
  }
  e.preventDefault();
  trackEvent('prep_paste_blocked', { pasted_len: pasted.length });
  state.prepPasteHint = 'Jot it in your own quick words — this becomes your Meeting Q&A crib sheet (short exact numbers <20 chars can still be pasted).';
  render();
};

function renderReadThrough() {
  const s = state.session;
  const total = s.page_count;
  const cur = state.readCurrentPage;
  state.reviewedPages.add(cur);
  const doneCount = state.reviewedPages.size;
  const allReviewed = doneCount >= total;
  const pct = Math.round((doneCount / total) * 100);

  return `
    <div style="display:flex; flex-direction:column; gap:14px;">
      <div class="card sticky-bar" style="margin-bottom:0;">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <button class="link-btn" onclick="window._goStage('prep')">← Back to Q&amp;A Prep</button>
          <span class="h2">Final Page-by-Page Read-Through</span>
          <span class="pill ${allReviewed ? 'pill-ready' : 'pill-muted'}">${doneCount} / ${total} pages reviewed (${pct}%)</span>
        </div>
        <button class="btn btn-sm ${allReviewed ? 'btn-primary' : 'btn-ghost'}"
                onclick="${allReviewed ? "window._goStage('signoff')" : "jumpNextUnreviewed()"}">
          ${allReviewed ? 'All Pages Reviewed — Owner Sign-Off →' : `Review Remaining ${total - doneCount} Page${total - doneCount > 1 ? 's' : ''}`}
        </button>
      </div>

      <div class="trust-strip">
        <span>✓</span>
        <span><strong>Sanctity of the Reviewed-by stamp:</strong> View every page cleanly before stamping <strong>Reviewed by ${esc(state.ownerName || 'Your Name')}</strong> onto the PDF. Use <span class="mono">← / →</span> keys to step through.</span>
      </div>

      <div class="progress-track"><div class="progress-fill" style="width:${pct}%; background:${allReviewed ? '#047857' : 'var(--primary)'};"></div></div>

      <div class="workspace-grid" style="grid-template-columns: minmax(0, 68%) minmax(260px, 32%);">
        <div class="card card-pad" style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong>Page ${cur} of ${total}</strong>
              <span class="pill pill-ready" style="font-size:11px;">✓ Viewed</span>
            </div>
            <button class="link-btn" onclick="window._returnToPreFlightPage(${cur})">Spot a flaw? Return to Pre-Flight</button>
          </div>

          <div class="page-img-frame">
            <img src="${pageImgUrl(cur, false)}" alt="Page ${cur} full proof" />
            <div class="stamp-overlay">✓ Reviewed by ${esc(state.ownerName || 'Your Name')}</div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; padding-top:8px; border-top:1px solid var(--border);">
            <button class="btn btn-sm" onclick="stepReadPage(-1)" ${cur <= 1 ? 'disabled' : ''}>← Previous Page</button>
            ${cur < total
              ? `<button class="btn btn-primary btn-sm" onclick="stepReadPage(1)">Looks Good — Next Page (${cur + 1}/${total}) →</button>`
              : `<button class="btn btn-success btn-sm" onclick="${allReviewed ? "window._goStage('signoff')" : 'jumpNextUnreviewed()'}">${allReviewed ? '✓ All Pages Reviewed — Sign &amp; Stamp →' : 'Jump to Next Unreviewed Page →'}</button>`}
          </div>
        </div>

        <div class="card card-pad" style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between;">
            <span class="label-caps">Page Checklist</span>
            <span class="muted small">${doneCount}/${total}</span>
          </div>
          <div class="checklist-grid">
            ${Array.from({ length: total }, (_, idx) => idx + 1).map(p => {
              const seen = state.reviewedPages.has(p);
              return `
                <button class="chk-pill ${p === cur ? 'active' : ''} ${seen ? '' : 'unseen'}" onclick="jumpReadPage(${p})">
                  <span class="mono">P${p}</span>
                  <span style="color:${seen ? 'var(--success)' : 'var(--muted)'};">${seen ? '✓' : '○'}</span>
                </button>
              `;
            }).join('')}
          </div>
          <div class="muted small" style="padding-top:8px; border-top:1px solid var(--border);">
            On v2 re-uploads, unchanged pages remain checked via content-addressed page hashes.
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderSignoff() {
  const s = state.session;
  const r = state.report;
  const allReviewed = state.reviewedPages.size >= s.page_count;
  const p2 = Math.min(2, s.page_count);
  const notes = (r?.issues || []).filter(i => i.disposition);

  return `
    <div style="display:flex; flex-direction:column; gap:14px;">
      <div class="card sticky-bar" style="margin-bottom:0;">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <button class="link-btn" onclick="window._goStage('readthrough')">← Final Read-Through</button>
          <span class="pill ${allReviewed ? 'pill-ready' : 'pill-verify'}">${allReviewed ? `✓ ALL ${s.page_count}/${s.page_count} PAGES REVIEWED` : `▲ ${state.reviewedPages.size}/${s.page_count} PAGES REVIEWED`}</span>
          <strong>${esc(s.filename)}</strong>
        </div>
        <button class="link-btn" onclick="appReset()">Check another PDF</button>
      </div>

      <div class="workspace-grid" style="grid-template-columns: minmax(0, 60%) minmax(0, 40%);">
        <div class="card card-pad" style="display:flex; flex-direction:column; gap:14px;">
          <div>
            <div class="h2">Owner Accountability Stamp</div>
            <div class="muted small" style="margin-top:3px;">Stamps a subtle luminance-adaptive <strong>✓ Reviewed by &lt;Name&gt;</strong> pill cleanly below slide footers and writes durable PDF <code>/Info</code> metadata.</div>
          </div>

          <div class="grid-2">
            <label class="field">
              <span>Owner Name</span>
              <input id="ownerNameInput" type="text" value="${esc(state.ownerName)}" oninput="window._setOwnerName(this.value)" placeholder="e.g., Krishna Kumar" />
            </label>
            <div class="field">
              <span>Stamp Placement</span>
              <div class="choice-group">
                <button class="choice-pill ${state.stampScope === 'all' ? 'active' : ''}" onclick="window._setStampScope('all')">All Pages</button>
                <button class="choice-pill ${state.stampScope === 'cover' ? 'active' : ''}" onclick="window._setStampScope('cover')">Cover / P1 Only</button>
              </div>
            </div>
          </div>

          <div class="grid-2">
            <div style="display:flex; flex-direction:column; gap:6px;">
              <span class="muted small">Preview · Page 1</span>
              <div class="page-img-frame">
                <img src="${pageImgUrl(1, false)}" alt="Page 1 stamp preview" />
                <div class="stamp-overlay">✓ Reviewed by ${esc(state.ownerName || 'Your Name')}</div>
              </div>
            </div>
            ${s.page_count > 1 ? `
              <div style="display:flex; flex-direction:column; gap:6px;">
                <span class="muted small">Preview · Page ${p2} (${state.stampScope === 'all' ? 'Stamped' : 'Unstamped'})</span>
                <div class="page-img-frame">
                  <img src="${pageImgUrl(p2, false)}" alt="Page ${p2} stamp preview" />
                  ${state.stampScope === 'all' ? `<div class="stamp-overlay">✓ Reviewed by ${esc(state.ownerName || 'Your Name')}</div>` : ''}
                </div>
              </div>
            ` : ''}
          </div>

          ${state.stampResult ? `
            <div class="quote-box mono" style="border-color:var(--success-border); background:var(--success-bg); color:var(--success);">
              ✓ Stamped (${state.stampResult.preferred_corner}) · /Info ReviewedBy="${esc(state.stampResult.owner_name)}" · PreFlightStatus="${esc(state.stampResult.metadata_written?.PreFlightStatus || 'VERIFIED')}"
            </div>
          ` : ''}

          <div style="display:flex; justify-content:flex-end; gap:10px; padding-top:8px; border-top:1px solid var(--border);">
            ${!allReviewed
              ? `<button class="btn btn-sm" onclick="window._resumeReadThrough()">Complete Final Read to Unlock →</button>`
              : `<button class="btn btn-primary" onclick="stampAndDownload()" ${state.busy ? 'disabled' : ''}>${state.busy ? 'Stamping PDF…' : '↓ Stamp &amp; Download Reviewed PDF'}</button>`}
          </div>
        </div>

        <div class="card card-pad" style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
            <div>
              <div class="h2">Meeting Q&amp;A Prep Sheet</div>
              <div class="muted small">Keep open during your leadership review.</div>
            </div>
            <div style="display:flex; gap:6px;">
              <button class="btn btn-ghost btn-sm" onclick="window._copyNotes('md')">Copy Markdown</button>
              <button class="btn btn-ghost btn-sm" onclick="window._copyNotes('plain')">Copy Plain Text</button>
            </div>
          </div>
          ${r?.creator_intent ? `<div class="quote-box"><strong>Stated Intent:</strong> ${esc(r.creator_intent)}</div>` : ''}
          ${state.gate2?.questions?.length ? `
            <div style="display:flex; flex-direction:column; gap:8px;">
              ${state.gate2.questions.map(q => {
                const a = state.gate2.answers?.[q.id];
                return `
                  <div class="quote-box">
                    <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
                      <strong style="color:var(--fg);">${q.is_limitation ? '★ ' : ''}${esc(q.prep_title)}</strong>
                      <span class="mono">P${q.pages.join(', P')}</span>
                    </div>
                    <div>${esc(a?.answer_text || '(Pending note)')}</div>
                  </div>
                `;
              }).join('')}
            </div>
          ` : ''}
          ${notes.length ? `
            <div style="display:flex; flex-direction:column; gap:8px; padding-top:6px; border-top:1px solid var(--border);">
              <div class="label-caps">Logged Pre-Flight Decisions</div>
              ${notes.map(i => `
                <div class="quote-box">
                  <strong style="color:var(--fg);">${esc(i.title)} (P${i.pages.join(', ')})</strong><br/>
                  <span>${i.disposition.status === 'intentional' ? 'Intentional' : 'Ignored for now'}: ${esc(i.disposition.note)}</span>
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
      </div>

      ${renderFeedbackStrip('signoff', 'Did Slop Gate make this document sharper before sending?')}
    </div>
  `;
}

function renderFeedbackStrip(stageKey, promptText) {
  const rating = state.feedback.inlineRatingByStage[stageKey] || '';
  const expanded = Boolean(state.feedback.inlineExpanded[stageKey]);
  const tagsSet = state.feedback.inlineTagsByStage[stageKey] || new Set();
  const comment = state.feedback.inlineCommentByStage[stageKey] || '';
  return `
    <div class="feedback-bar">
      <div class="feedback-row">
        <span class="small" style="font-weight:600;">
          ${rating ? '✓ Thanks for the rating! Want to add a quick tag or note?' : esc(promptText)}
        </span>
        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
          <button type="button" class="fb-btn ${rating === 'up' ? 'active' : ''}" onclick="window._quickFeedback('${stageKey}','up')">👍 Helpful</button>
          <button type="button" class="fb-btn ${rating === 'down' ? 'active' : ''}" onclick="window._quickFeedback('${stageKey}','down')">👎 Needs work</button>
          <button type="button" class="link-btn" onclick="window._openFeedbackModal('${rating || 'up'}')">+ Detailed note</button>
        </div>
      </div>
      ${expanded ? `
        <div style="display:flex; flex-direction:column; gap:8px; padding-top:6px; border-top:1px solid var(--border);">
          <div class="choice-group">
            ${FEEDBACK_TAGS.map(t => `
              <button type="button" class="choice-pill ${tagsSet.has(t) ? 'active' : ''}"
                      onclick="window._toggleInlineFeedbackTag('${stageKey}','${esc(t)}')">${esc(t)}</button>
            `).join('')}
          </div>
          <div style="display:flex; gap:8px; align-items:center;">
            <input type="text" value="${esc(comment)}"
                   oninput="window._setInlineFeedbackComment('${stageKey}', this.value)"
                   onkeydown="if(event.key==='Enter') window._saveInlineFeedbackDetails('${stageKey}')"
                   placeholder="Optional 1-line note (e.g., what worked or felt off)…" />
            <button type="button" class="btn btn-primary btn-sm" onclick="window._saveInlineFeedbackDetails('${stageKey}')">Save Note</button>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

window._quickFeedback = async (stageKey, rating) => {
  state.feedback.inlineRatingByStage[stageKey] = rating;
  state.feedback.inlineExpanded[stageKey] = true;
  if (!state.feedback.inlineTagsByStage[stageKey]) state.feedback.inlineTagsByStage[stageKey] = new Set();
  render();
  try {
    const resp = await apiJson('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_id: state.feedback.inlineIdByStage[stageKey] || null,
        session_id: state.session?.session_id || null,
        revision: state.session?.revision || null,
        stage: stageKey,
        rating,
        tags: Array.from(state.feedback.inlineTagsByStage[stageKey]),
        comment: state.feedback.inlineCommentByStage[stageKey] || '',
        context: feedbackContext(),
      }),
    });
    state.feedback.inlineIdByStage[stageKey] = resp.feedback_id;
    showToast(rating === 'up' ? '✓ Logged 👍 — add a quick tag or note if you like!' : '✓ Logged 👎 — tell us what felt off!');
  } catch (e) {
    showToast('Feedback error: ' + e.message);
  }
};

window._toggleInlineFeedbackTag = (stageKey, tag) => {
  if (!state.feedback.inlineTagsByStage[stageKey]) state.feedback.inlineTagsByStage[stageKey] = new Set();
  const s = state.feedback.inlineTagsByStage[stageKey];
  if (s.has(tag)) s.delete(tag);
  else s.add(tag);
  render();
  window._saveInlineFeedbackDetails(stageKey, true);
};

window._setInlineFeedbackComment = (stageKey, val) => {
  state.feedback.inlineCommentByStage[stageKey] = val;
};

window._saveInlineFeedbackDetails = async (stageKey, silent = false) => {
  try {
    const resp = await apiJson('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_id: state.feedback.inlineIdByStage[stageKey] || null,
        session_id: state.session?.session_id || null,
        revision: state.session?.revision || null,
        stage: stageKey,
        rating: state.feedback.inlineRatingByStage[stageKey] || 'note',
        tags: Array.from(state.feedback.inlineTagsByStage[stageKey] || []),
        comment: (state.feedback.inlineCommentByStage[stageKey] || '').trim(),
        context: feedbackContext(),
      }),
    });
    state.feedback.inlineIdByStage[stageKey] = resp.feedback_id;
    if (!silent) {
      state.feedback.inlineExpanded[stageKey] = false;
      showToast('✓ Feedback note saved — thank you!');
      render();
    }
  } catch (e) {
    if (!silent) showToast('Feedback error: ' + e.message);
  }
};

window._setOwnerName = (v) => {
  state.ownerName = v;
  // Update live preview overlays smoothly without losing focus
  document.querySelectorAll('.stamp-overlay').forEach(el => {
    el.textContent = `✓ Reviewed by ${v.trim() || 'Your Name'}`;
  });
};
window._setStampScope = (v) => { state.stampScope = v; render(); };
window._copyNotes = (fmt = 'md') => {
  const md = state.gate2?.prep_sheet_markdown || `# Pre-Flight Summary — ${state.session.filename}`;
  const out = fmt === 'plain' ? md.replace(/^#+\s*/gm, '').replace(/\*\*/g, '').replace(/\*/g, '') : md;
  trackEvent('prep_sheet_copied', { format: fmt });
  navigator.clipboard?.writeText(out).then(() => showToast(`✓ Meeting Q&A Prep Sheet copied (${fmt === 'plain' ? 'Plain Text' : 'Markdown'})!`));
};

function wireDropzone() {
  const dz = $('dropzone');
  if (!dz) return;
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('dragover'); };
  dz.ondragleave = () => dz.classList.remove('dragover');
  dz.ondrop = (e) => {
    e.preventDefault();
    dz.classList.remove('dragover');
    const f = e.dataTransfer?.files?.[0];
    if (f) uploadNewPdf(f);
  };
}

function render() {
  if (state.lastTrackedStage !== state.stage) {
    state.lastTrackedStage = state.stage;
    trackEvent('stage_viewed', { stage: state.stage });
  }
  renderBreadcrumb();
  const root = $('app');
  if (state.stage === 'upload') root.innerHTML = renderUpload();
  else if (state.stage === 'waiting_intent') root.innerHTML = renderWaitingIntent();
  else if (state.stage === 'report') root.innerHTML = renderReport();
  else if (state.stage === 'prep') root.innerHTML = renderPrep();
  else if (state.stage === 'readthrough') root.innerHTML = renderReadThrough();
  else if (state.stage === 'signoff') root.innerHTML = renderSignoff();
  wireDropzone();
}
window.render = render;

init();
