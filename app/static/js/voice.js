/* Gethu voice layer — browser SpeechRecognition (input) + SpeechSynthesis
   (output). Everything here is capability-detected at runtime; there is no
   assumption that a microphone, a male voice, or any speech API exists.

   This module never touches the DOM directly (except insertTranscript, which
   only uses the textarea it is given), so all of its logic is testable in Node
   with mocked browser APIs.
*/

/* ---------------------------------------------------------------- support */

export function isSecureContext(env = globalThis) {
  if (env.isSecureContext === true) return true;
  if (env.isSecureContext === false) return false;
  const host = env.location?.hostname;
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

export function detectSupport(env = globalThis) {
  const RecognitionCtor = env.SpeechRecognition || env.webkitSpeechRecognition || null;
  return {
    recognition: typeof RecognitionCtor === 'function',
    synthesis: Boolean(env.speechSynthesis) &&
      typeof env.SpeechSynthesisUtterance === 'function',
    RecognitionCtor,
    secure: isSecureContext(env),
  };
}

export function recognitionErrorMessage(code, support = {}) {
  if (!support.recognition || code === 'not-supported') {
    return "This browser doesn't support speech recognition. Chrome or Edge on desktop usually do.";
  }
  if (!support.secure && (code === 'not-allowed' || code === 'service-not-allowed')) {
    return 'Microphone access needs HTTPS or localhost — check how you opened Gethu.';
  }
  switch (code) {
    case 'not-allowed':
    case 'permission-denied':
      return "Microphone permission was blocked. Allow the microphone for this site, then try again.";
    case 'service-not-allowed':
      return 'The browser blocked its speech service. If you are on Brave, lower Shields for this site (the lion icon) — Brave blocks speech recognition by default. You can still type.';
    case 'no-speech':
      return "I didn't catch that — tap the mic and speak again.";
    case 'audio-capture':
      return 'No microphone was found. Check your input device.';
    case 'network':
      return 'Speech recognition needs the browser\'s speech service and could not reach it. On Brave, lower Shields for this site; otherwise check your network.';
    case 'language-not-supported':
      return 'This browser does not support the selected recognition language.';
    case 'aborted':
    case 'start-failed':
      return null; // user-driven or already reported
    default:
      return 'Speech recognition stopped unexpectedly. Try again.';
  }
}

/* ------------------------------------------------- text → spoken language */

function looksLikeJson(body) {
  const trimmed = body.trim();
  if (!trimmed || !/^[{[]/.test(trimmed)) return false;
  try {
    const parsed = JSON.parse(trimmed);
    return Boolean(parsed && typeof parsed === 'object');
  } catch {
    return false;
  }
}

/**
 * Convert an assistant Markdown reply into text that reads naturally aloud.
 * Never mutates the original message — the chat always shows the real text.
 *
 * Deliberately conservative: it strips syntax, never content. Emphasis markers
 * written with a single * or _ are left alone because those characters are
 * common in code and maths, where removal would corrupt meaning.
 */
export function cleanupForSpeech(raw) {
  let text = String(raw ?? '');

  // Fenced code blocks. JSON payloads become a short spoken placeholder;
  // other code keeps its content but loses the fences.
  text = text.replace(/```([\w+-]*)[ \t]*\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    const body = String(code).replace(/\s+$/, '');
    if (looksLikeJson(body)) return ' I sent the details as JSON — check the chat for the exact output. ';
    return ` ${body.replace(/\s+/g, ' ')} `;
  });
  // An unterminated fence (streaming cut off) — treat the remainder as code text.
  text = text.replace(/```([\w+-]*)[ \t]*\n?([\s\S]*)$/, (_m, _lang, code) =>
    ` ${String(code).replace(/\s+/g, ' ')} `
  );

  text = text.replace(/`([^`\n]+)`/g, '$1');       // inline code
  text = text.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1'); // images → alt text
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');  // links → link text
  text = text.replace(/<((?:https?:\/\/|mailto:)[^>\s]+)>/g, ' '); // <autolink>
  text = text.replace(/\bhttps?:\/\/\S+/g, ' ');   // bare URLs are unreadable aloud

  text = text.replace(/^\s{0,3}#{1,6}\s+/gm, '');  // headings
  text = text.replace(/^\s{0,3}[-*_]{3,}\s*$/gm, ' '); // horizontal rules
  text = text.replace(/^\s{0,3}>\s?/gm, '');       // blockquotes
  text = text.replace(/^\s*[-*+]\s+/gm, '');       // bullet markers
  text = text.replace(/^\s*\d+\.\s+/gm, '');       // ordered markers
  text = text.replace(/^\s*\[[ xX]\]\s+/gm, '');   // task checkboxes

  text = text.replace(/\*\*([^*\n]+)\*\*/g, '$1'); // **strong**
  text = text.replace(/__([^_\n]+)__/g, '$1');     // __strong__
  text = text.replace(/~~([^~\n]+)~~/g, '$1');     // ~~strike~~

  text = text.replace(/<\/?[a-zA-Z][^>\n]*>/g, ' '); // stray HTML
  text = text.replace(/^\s*---\s*[\s\S]*?^\s*---\s*$/m, ' '); // frontmatter
  text = text.replace(/\|/g, ' ');                 // table pipes

  text = text.replace(/[ \t]+/g, ' ');
  text = text.replace(/\s*\n\s*/g, ' ');
  return text.trim();
}

/** Split cleaned text into speakable chunks (~sentence level). */
export function splitSentences(text) {
  const source = String(text ?? '').trim();
  if (!source) return [];
  const parts = source
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const chunks = [];
  for (const part of parts) {
    if (part.length <= 220) {
      chunks.push(part);
      continue;
    }
    let current = '';
    for (const bit of part.split(/(?<=[,;:])\s+/)) {
      if (current && (current + ' ' + bit).length > 220) {
        chunks.push(current.trim());
        current = bit;
      } else {
        current = current ? `${current} ${bit}` : bit;
      }
    }
    if (current.trim()) chunks.push(current.trim());
  }
  return chunks;
}

/* ----------------------------------------------------------- voice choice */

const MALE_NAME_HINT =
  /\b(male|david|daniel|fred|thomas|arthur|alex|mark|james|george|philip|ravi|prabhat|hemant|kumar|guy)\b/i;
const FEMALE_NAME_HINT =
  /\b(female|samantha|zira|lisa|karen|moira|tessa|fiona|victoria|serena|heera|aditi|swara|kalpana|woman|girl)\b/i;

/**
 * Rank available voices. Gender is *never* guaranteed by the browser, so this
 * is a best-effort heuristic on top of language fit: language match always
 * outweighs the gender hint.
 */
export function rankVoices(voices, { lang = 'en-IN', preferMale = true } = {}) {
  const target = String(lang).replace('_', '-').toLowerCase();
  const primary = target.split('-')[0];

  return [...(voices || [])]
    .map((voice) => {
      const vlang = String(voice.lang || '').replace('_', '-').toLowerCase();
      const name = String(voice.name || '');
      let score = 0;
      if (vlang === target) score += 6;
      else if (vlang.split('-')[0] === primary) score += 4;
      else if (vlang.startsWith('en')) score += 2;

      const male = MALE_NAME_HINT.test(name);
      const female = FEMALE_NAME_HINT.test(name);
      if (preferMale) {
        if (male) score += 3;
        if (female) score -= 4;
      }
      if (voice.localService) score += 1;
      if (voice.default) score += 0.5;
      return { voice, score };
    })
    .sort((a, b) => b.score - a.score);
}

export function pickBestVoice(voices, opts = {}) {
  const ranked = rankVoices(voices, opts);
  if (!ranked.length) return null;
  // Only accept a "best" voice when it has at least some language affinity.
  return ranked[0].score >= 2 ? ranked[0].voice : null;
}

/* --------------------------------------------------------------- synthesis */

export function createSynth(env = globalThis) {
  const synth = env.speechSynthesis;
  const Utterance = env.SpeechSynthesisUtterance;
  const supported = Boolean(synth) && typeof Utterance === 'function';

  let voices = [];
  let state = 'idle';
  let session = 0;
  let queue = [];
  const listeners = new Set();

  function notify() {
    for (const fn of listeners) {
      try { fn({ state, voices, supported }); } catch { /* listener errors are not fatal */ }
    }
  }

  function refreshVoices() {
    if (!supported) return voices;
    try {
      voices = synth.getVoices() || [];
    } catch {
      voices = [];
    }
    notify();
    return voices;
  }

  if (supported) {
    refreshVoices();
    if (typeof synth.addEventListener === 'function') {
      synth.addEventListener('voiceschanged', refreshVoices);
    } else if ('onvoiceschanged' in synth) {
      synth.onvoiceschanged = refreshVoices;
    }
  }

  function findVoice(voiceURI) {
    if (!voiceURI) return null;
    return voices.find((v) => v.voiceURI === voiceURI) || null;
  }

  function speak(rawText, {
    voiceURI = '',
    lang = 'en-IN',
    rate = 1,
    preferMale = true,
    onDone = null,
    raw = false,
  } = {}) {
    if (!supported) return false;
    const text = raw ? String(rawText ?? '').trim() : cleanupForSpeech(rawText);
    if (!text) return false;

    stop(); // never overlap utterances

    const mySession = ++session;
    queue = splitSentences(text);
    state = 'speaking';
    notify();

    const finish = (error) => {
      if (mySession !== session) return;
      state = 'idle';
      queue = [];
      notify();
      if (onDone) onDone(error ? { error } : null);
    };

    const speakNext = () => {
      if (mySession !== session) return;
      const chunk = queue.shift();
      if (!chunk) {
        finish(null);
        return;
      }
      let utterance;
      try {
        utterance = new Utterance(chunk);
        const voice = findVoice(voiceURI) || pickBestVoice(voices, { lang, preferMale });
        if (voice) {
          utterance.voice = voice;
          utterance.lang = voice.lang;
        } else if (lang) {
          utterance.lang = lang;
        }
        utterance.rate = rate;
        utterance.onend = () => speakNext();
        utterance.onerror = (event) => {
          const code = event?.error;
          if (code === 'interrupted' || code === 'canceled') return; // we called stop()
          finish(code || 'error');
        };
        synth.speak(utterance);
      } catch {
        finish('error');
      }
    };

    speakNext();
    return true;
  }

  function stop() {
    session += 1;
    queue = [];
    if (supported) {
      try { synth.cancel(); } catch { /* some browsers throw when idle */ }
    }
    if (state !== 'idle') {
      state = 'idle';
      notify();
    }
  }

  return {
    supported,
    speak,
    stop,
    refreshVoices,
    getVoices: () => voices.slice(),
    isSpeaking: () => state === 'speaking',
    getState: () => state,
    onChange: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    pick: (voiceURI) => findVoice(voiceURI),
  };
}

/* ----------------------------------------------------------- recognition */

export function createRecognizer(env = globalThis, opts = {}) {
  const support = detectSupport(env);
  const Ctor = support.RecognitionCtor;

  let instance = null;
  let running = false;
  let manualStop = false;

  function finish() {
    running = false;
    instance = null;
  }

  return {
    supported: support.recognition,
    support,
    isRunning: () => running,
    start({ lang } = {}) {
      if (!support.recognition) {
        opts.onError?.('not-supported');
        return false;
      }
      if (running) return true; // idempotent: no duplicate recognisers

      let rec;
      try {
        rec = new Ctor();
      } catch {
        opts.onError?.('not-supported');
        return false;
      }
      instance = rec;
      manualStop = false;
      rec.lang = lang || opts.lang || 'en-IN';
      rec.interimResults = opts.interimResults !== false;
      rec.continuous = Boolean(opts.continuous); // one utterance by default
      rec.maxAlternatives = 1;

      rec.onstart = () => {
        running = true;
        opts.onStart?.();
      };
      rec.onresult = (event) => {
        let interim = '';
        let final = '';
        const start = typeof event.resultIndex === 'number' ? event.resultIndex : 0;
        for (let i = start; i < event.results.length; i += 1) {
          const result = event.results[i];
          const text = result?.[0]?.transcript ?? '';
          if (result?.isFinal) final += text;
          else interim += text;
        }
        if (interim.trim()) opts.onInterim?.(interim.trim());
        if (final.trim()) opts.onFinal?.(final.trim());
      };
      rec.onerror = (event) => {
        finish();
        opts.onError?.(event?.error || 'unknown');
      };
      rec.onend = () => {
        const wasManual = manualStop;
        finish();
        opts.onEnd?.({ manual: wasManual });
      };

      try {
        rec.start(); // may throw if permission is already denied
      } catch {
        finish();
        opts.onError?.('start-failed');
        return false;
      }
      running = true;
      return true;
    },
    stop() {
      manualStop = true;
      try { instance?.stop(); } catch { /* already stopped */ }
    },
    abort() {
      manualStop = true;
      try { instance?.abort?.(); } catch { /* already stopped */ }
      finish();
    },
    dispose() {
      this.abort();
      instance = null;
    },
  };
}

/* ------------------------------------------------------ live conversation */

/**
 * Hands-free voice conversation state machine.
 *
 *   idle -> listening -> thinking -> speaking -> listening -> ...
 *
 * Transport-agnostic: `send(text)` comes from the chat controller and
 * `speak(text)` from the synthesis layer, so every transition is testable
 * without a microphone or speaker.
 *
 * Safety rules:
 *  - the mic is aborted before speaking, so Gethu never hears itself;
 *  - one stop() (tap, Escape, unload) halts the whole loop;
 *  - empty/no-speech results re-listen instead of ending the session;
 *  - a hard error (permission denied) ends the session rather than looping.
 */
export function createLiveConversation({
  recognizer,
  synth,
  send,
  onState = () => {},
  onTranscript = () => {},
  onError = () => {},
  speechOpts = {},
} = {}) {
  let state = 'idle';
  let active = false;
  let ended = false;
  let turnInFlight = false;

  function setState(next) {
    if (state === next) return;
    state = next;
    try { onState(next); } catch { /* UI listeners must never break the loop */ }
  }

  function listen() {
    if (!active || ended) return;
    turnInFlight = false;
    setState('listening');
    const started = recognizer.start({ continuous: true });
    if (!started) {
      stop();
      onError('start-failed');
    }
  }

  async function think(text) {
    turnInFlight = true;
    setState('thinking');
    let reply = '';
    try {
      reply = await send(text);
    } catch (err) {
      onError(err?.kind || 'send-failed');
      stop();
      return;
    }
    if (!active || ended) return;
    if (!reply || !String(reply).trim()) {
      listen(); // nothing speakable — just listen again
      return;
    }
    speak(reply);
  }

  function speak(text) {
    setState('speaking');
    const spoken = synth.speak(text, {
      ...speechOpts,
      onDone: (result) => {
        if (!active || ended) return;
        if (result?.error && result.error !== 'interrupted' && result.error !== 'canceled') {
          onError('speak-failed');
        }
        listen();
      },
    });
    if (!spoken) listen(); // synthesis unavailable — keep the loop going
  }

  function start() {
    if (active) return;
    if (!recognizer.supported) {
      onError('not-supported');
      return;
    }
    active = true;
    ended = false;
    turnInFlight = false;
    listen();
  }

  function stop() {
    active = false;
    ended = true;
    turnInFlight = false;
    try { recognizer.abort?.(); } catch { /* ignore */ }
    try { synth.stop(); } catch { /* ignore */ }
    setState('idle');
  }

  return {
    start,
    stop,
    isActive: () => active,
    getState: () => state,
    /** Recogniser delivered a final transcript. Returns true if handled. */
    handleFinal(text) {
      if (!active || ended) return false;
      const clean = String(text ?? '').trim();
      if (!clean) return true; // swallow empties, stay in the loop
      onTranscript(clean);
      // One utterance per turn: release the mic before we play audio.
      try { recognizer.stop(); } catch { /* ignore */ }
      think(clean);
      return true;
    },
    /** Recogniser ended. Re-listen only when still idling in the loop. */
    handleEnd() {
      if (!active || ended) return false;
      if (!turnInFlight && state === 'listening') listen();
      return true;
    },
    /** Recogniser errored. Fatal codes end the session. */
    handleError(code) {
      if (!active || ended) return false;
      if (code === 'no-speech' || code === 'aborted') {
        if (!turnInFlight && state === 'listening') listen();
        return true;
      }
      onError(code);
      stop();
      return true;
    },
  };
}

/** Map a live-conversation state to a short human status label. */
export function liveStateLabel(state) {
  switch (state) {
    case 'listening': return 'Listening…';
    case 'thinking': return 'Thinking…';
    case 'speaking': return 'Speaking…';
    default: return 'Ready';
  }
}

/* --------------------------------------------------------------- composer */

/**
 * Insert recognised text into the composer for editing. Never submits.
 * Returns the resulting textarea value.
 */
export function insertTranscript(textarea, transcript) {
  if (!textarea) return '';
  const clean = String(transcript ?? '').replace(/\s+/g, ' ').trim();
  if (!clean) return textarea.value ?? '';

  const current = String(textarea.value ?? '');
  const joined = current.trim() ? `${current.trim()} ${clean}` : clean;
  textarea.value = joined;
  try {
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  } catch {
    /* non-DOM textarea in tests */
  }
  return joined;
}
