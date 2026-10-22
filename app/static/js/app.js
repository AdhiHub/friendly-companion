/* Gethu UI bootstrap: sidebar, conversation list, voice input, header controls
   and wiring between the chat controller, settings and voice manager. */

import { api } from './api.js';
import { createAttachmentManager } from './attachments.js';
import { createChatController } from './chat.js';
import { createSettingsPanel } from './settings.js';
import { createWelcomeScreen } from './welcome.js';
import { setCompanionName } from './companion.js';
import { loadPrefs, savePrefs } from './storage.js';
import {
  createLiveConversation,
  createRecognizer,
  createSynth,
  detectSupport,
  insertTranscript,
  liveStateLabel,
  recognitionErrorMessage,
} from './voice.js';

const $ = (id) => document.getElementById(id);

/* --------------------------------------------------------------- helpers */

let prefsCache = loadPrefs();
function prefs(patch) {
  if (patch) prefsCache = savePrefs(patch);
  return prefsCache;
}

function refreshIcons() {
  try {
    globalThis.lucide?.createIcons();
  } catch { /* icons are decorative — never block the UI */ }
}

let toastTimer = null;
function toast(message) {
  const node = $('toast');
  if (!node) return;
  node.textContent = String(message ?? '');
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 2600);
}

let noticeTimer = null;
function showNotice(message, kind = 'error') {
  const notice = $('notice');
  if (!notice) return;
  $('notice-text').textContent = String(message ?? '');
  notice.classList.toggle('info', kind === 'info');
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 12000);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
}

/* ----------------------------------------------------------------- voice */

const support = detectSupport(globalThis);
const synth = createSynth(globalThis);

const voice = {
  supported: synth.supported,
  speak: (text, opts) => synth.speak(text, opts),
  stop: () => synth.stop(),
  isSpeaking: () => synth.isSpeaking(),
  onceEnded(fn) {
    if (!synth.isSpeaking()) {
      fn();
      return () => {};
    }
    const unsubscribe = synth.onChange(({ state }) => {
      if (state === 'idle') {
        unsubscribe();
        fn();
      }
    });
    return unsubscribe;
  },
};

/* ---------------------------------------------------------- attachments */

const attachments = createAttachmentManager({
  fileInput: $('file-input'),
  previewsEl: $('attach-previews'),
  dropTargetEl: $('composer'),
  onError: (message) => showNotice(message, 'error'),
});

/* ------------------------------------------------------------- chat ctl */

const chat = createChatController({
  els: {
    messages: $('messages'),
    input: $('message-input'),
    send: $('send-btn'),
    stopGen: $('stop-generation'),
    mode: $('mode-select'),
    title: $('chat-title'),
  },
  voice,
  attachments,
  getMode: () => $('mode-select').value || 'friendly',
  prefs,
  toast,
  showNotice,
  refreshIcons,
  onConversation: (update) => handleConversationUpdate(update),
});

/* -------------------------------------------------------- conversation UI */

const listEl = $('conv-list');
let conversations = [];
let activeId = null;
let searchQuery = '';

function renderConversations() {
  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );
  listEl.innerHTML = '';
  if (!filtered.length) {
    const empty = document.createElement('p');
    empty.className = 'conv-empty';
    empty.textContent = searchQuery ? 'No chats match your search.' : 'No chats yet.';
    listEl.append(empty);
    return;
  }
  for (const convo of filtered) {
    const item = document.createElement('div');
    item.className = `conv-item${convo.id === activeId ? ' active' : ''}`;
    item.dataset.id = convo.id;
    item.tabIndex = 0;
    item.innerHTML = `
      <span class="conv-title"></span>
      <span class="conv-actions">
        <button class="icon-btn" data-conv-act="rename" title="Rename" aria-label="Rename"><i data-lucide="pencil"></i></button>
        <button class="icon-btn danger" data-conv-act="delete" title="Delete" aria-label="Delete"><i data-lucide="trash-2"></i></button>
      </span>`;
    item.querySelector('.conv-title').textContent = convo.title;
    listEl.append(item);
  }
  refreshIcons();
}

