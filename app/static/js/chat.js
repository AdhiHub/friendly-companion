/* Chat surface: composer submission, streaming replies, message rendering and
   per-message actions (copy / speak / regenerate). Speech never changes what
   is displayed — the rendered message is always the original text. */

import { api, streamChat } from './api.js';
import { enhanceCodeBlocks, escapeHtml, renderMarkdown } from './markdown.js';
import { getCompanionInitial, getCompanionName } from './companion.js';

const rawContent = new WeakMap();
let uidCounter = 0;

/**
 * The companion's name and avatar letter. The name is owned by the backend
 * (it also goes into the system prompt), so the chat surface just reads it.
 */
function companionName() {
  return getCompanionName();
}
function companionInitial() {
  return getCompanionInitial();
}

/**
 * Duplicate-submission guard. `acquire()` returns false while a send is
 * already in flight, so a double Enter / double tap can never send twice.
 */
export function createSubmitGuard() {
  let active = false;
  return {
    isActive: () => active,
    acquire() {
      if (active) return false;
      active = true;
      return true;
    },
    release() {
      active = false;
    },
  };
}

function uid(prefix) {
  uidCounter += 1;
  return `${prefix}_${uidCounter}`;
}

function timeLabel(iso) {
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function attachmentChip(att) {
  if (att.mime?.startsWith('image/')) {
    return `<a class="msg-att" href="/api/attachments/${att.id}" target="_blank" rel="noopener">
      <img src="/api/attachments/${att.id}" alt="${escapeHtml(att.filename)}" loading="lazy"></a>`;
  }
  return `<a class="msg-att" href="/api/attachments/${att.id}" target="_blank" rel="noopener">
    <span aria-hidden="true">📄</span>${escapeHtml(att.filename)}</a>`;
}

export function createChatController({
  els,
  voice,
  attachments,
  getMode,
  prefs,
  onConversation = null,
  toast = () => {},
  showNotice = () => {},
  refreshIcons = () => {},
}) {
  const state = {
    conversationId: null,
    streaming: null, // { abort, assistantEl, buffer, meta, pendingPayload }
    lastPayload: null,
    spokenEl: null,
  };
  const submitGuard = createSubmitGuard();

  /* ---------------------------------------------------------- rendering */

  function inner() {
    let node = els.messages.querySelector('.messages-inner');
    if (!node) {
      node = document.createElement('div');
      node.className = 'messages-inner';
      els.messages.append(node);
    }
    return node;
  }

  function showEmptyState(show) {
    const empty = document.getElementById('empty-state');
    if (empty) empty.hidden = !show;
    const list = els.messages.querySelector('.messages-inner');
    if (list) list.hidden = show;
  }

  function scrollToEnd() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function buildMessageElement(message) {
    const article = document.createElement('article');
    article.className = `msg ${message.role}`;
    article.dataset.id = message.id;
    const isAssistant = message.role === 'assistant';
    const who = isAssistant ? companionName() : 'You';
    const initial = isAssistant ? companionInitial() : 'You';

    const attachmentsHtml = message.attachments?.length
      ? `<div class="msg-attachments">${message.attachments.map(attachmentChip).join('')}</div>`
      : '';

    article.innerHTML = `
      <div class="msg-avatar" aria-hidden="true">${initial}</div>
      <div class="msg-body">
        <div class="msg-meta"><span class="msg-role">${who}</span>
          <span>${escapeHtml(timeLabel(message.created_at))}</span></div>
        ${attachmentsHtml}
        <div class="msg-content"></div>
        <div class="msg-actions"></div>
      </div>`;

    const content = article.querySelector('.msg-content');
    if (isAssistant) {
      content.innerHTML = renderMarkdown(message.content);
      enhanceCodeBlocks(content);
      article.querySelector('.msg-actions').innerHTML = `
        <button class="icon-btn" data-act="speak" title="Speak this reply" aria-label="Speak this reply"><i data-lucide="volume-2"></i></button>
        <button class="icon-btn" data-act="copy" title="Copy reply" aria-label="Copy reply"><i data-lucide="copy"></i></button>
        <button class="icon-btn" data-act="regenerate" title="Regenerate" aria-label="Regenerate reply"><i data-lucide="refresh-cw"></i></button>`;
    } else {
      content.textContent = message.content;
    }
    rawContent.set(content, message.content);
    return article;
  }

  function renderHistory(messages) {
    clearMessages();
    for (const message of messages) inner().append(buildMessageElement(message));
    showEmptyState(messages.length === 0);
    refreshIcons(els.messages);
    scrollToEnd();
  }

  function clearMessages() {
    for (const child of [...els.messages.querySelectorAll('.messages-inner, .msg')]) {
      child.remove();
    }
    showEmptyState(true);
  }

  function setTitle(title) {
    if (els.title) els.title.textContent = title || companionName();
  }

  /* ---------------------------------------------------------- streaming */

  function ensureAssistantBubble(meta) {
    const article = document.createElement('article');
    article.className = 'msg assistant';
    article.dataset.id = meta?.assistant_message_id || uid('m');
    const who = companionName();
    article.innerHTML = `
      <div class="msg-avatar" aria-hidden="true">${escapeHtml(companionInitial())}</div>
      <div class="msg-body">
        <div class="msg-meta"><span class="msg-role">${escapeHtml(who)}</span></div>
        <div class="msg-content"><div class="typing" aria-label="${escapeHtml(who)} is typing">
          <span></span><span></span><span></span></div></div>
        <div class="msg-actions"></div>
      </div>`;
    inner().append(article);
    showEmptyState(false);
    scrollToEnd();
    return article;
  }

  function setGenerating(active) {
    els.stopGen.hidden = !active;
    els.send.disabled = active || !els.input.value.trim() || attachments.busy();
  }

  async function send({ text, attachmentIds = [] } = {}) {
    const message = String(text ?? '').trim();
    if (!submitGuard.acquire()) {
      toast(`${companionName()} is already replying — hit stop first.`);
      return false;
    }
    try {
      return await runSend(message, attachmentIds);
    } finally {
      submitGuard.release();
    }
  }

  async function runSend(message, attachmentIds) {
    if (!message && attachmentIds.length === 0) {
      toast('Type something first.');
      return false;
    }

    const payload = {
      message: message || '(attachment)',
      conversation_id: state.conversationId,
      mode: getMode(),
      attachment_ids: attachmentIds,
    };
    state.lastPayload = payload;

    // Optimistic clear — restored below if the request never starts.
    const restoreText = els.input.value;
    els.input.value = '';
    autoResize();

    const userArticle = buildMessageElement({
      id: uid('local'),
      role: 'user',
      content: payload.message,
      attachments: [],
      created_at: new Date().toISOString(),
    });
    // Attachments were uploaded already; show them on the optimistic bubble.
    inner().append(userArticle);
    showEmptyState(false);
    scrollToEnd();

    const controller = new AbortController();
    let assistantEl = null;
    let buffer = '';
    let gotMeta = false;
    let replyText = null;

    const restoreIfFailed = () => {
      if (!gotMeta && !buffer && els.input.value.trim() === '') {
        els.input.value = restoreText;
        autoResize();
      }
    };

    state.streaming = { abort: controller, assistantEl: null, buffer: '' };
    setGenerating(true);

    await streamChat(payload, {
      onMeta(meta) {
        gotMeta = true;
        state.conversationId = meta.conversation_id;
        userArticle.dataset.id = meta.user_message_id;
        if (meta.mode && meta.mode !== getMode()) {
          els.mode.value = meta.mode;
        }
        assistantEl = ensureAssistantBubble(meta);
        state.streaming.assistantEl = assistantEl;
        attachments.clear(); // only once the server accepted the request
        onConversation?.({ id: meta.conversation_id, created: meta.conversation_created });
      },
      onDelta(delta) {
        if (!assistantEl) assistantEl = ensureAssistantBubble(null);
        buffer += delta.text;
        state.streaming.buffer = buffer;
        const content = assistantEl.querySelector('.msg-content');
        content.innerHTML = renderMarkdown(buffer);
        enhanceCodeBlocks(content);
        scrollToEnd();
      },
      onDone(done) {
        buffer = done.text || buffer;
        replyText = buffer;
        finalizeBubble(assistantEl, done.message_id, buffer);
        if (prefs().voiceEnabled && prefs().autoSpeak) speakElement(assistantEl);
        onConversation?.({ id: done.conversation_id, updated: true });
      },
      onError(error) {
        restoreIfFailed();
        const partial = error.partial_text || buffer;
        if (partial) {
          finalizeBubble(assistantEl, null, partial);
          showNotice(`${error.message} (partial reply shown)`, 'error');
        } else if (assistantEl) {
          assistantEl.remove();
          showNotice(error.message || `${companionName()} could not reply.`, 'error');
        } else {
          // Remove the optimistic user bubble only if nothing was accepted.
          if (!gotMeta) userArticle.remove();
          showNotice(error.message || `${companionName()} could not reply.`, 'error');
          if (!gotMeta) showEmptyState(inner().querySelectorAll('.msg').length === 0);
        }
        onConversation?.({ id: state.conversationId, updated: true });
      },
    }, controller.signal);

    state.streaming = null;
    setGenerating(false);
    if (gotMeta) showEmptyState(false);
    els.input.focus();
    // Live-voice mode needs the reply text itself, not just a boolean.
    return replyText !== null ? replyText : (gotMeta ? buffer : null);
  }

  function finalizeBubble(article, messageId, text) {
    if (!article) return;
    if (messageId) article.dataset.id = messageId;
    const content = article.querySelector('.msg-content');
    content.innerHTML = renderMarkdown(text);
    enhanceCodeBlocks(content);
    rawContent.set(content, text);
    article.querySelector('.msg-actions').innerHTML = `
      <button class="icon-btn" data-act="speak" title="Speak this reply" aria-label="Speak this reply"><i data-lucide="volume-2"></i></button>
      <button class="icon-btn" data-act="copy" title="Copy reply" aria-label="Copy reply"><i data-lucide="copy"></i></button>
      <button class="icon-btn" data-act="regenerate" title="Regenerate" aria-label="Regenerate reply"><i data-lucide="refresh-cw"></i></button>`;
    refreshIcons(article);
    scrollToEnd();
  }

  function stopGenerating() {
    if (!state.streaming) return;
    state.streaming.abort.abort();
    const article = state.streaming.assistantEl;
    if (article) {
      const buffer = state.streaming.buffer;
      if (buffer) finalizeBubble(article, null, buffer);
      else article.remove();
    }
    state.streaming = null;
    setGenerating(false);
    toast('Stopped.');
  }

  async function regenerate() {
    if (state.streaming || !state.lastPayload) return;
    const messages = [...inner().querySelectorAll('.msg.assistant')];
    const last = messages.at(-1);
    if (last) last.remove();
    const payload = state.lastPayload;
    await send({ text: payload.message, attachmentIds: payload.attachment_ids || [] });
  }

  /* ------------------------------------------------------------ speaking */

  function speakElement(article) {
    if (!article) return;
    const content = article.querySelector('.msg-content');
    const text = rawContent.get(content) || content.textContent || '';
    if (state.spokenEl === article && voice.isSpeaking()) {
      voice.stop();
      return;
    }
    const ok = voice.speak(text, { rate: prefs().rate, voiceURI: prefs().voiceURI, lang: prefs().lang });
    if (ok) {
      state.spokenEl = article;
      voice.onceEnded(() => {
        if (state.spokenEl === article) state.spokenEl = null;
      });
    } else {
      toast(voice.supported ? 'Nothing to speak.' : 'Speech output is not supported in this browser.');
    }
  }

  /* ------------------------------------------------------------- events */

  function autoResize() {
    els.input.style.height = 'auto';
    els.input.style.height = `${Math.min(els.input.scrollHeight, 190)}px`;
  }

  function submitCurrent() {
    const text = els.input.value;
    if (!text.trim() && attachments.count() === 0) return;
    if (attachments.busy()) {
      toast('Attachments are still uploading…');
      return;
    }
    send({ text, attachmentIds: attachments.readyIds() });
  }

  function bind() {
    document.getElementById('composer').addEventListener('submit', (event) => {
      event.preventDefault();
      submitCurrent();
    });

    els.input.addEventListener('input', () => {
      autoResize();
      els.send.disabled =
        state.streaming !== null || (!els.input.value.trim() && attachments.count() === 0);
    });

    els.input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      submitCurrent();
    });

    els.stopGen.addEventListener('click', stopGenerating);

    document.getElementById('suggestions')?.addEventListener('click', (event) => {
      const btn = event.target.closest('.suggestion');
      if (!btn) return;
      els.input.value = btn.textContent.trim();
      autoResize();
      els.send.disabled = false;
      els.input.focus();
    });

    // Message actions via delegation.
    els.messages.addEventListener('click', async (event) => {
      const copyCode = event.target.closest?.('[data-copy-code]');
      if (copyCode) {
        const code = copyCode.closest('.code-block')?.querySelector('code')?.textContent || '';
        try {
          await navigator.clipboard.writeText(code);
          copyCode.textContent = 'Copied!';
          setTimeout(() => { copyCode.textContent = 'Copy'; }, 1400);
        } catch { toast('Clipboard unavailable.'); }
        return;
      }

      const button = event.target.closest?.('[data-act]');
      if (!button) return;
      const article = button.closest('.msg');
      if (!article) return;
      const content = article.querySelector('.msg-content');
      const action = button.dataset.act;

      if (action === 'copy') {
        const text = rawContent.get(content) || content.textContent || '';
        try {
          await navigator.clipboard.writeText(text);
          toast('Copied.');
        } catch { toast('Clipboard unavailable.'); }
      } else if (action === 'speak') {
        speakElement(article);
      } else if (action === 'regenerate') {
        regenerate();
      }
    });
  }

  function loadConversation(conversation) {
    state.conversationId = conversation.id;
    setTitle(conversation.title);
    if (conversation.mode) els.mode.value = conversation.mode;
    return api.get(`/api/conversations/${conversation.id}`).then((detail) => {
      state.conversationId = detail.id;
      setTitle(detail.title);
      if (detail.mode) els.mode.value = detail.mode;
      renderHistory(detail.messages);
      return detail;
    });
  }

  function reset() {
    stopGenerating();
    state.conversationId = null;
    state.lastPayload = null;
    state.spokenEl = null;
    voice.stop();
    setTitle(companionName());
    clearMessages();
  }

  return {
    bind,
    send,
    /** Send one message and resolve with the assistant reply text (voice mode). */
    async sendAndReply(text) {
      if (state.streaming) stopGenerating();
      const result = await runSend(String(text ?? '').trim(), []);
      return typeof result === 'string' ? result : '';
    },
    stopGenerating,
    loadConversation,
    renderHistory,
    clearMessages,
    reset,
    state,
    getConversationId: () => state.conversationId,
    setConversationId: (id) => { state.conversationId = id; },
    isEmpty: () => inner().querySelectorAll('.msg').length === 0,
    focus: () => els.input.focus(),
  };
}
