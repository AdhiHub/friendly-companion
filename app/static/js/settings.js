/* Settings modal: connection status, model, voice output, voice input,
   theme and data management. Preferences persist in localStorage; nothing
   sensitive (API keys, permissions) is stored here. */

import { api } from './api.js';
import { detectSupport, rankVoices } from './voice.js';
import { setCompanionName } from './companion.js';

export function createSettingsPanel({
  els,
  synth,
  prefs,
  applyTheme,
  onClearHistory = null,
  onOpenWelcome = null,
  toast = () => {},
}) {
  const support = detectSupport(globalThis);

  function fillModels(settings) {
    const select = els.modelSelect;
    if (!select) return;
    const models = settings.available_models?.length
      ? settings.available_models
      : [settings.model];
    select.innerHTML = '';
    for (const name of models) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      option.selected = name === settings.model;
      select.append(option);
    }
  }

  function fillVoices() {
    const select = els.voiceSelect;
    if (!select) return;
    const voices = synth.getVoices();
    const ranked = rankVoices(voices, { lang: prefs().lang, preferMale: true });
    const current = prefs().voiceURI;
    select.innerHTML = '<option value="">Automatic (best fit)</option>';
    ranked.forEach(({ voice }, index) => {
      const option = document.createElement('option');
      option.value = voice.voiceURI;
      const suffix = index === 0 && ranked.length && ranked[0].score >= 4 ? ' — suggested' : '';
      option.textContent = `${voice.name} (${voice.lang})${suffix}`;
      if (voice.voiceURI === current) option.selected = true;
      select.append(option);
    });
    if (!voices.length) {
      const option = document.createElement('option');
      option.disabled = true;
      option.textContent = 'No browser voices available yet';
      select.append(option);
    }
  }

  async function refreshStatus() {
    try {
      const settings = await api.get('/api/settings');
      fillModels(settings);
      if (els.apiStatus) {
        els.apiStatus.textContent = settings.api_key_configured
          ? 'Key detected on the server.'
          : 'No key yet — paste one below to get started.';
      }
      if (els.apiPill) {
        els.apiPill.textContent = settings.api_key_configured ? 'Ready' : 'Missing';
        els.apiPill.className = `pill ${settings.api_key_configured ? 'ok' : 'err'}`;
      }
      if (els.name && document.activeElement !== els.name) {
        els.name.value = settings.companion_name || 'Gethu';
      }
      setCompanionName(settings.companion_name || 'Gethu');
    } catch (err) {
      if (els.apiStatus) els.apiStatus.textContent = err.message;
      if (els.apiPill) {
        els.apiPill.textContent = 'Offline';
        els.apiPill.className = 'pill err';
      }
    }
  }

  /** Save a new API key typed into the settings panel. */
  async function saveApiKey() {
    const key = (els.apiKeyInput?.value || '').trim();
    if (!key) {
      toast('Paste your Gemini API key first');
      els.apiKeyInput?.focus();
      return;
    }
    els.apiKeySave?.setAttribute('disabled', 'disabled');
    try {
      const result = await api.post('/api/settings/api-key', { api_key: key });
      if (els.apiKeyInput) els.apiKeyInput.value = '';
      toast(result.message || 'API key saved');
      await refreshStatus();
    } catch (err) {
      toast(err.message || 'Could not save that key');
    } finally {
      els.apiKeySave?.removeAttribute('disabled');
    }
  }

  /** Save a new companion name. */
  async function saveName() {
    const name = (els.name?.value || '').trim();
    if (!name) {
      toast('Give your companion a name');
      els.name?.focus();
      return;
    }
    try {
      const updated = await api.put('/api/settings', { companion_name: name });
      setCompanionName(updated.companion_name);
      toast(`Your companion is now called ${updated.companion_name}`);
    } catch (err) {
      toast(err.message);
    }
  }

  function syncFromPrefs() {
    const p = prefs();
    if (els.autospeak) els.autospeak.checked = Boolean(p.autoSpeak);
    if (els.rate) els.rate.value = String(p.rate);
    if (els.rateValue) els.rateValue.textContent = Number(p.rate).toFixed(1);
    if (els.lang) els.lang.value = p.lang;
    if (els.theme) els.theme.value = p.theme;
    if (els.voiceURI) els.voiceURI.value = p.voiceURI;
    if (els.support) {
      const parts = [];
      parts.push(support.recognition ? 'speech input ✓' : 'speech input ✗ not supported');
      parts.push(support.synthesis ? 'speech output ✓' : 'speech output ✗ not supported');
      if (support.recognition && !support.secure) parts.push('needs HTTPS or localhost');
      els.support.textContent = parts.join(' · ');
    }
    fillVoices();
  }

  function open() {
    els.modal.hidden = false;
    syncFromPrefs();
    refreshStatus();
    els.closeBtn?.focus();
  }

  function close() {
    if (els.modal) els.modal.hidden = true;
  }

  function bind() {
    els.openBtn?.addEventListener('click', open);
    els.closeBtn?.addEventListener('click', close);
    els.modal?.addEventListener('click', (event) => {
      if (event.target === els.modal) close();
    });

    els.autospeak?.addEventListener('change', () => {
      prefs({ autoSpeak: els.autospeak.checked });
    });

    els.voiceURI?.addEventListener('change', () => {
      prefs({ voiceURI: els.voiceURI.value });
      // Demo the selection so the user immediately hears what they picked.
      const voice = synth.pick(els.voiceURI.value);
      toast(voice ? `Voice set: ${voice.name}` : 'Automatic voice selected');
    });

    els.rate?.addEventListener('input', () => {
      const value = Number(els.rate.value);
      if (els.rateValue) els.rateValue.textContent = value.toFixed(1);
      prefs({ rate: value });
    });

    els.lang?.addEventListener('change', () => {
      prefs({ lang: els.lang.value });
    });

    els.model?.addEventListener('change', async () => {
      try {
        await api.put('/api/settings', { model: els.model.value });
        toast(`Model set to ${els.model.value}`);
      } catch (err) {
        toast(err.message);
        refreshStatus();
      }
    });

    els.name?.addEventListener('change', saveName);
    els.name?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveName();
      }
    });

    els.apiKeySave?.addEventListener('click', saveApiKey);
    els.apiKeyInput?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveApiKey();
      }
    });

    els.setupBtn?.addEventListener('click', () => {
      close();
      onOpenWelcome?.();
    });

    els.theme?.addEventListener('change', () => {
      prefs({ theme: els.theme.value });
      applyTheme(els.theme.value);
    });

    els.clearHistory?.addEventListener('click', async () => {
      const confirmed = globalThis.confirm?.(
        'Delete every conversation and message? This cannot be undone.'
      );
      if (!confirmed) return;
      try {
        const conversations = await api.get('/api/conversations');
        await Promise.all(conversations.map((c) => api.del(`/api/conversations/${c.id}`)));
        close();
        toast('Chat history cleared');
        onClearHistory?.();
      } catch (err) {
        toast(err.message);
      }
    });

    // Voices can arrive asynchronously in Chrome.
    synth.onChange(() => fillVoices());
    globalThis.setTimeout?.(fillVoices, 350);
  }

  function afterVoicePrefsChange() {
    syncFromPrefs();
  }

  return { open, close, bind, refreshStatus, syncFromPrefs: afterVoicePrefsChange };
}