async function loadConversations() {
  try {
    conversations = await api.get('/api/conversations');
    renderConversations();
  } catch (err) {
    setHealth('offline', err.message);
  }
}

function handleConversationUpdate(update) {
  if (!update?.id) return;
  activeId = update.id;
  chat.setConversationId(activeId);
  loadConversations().then(() => {
    const current = conversations.find((c) => c.id === activeId);
    if (current) $('chat-title').textContent = current.title;
    renderConversations();
  });
}

async function openConversation(id) {
  if (chat.state.streaming) chat.stopGenerating();
  activeId = id;
  try {
    const detail = await chat.loadConversation({ id });
    activeId = detail.id;
    renderConversations();
    closeSidebarMobile();
    return detail;
  } catch (err) {
    showNotice(err.message);
  }
  return null;
}

function startNewChat() {
  if (chat.state.streaming) chat.stopGenerating();
  activeId = null;
  chat.reset();
  renderConversations();
  closeSidebarMobile();
  chat.focus();
}

function beginRename(item) {
  const id = item.dataset.id;
  const titleEl = item.querySelector('.conv-title');
  if (!titleEl || item.querySelector('.conv-rename-input')) return;
  const input = document.createElement('input');
  input.className = 'conv-rename-input';
  input.value = conversations.find((c) => c.id === id)?.title || '';
  titleEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = async (save) => {
    const value = input.value.trim();
    if (save && value) {
      try {
        await api.patch(`/api/conversations/${id}`, { title: value });
        conversations = conversations.map((c) => (c.id === id ? { ...c, title: value } : c));
        if (activeId === id) $('chat-title').textContent = value;
      } catch (err) {
        showNotice(err.message);
      }
    }
    renderConversations();
  };

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); commit(true); }
    if (event.key === 'Escape') { event.preventDefault(); commit(false); }
  });
  input.addEventListener('blur', () => commit(true));
}

async function deleteConversation(id) {
  const convo = conversations.find((c) => c.id === id);
  const confirmed = globalThis.confirm?.(
    `Delete "${convo?.title || 'this chat'}"? This cannot be undone.`
  );
  if (!confirmed) return;
  try {
    await api.del(`/api/conversations/${id}`);
    conversations = conversations.filter((c) => c.id !== id);
    if (activeId === id) startNewChat();
    renderConversations();
    toast('Chat deleted');
  } catch (err) {
    showNotice(err.message);
  }
}

listEl.addEventListener('click', (event) => {
  const item = event.target.closest('.conv-item');
  if (!item) return;
  const action = event.target.closest('[data-conv-act]')?.dataset.convAct;
  if (action === 'rename') { event.stopPropagation(); beginRename(item); return; }
  if (action === 'delete') { event.stopPropagation(); deleteConversation(item.dataset.id); return; }
  openConversation(item.dataset.id);
});
listEl.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  const item = event.target.closest?.('.conv-item');
  if (item && !event.target.closest('[data-conv-act]')) openConversation(item.dataset.id);
});

$('conv-search').addEventListener('input', (event) => {
  searchQuery = event.target.value || '';
  renderConversations();
});

$('new-chat-btn').addEventListener('click', startNewChat);

/* --------------------------------------------------------------- sidebar */

function setMobileSidebar(open) {
  $('sidebar').classList.toggle('open', open);
  $('sidebar-scrim').hidden = !open;
}
function closeSidebarMobile() { setMobileSidebar(false); }

$('sidebar-toggle').addEventListener('click', () => {
  const appRoot = document.querySelector('.app');
  if (globalThis.matchMedia?.('(max-width: 860px)').matches) {
    setMobileSidebar(!$('sidebar').classList.contains('open'));
    return;
  }
  appRoot.classList.toggle('sidebar-collapsed');
});
$('sidebar-close').addEventListener('click', closeSidebarMobile);
$('sidebar-scrim').addEventListener('click', closeSidebarMobile);

