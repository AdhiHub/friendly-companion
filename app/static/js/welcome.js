/* First-run setup: name the companion and supply the Gemini API key.
 *
 * Shown automatically the first time the app opens without a key, and
 * reachable afterwards from Settings. Everything here is optional — the user
 * can skip and come back later.
 */

import { api } from './api.js';
import { setCompanionName } from './companion.js';

export function createWelcomeScreen({ els, onDone = () => {}, toast = () => {} }) {
  let shown = false;

  function setError(message) {
    if (!els.error) return;
    els.error.textContent = message ? String(message) : '';
    els.error.hidden = !message;
  }

  function setBusy(busy) {
    if (els.save) {
      els.save.disabled = busy;
      els.save.textContent = busy ? 'Saving…' : 'Start chatting';
    }
    if (els.skip) els.skip.disabled = busy;
  }

  function markActiveChip(name) {
    els.suggestions?.querySelectorAll('.chip').forEach((chip) => {
      chip.classList.toggle('active', chip.dataset.name === name);
    });
  }

  /** Pre-fill the form with the current values. */
  function fill(settings) {
    const name = settings?.companion_name || '';
    if (els.name) {
      els.name.value = name;
      markActiveChip(name);
    }
    if (els.brand) els.brand.textContent = name || 'Friendly Companion';
    // Only ask for the key when there isn't one already.
    const hasKey = Boolean(settings?.api_key_configured);
    if (els.keyStep) els.keyStep.hidden = hasKey;
    if (els.key) els.key.value = '';
    setError('');
  }

  function open(settings) {
    if (shown) return;
    shown = true;
    fill(settings);
    if (els.modal) els.modal.hidden = false;
    els.name?.focus();
  }

  function close() {
    shown = false;
    if (els.modal) els.modal.hidden = true;
  }

  /** Save the name and (if given) the API key. */
  async function save() {
    const name = (els.name?.value || '').trim();
    const key = (els.key?.value || '').trim();

    if (!name) {
      setError('Give your companion a name, or use the default.');
      els.name?.focus();
      return;
    }
    if (key) {
      // A key is supplied: check it before saving the name, so a bad key is
      // reported while the user is still looking at this screen.
      setBusy(true);
      setError('');
      try {
        await api.post('/api/settings/api-key', { api_key: key });
      } catch (err) {
        setBusy(false);
        setError(err.message || 'That key could not be saved.');
        els.key?.focus();
        return;
      }
      setBusy(false);
    }

    setBusy(true);
    setError('');
    try {
      const updated = await api.put('/api/settings', { companion_name: name });
      setCompanionName(updated.companion_name);
      close();
      toast('Setup complete. Say hello!');
      onDone(updated);
    } catch (err) {
      setError(err.message || 'Could not save your settings.');
    } finally {
      setBusy(false);
    }
  }

  function bind() {
    els.save?.addEventListener('click', save);
    els.skip?.addEventListener('click', () => {
      close();
      onDone(null);
    });

    els.name?.addEventListener('input', () => {
      markActiveChip(els.name.value.trim());
      setError('');
    });

    els.suggestions?.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      els.name.value = chip.dataset.name || '';
      markActiveChip(els.name.value);
      els.name.focus();
    });

    // Enter submits from either field.
    [els.name, els.key].forEach((field) => {
      field?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          save();
        }
      });
    });

    els.modal?.addEventListener('click', (event) => {
      // Clicking the backdrop skips: this screen must never trap someone.
      if (event.target === els.modal) {
        close();
        onDone(null);
      }
    });
  }

  return { open, close, bind, save, isOpen: () => shown };
}
