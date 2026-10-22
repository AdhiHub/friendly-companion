/* Local preference storage. Non-sensitive UI preferences only — never secrets,
   never microphone permission (browsers own that). */

export const PREFS_KEY = 'companion.prefs.v1';

export const DEFAULT_PREFS = {
  theme: 'dark',
  voiceEnabled: true,   // voice output master toggle
  autoSpeak: false,     // speak completed replies automatically
  voiceURI: '',         // preferred SpeechSynthesis voice
  rate: 1.0,            // speaking speed
  lang: 'en-IN',        // speech recognition language
  mode: 'friendly',     // last conversation mode
};

function getStorage() {
  try {
    const s = globalThis.localStorage;
    const probe = '__companion_probe__';
    s.setItem(probe, '1');
    s.removeItem(probe);
    return s;
  } catch {
    return null; // storage blocked (private mode) — run with in-memory defaults
  }
}

let memoryStore = null;

export function loadPrefs() {
  const storage = getStorage();
  if (!storage) return { ...DEFAULT_PREFS, ...(memoryStore || {}) };
  try {
    const raw = storage.getItem(PREFS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return { ...DEFAULT_PREFS, ...(parsed && typeof parsed === 'object' ? parsed : {}) };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function savePrefs(patch) {
  const next = { ...loadPrefs(), ...patch };
  // clamp numeric range
  next.rate = Math.min(1.6, Math.max(0.6, Number(next.rate) || 1));
  const storage = getStorage();
  if (!storage) {
    memoryStore = next;
    return next;
  }
  try {
    storage.setItem(PREFS_KEY, JSON.stringify(next));
  } catch {
    memoryStore = next;
  }
  return next;
}

export function resetPrefs() {
  const storage = getStorage();
  try {
    storage?.removeItem(PREFS_KEY);
  } catch { /* ignore */ }
  memoryStore = null;
  return { ...DEFAULT_PREFS };
}