/* ---------------------------------------------------------- header bits */

$('mode-select').value = prefs().mode || 'friendly';
$('mode-select').addEventListener('change', async (event) => {
  const mode = event.target.value;
  prefs({ mode });
  const id = chat.getConversationId();
  if (id) {
    try {
      await api.patch(`/api/conversations/${id}`, { mode });
      conversations = conversations.map((c) => (c.id === id ? { ...c, mode } : c));
    } catch (err) {
      showNotice(err.message);
    }
  }
});

function renderVoiceToggle() {
  const enabled = prefs().voiceEnabled;
  const button = $('voice-toggle');
  button.classList.toggle('active', enabled);
  button.setAttribute('aria-pressed', String(enabled));
  button.title = enabled ? 'Voice output: on' : 'Voice output: off';
  button.innerHTML = enabled
    ? '<i data-lucide="volume-2"></i>'
    : '<i data-lucide="volume-x"></i>';
  refreshIcons();
}

$('voice-toggle').addEventListener('click', () => {
  const next = !prefs().voiceEnabled;
  prefs({ voiceEnabled: next });
  if (!next) voice.stop();
  renderVoiceToggle();
  toast(next ? 'Voice output on' : 'Voice output off');
});

$('stop-speaking').addEventListener('click', () => voice.stop());

synth.onChange(({ state }) => {
  $('stop-speaking').hidden = state !== 'speaking';
});

/* ---------------------------------------------------------- voice input */

const micBtn = $('mic-btn');
const banner = $('voice-banner');
const bannerText = $('voice-banner-text');
const voiceHint = $('voice-hint');

const recognizer = createRecognizer(globalThis, {
  lang: prefs().lang,
  onStart() {
    micBtn.classList.add('recording');
    micBtn.title = 'Stop listening';
    banner.hidden = false;
    bannerText.innerHTML = '<span class="listening-dot"></span>Listening… speak now';
    $('stop-listening').hidden = false;
    $('voice-send').hidden = true;
    $('voice-discard').hidden = true;
  },
  onInterim(text) {
    if (live.isActive()) {
      bannerText.innerHTML = `<span class="listening-dot"></span>${text}`;
      return;
    }
    bannerText.innerHTML = `<span class="listening-dot"></span>${text}`;
  },
  onFinal(text) {
    // Live conversation owns the turn when it is running.
    if (live.handleFinal(text)) return;
    insertTranscript($('message-input'), text);
    $('message-input').dispatchEvent(new Event('input', { bubbles: true }));
    bannerText.textContent = `Heard: “${text}” — edit below or send.`;
    $('stop-listening').hidden = true;
    $('voice-send').hidden = false;
    $('voice-discard').hidden = false;
    $('message-input').focus();
  },
  onError(code) {
    if (live.handleError(code)) return;
    const message = recognitionErrorMessage(code, recognizer.support);
    if (message) showNotice(message, 'error');
    resetMicUi();
  },
  onEnd() {
    if (live.handleEnd()) return;
    resetMicUi({ keepBanner: $('voice-send') && !$('voice-send').hidden });
  },
});

function resetMicUi({ keepBanner = false } = {}) {
  micBtn.classList.remove('recording');
  micBtn.title = 'Start voice input';
  if (!keepBanner) {
    banner.hidden = true;
    $('stop-listening').hidden = false;
    $('voice-send').hidden = true;
    $('voice-discard').hidden = true;
  }
}

function startListening() {
  if (!recognizer.supported) {
    showNotice(
      `Voice input is not supported in this browser. (${voiceDiagnostics()})`,
      'error'
    );
    return;
  }
  if (!recognizer.support.secure) {
    showNotice('Microphone access requires HTTPS or localhost.', 'error');
    return;
  }
  const started = recognizer.start({ lang: prefs().lang });
  if (!started) resetMicUi();
}

micBtn.addEventListener('click', () => {
  if (recognizer.isRunning()) recognizer.stop();
  else startListening();
});
$('stop-listening').addEventListener('click', () => recognizer.stop());
$('voice-send').addEventListener('click', () => {
  banner.hidden = true;
  $('voice-send').hidden = true;
  $('voice-discard').hidden = true;
  $('composer').requestSubmit();
});
$('voice-discard').addEventListener('click', () => {
  $('message-input').value = '';
  $('message-input').dispatchEvent(new Event('input', { bubbles: true }));
  banner.hidden = true;
  $('voice-send').hidden = true;
  $('voice-discard').hidden = true;
  $('message-input').focus();
});

/* --------------------------------------------------- live voice conversation */

const liveBtn = $('live-btn');

const live = createLiveConversation({
  recognizer,
  synth,
  send: (text) => chat.sendAndReply(text),
  // Live turns get fresh speech prefs on every reply.
  get speechOpts() {
    const p = prefs();
    return { voiceURI: p.voiceURI, rate: p.rate, lang: p.lang, preferMale: true };
  },
  onState(state) {
    const on = state !== 'idle';
    liveBtn.classList.toggle('recording', on);
    liveBtn.setAttribute('aria-pressed', String(on));
    liveBtn.title = on ? 'Stop live conversation' : 'Start live voice conversation';
    if (on) {
      banner.hidden = false;
      bannerText.innerHTML =
        `<span class="listening-dot"></span>${liveStateLabel(state)}`;
      $('stop-listening').hidden = false;
      $('voice-send').hidden = true;
      $('voice-discard').hidden = true;
    } else {
      resetMicUi();
    }
  },
  onTranscript(text) {
    // Show the user's spoken turn immediately, even before the reply lands.
    insertTranscript($('message-input'), text);
    $('message-input').dispatchEvent(new Event('input', { bubbles: true }));
    bannerText.innerHTML = `<span class="listening-dot"></span>You: “${text}”`;
  },
  onError(code) {
    const message = recognitionErrorMessage(code, recognizer.support);
    if (message) showNotice(message, 'error');
    resetMicUi();
  },
});

liveBtn.addEventListener('click', () => {
  if (live.isActive()) {
    live.stop();
    showNotice('Live conversation ended.', 'info');
    return;
  }
  if (!recognizer.supported) {
    showNotice(
      `Live voice needs speech recognition. (${voiceDiagnostics()})`,
      'error'
    );
    return;
  }
  if (!recognizer.support.secure) {
    showNotice('Live voice needs HTTPS or localhost for the microphone.', 'error');
    return;
  }
  live.start();
  showNotice('Live conversation started — just talk. Tap the button again to stop.', 'info');
});

if (!recognizer.supported) {
  voiceHint.hidden = false;
  voiceHint.textContent =
    "Voice input isn't supported in this browser. On Brave, lower Shields for this site (lion icon → Shields down) and reload.";
  micBtn.title = 'Voice input not supported — tap for details';
} else if (!support.secure) {
  voiceHint.hidden = false;
  voiceHint.textContent = 'Microphone access needs HTTPS or localhost — voice input may be blocked.';
}
if (!voice.supported) {
  $('voice-toggle').disabled = true;
  $('voice-toggle').title = 'Speech synthesis is not supported in this browser';
}

/* ------------------------------------------------------------ attachments */

$('attach-btn').addEventListener('click', () => $('file-input').click());

/* --------------------------------------------------------------- settings */

const settings = createSettingsPanel({
  els: {
    modal: $('settings-modal'),
    openBtn: $('settings-btn'),
    closeBtn: $('settings-close'),
    apiStatus: $('api-key-status'),
    apiPill: $('api-key-pill'),
    apiKeyInput: $('api-key-input'),
    apiKeySave: $('api-key-save'),
    name: $('companion-name'),
    setupBtn: $('setup-btn'),
    model: $('model-select'),
    autospeak: $('set-autospeak'),
    voiceURI: $('voice-select'),
    rate: $('rate-range'),
    rateValue: $('rate-value'),
    lang: $('lang-select'),
    support: $('speech-support'),
    theme: $('theme-select'),
    clearHistory: $('clear-history'),
  },
  synth,
  prefs,
  applyTheme,
  toast,
  onClearHistory() {
    startNewChat();
    loadConversations();
  },
  onOpenWelcome() {
    welcome.open(lastSettings);
  },
});

/* ---------------------------------------------------------- welcome screen */

let lastSettings = null;

const welcome = createWelcomeScreen({
  els: {
    modal: $('welcome-modal'),
    name: $('welcome-name'),
    key: $('welcome-key'),
    keyStep: $('welcome-key-step'),
    brand: $('welcome-brand'),
    error: $('welcome-error'),
    save: $('welcome-save'),
    skip: $('welcome-skip'),
    suggestions: $('welcome-name-suggestions'),
  },
  toast,
  onDone() {
    checkHealth();
    settings.refreshStatus();
  },
});

/* ----------------------------------------------------------------- health */

async function checkHealth() {
  const dot = $('status-dot');
  const text = $('status-text');
  try {
    const health = await api.get('/api/health');
    if (health.api_key_configured) {
      dot.className = 'status-dot ok';
      text.textContent = 'Connected';
    } else {
      dot.className = 'status-dot err';
      text.textContent = 'No API key';
    }
  } catch {
    dot.className = 'status-dot err';
    text.textContent = 'Server offline';
  }
}

/* ------------------------------------------------------------ voice diag */

/**
 * Report what voice features this browser actually exposes. Runs on demand
 * from the mic button when nothing is available, so the user gets a concrete
 * reason instead of a silent failure.
 */
function voiceDiagnostics() {
  const lines = [
    `Recognition: ${support.recognition ? 'available' : 'NOT available'}`,
    `Synthesis: ${voice.supported ? 'available' : 'NOT available'}`,
    `Voices installed: ${synth.getVoices().length}`,
    `Secure context: ${support.secure ? 'yes' : 'no'}`,
  ];
  return lines.join(' · ');
}

/* ------------------------------------------------------------------- misc */

$('notice-close').addEventListener('click', () => { $('notice').hidden = true; });

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (!$('settings-modal').hidden) settings.close();
    else closeSidebarMobile();
  }
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'o') {
    event.preventDefault();
    startNewChat();
  }
});

window.addEventListener('beforeunload', () => {
  recognizer.abort?.();
  voice.stop();
});

/* -------------------------------------------------------------------- go */

/**
 * Load the server-side settings (model, companion name) and mirror them into
 * the UI. On a fresh install without an API key the welcome screen opens so
 * the user can finish setup in the browser.
 */
async function loadSettings() {
  try {
    lastSettings = await api.get('/api/settings');
  } catch {
    lastSettings = null;
    return;
  }
  if (!lastSettings) return;
  setCompanionName(lastSettings.companion_name || 'Gethu');
  if (lastSettings.setup_complete === false) {
    welcome.open(lastSettings);
  }
}

function init() {
  applyTheme(prefs().theme);
  renderVoiceToggle();
  chat.bind();
  attachments.bind();
  settings.bind();
  welcome.bind();
  refreshIcons();
  loadConversations();
  checkHealth();
  loadSettings();
  chat.focus();
  // Voices load asynchronously in Chromium; re-read now and once more shortly.
  synth.refreshVoices();
  globalThis.setTimeout(() => synth.refreshVoices(), 300);
  globalThis.setTimeout(() => {
    console.info('[gethu] voice:', voiceDiagnostics());
  }, 1200);
}

init();
