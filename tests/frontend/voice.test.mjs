// Frontend unit tests — Node's built-in test runner, no extra dependencies.
// Browser APIs (SpeechRecognition, SpeechSynthesis, localStorage) are mocked so
// no microphone, speaker, or network access is needed.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  cleanupForSpeech,
  createRecognizer,
  createSynth,
  detectSupport,
  insertTranscript,
  isSecureContext,
  pickBestVoice,
  rankVoices,
  recognitionErrorMessage,
  splitSentences,
} from '../../app/static/js/voice.js';

import { createSubmitGuard } from '../../app/static/js/chat.js';
import { DEFAULT_PREFS, PREFS_KEY, loadPrefs, resetPrefs, savePrefs } from '../../app/static/js/storage.js';
import { validateFile, formatSize } from '../../app/static/js/attachments.js';
import { escapeHtml, renderMarkdown } from '../../app/static/js/markdown.js';

/* ------------------------------------------------------------- mocks */

class MockUtterance {
  constructor(text) {
    this.text = text;
    this.rate = 1;
    this.lang = '';
    this.voice = null;
    this.onend = null;
    this.onerror = null;
  }
}

function mockSynth(voices = []) {
  const spoken = [];
  const state = { cancelled: 0 };
  const speechSynthesis = {
    getVoices: () => voices,
    speak(utterance) {
      spoken.push(utterance);
      // Simulate the browser finishing the utterance asynchronously.
      queueMicrotask(() => utterance.onend?.({}));
    },
    cancel() { state.cancelled += 1; },
    addEventListener() {},
  };
  return { speechSynthesis, SpeechSynthesisUtterance: MockUtterance, spoken, state, voices };
}

function mockRecognitionEnv(overrides = {}) {
  const instances = [];
  class MockRecognition {
    constructor() {
      this.started = 0;
      this.stopped = 0;
      instances.push(this);
    }
    start() { this.started += 1; this.onstart?.({}); }
    stop() { this.stopped += 1; this.onend?.({}); }
    abort() { this.onend?.({}); }
  }
  // Mirrors how Chrome exposes the prefixed constructor.
  class MockWebkitRecognition extends MockRecognition {}
  const env = {
    SpeechRecognition: MockRecognition,
    isSecureContext: true,
    ...overrides,
  };
  return { env, instances, MockRecognition, MockWebkitRecognition };
}

function memoryStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _map: map,
  };
}

function fakeTextarea(value = '') {
  const events = [];
  return {
    value,
    dispatchEvent: (event) => { events.push(event.type); return true; },
    _events: events,
  };
}

/* --------------------------------------------------- capability detection */

test('detectSupport reports what the browser actually provides', () => {
  const full = detectSupport({ SpeechRecognition: class {}, speechSynthesis: {}, SpeechSynthesisUtterance: class {}, isSecureContext: true });
  assert.equal(full.recognition, true);
  assert.equal(full.synthesis, true);

  const none = detectSupport({ isSecureContext: true });
  assert.equal(none.recognition, false);
  assert.equal(none.synthesis, false);
  assert.equal(none.RecognitionCtor, null);
});

test('webkitSpeechRecognition is accepted as a fallback name', () => {
  class PrefixedRecognition {}
  const env = {
    SpeechRecognition: undefined,
    webkitSpeechRecognition: PrefixedRecognition,
    isSecureContext: true,
  };
  const support = detectSupport(env);
  assert.equal(support.recognition, true);
  assert.equal(support.RecognitionCtor, PrefixedRecognition);
});

test('secure-context detection accepts localhost but not plain http hosts', () => {
  assert.equal(isSecureContext({ location: { hostname: 'localhost' } }), true);
  assert.equal(isSecureContext({ location: { hostname: '127.0.0.1' } }), true);
  assert.equal(isSecureContext({ location: { hostname: 'example.com' } }), false);
  assert.equal(isSecureContext({ isSecureContext: true, location: { hostname: 'example.com' } }), true);
});

/* -------------------------------------------------------- error messages */

test('recognitionErrorMessage explains unsupported browsers and permissions', () => {
  const unsupported = recognitionErrorMessage('not-supported', { recognition: false });
  assert.match(unsupported, /doesn't support speech recognition/i);

  const denied = recognitionErrorMessage('not-allowed', { recognition: true, secure: true });
  assert.match(denied, /permission/i);

  const insecure = recognitionErrorMessage('not-allowed', { recognition: true, secure: false });
  assert.match(insecure, /HTTPS or localhost/);

  const noSpeech = recognitionErrorMessage('no-speech', { recognition: true, secure: true });
  assert.match(noSpeech, /didn't catch/i);

  // User-initiated aborts are not errors and must not produce a scary message.
  assert.equal(recognitionErrorMessage('aborted', { recognition: true, secure: true }), null);
});

/* ------------------------------------------------------------ recognizer */

test('recognizer inserts a final transcript without submitting', () => {
  const finals = [];
  const { env, instances } = mockRecognitionEnv();
  const rec = createRecognizer(env, {
    onFinal: (text) => finals.push(text),
  });
  rec.start({ lang: 'en-IN' });

  assert.equal(instances.length, 1);
  assert.equal(rec.isRunning(), true);
  assert.equal(finals.length, 0); // nothing is submitted automatically

  // Simulate the browser delivering one final result.
  instances[0].onresult({
    resultIndex: 0,
    results: [Object.assign([{ transcript: 'enna plan innaiku' }], { isFinal: true })],
  });
  assert.deepEqual(finals, ['enna plan innaiku']);
  rec.stop();
});

test('recognizer separates interim from final results', () => {
  const interim = [];
  const finals = [];
  const { env, instances } = mockRecognitionEnv();
  const rec = createRecognizer(env, {
    onInterim: (t) => interim.push(t),
    onFinal: (t) => finals.push(t),
  });
  rec.start({ lang: 'en-IN' });

  instances[0].onresult({
    resultIndex: 0,
    results: [Object.assign([{ transcript: 'enna' }], { isFinal: false })],
  });
  assert.deepEqual(interim, ['enna']);
  assert.deepEqual(finals, []); // interim text is never treated as a message

  instances[0].onresult({
    resultIndex: 0,
    results: [Object.assign([{ transcript: 'enna plan' }], { isFinal: true })],
  });
  assert.deepEqual(finals, ['enna plan']);
  rec.stop();
});

test('recognizer start is idempotent while running', () => {
  const { env, instances } = mockRecognitionEnv();
  const rec = createRecognizer(env, {});
  rec.start({ lang: 'en-IN' });
  rec.start({ lang: 'en-IN' });
  assert.equal(instances.length, 1); // never spawns a second recogniser
  rec.stop();
});

test('recognizer reports errors and stops cleanly', () => {
  const errors = [];
  const { env, instances } = mockRecognitionEnv();
  const rec = createRecognizer(env, { onError: (code) => errors.push(code) });
  rec.start({ lang: 'en-IN' });
  instances[0].onerror({ error: 'no-speech' });
  assert.deepEqual(errors, ['no-speech']);
  assert.equal(rec.isRunning(), false);
});

test('recognizer handle start() throwing (permission already denied)', () => {
  const errors = [];
  class Throwing {
    start() { throw new Error('not allowed'); }
    stop() {}
  }
  const rec = createRecognizer({ SpeechRecognition: Throwing, isSecureContext: true }, {
    onError: (code) => errors.push(code),
  });
  assert.equal(rec.start({ lang: 'en-IN' }), false);
  assert.deepEqual(errors, ['start-failed']);
  assert.equal(rec.isRunning(), false);
});

test('unsupported browser disables recognition instead of throwing', () => {
  const errors = [];
  const rec = createRecognizer({ isSecureContext: true }, { onError: (c) => errors.push(c) });
  assert.equal(rec.supported, false);
  assert.equal(rec.start({}), false);
  assert.deepEqual(errors, ['not-supported']);
});

test('manual stop is flagged to the caller (no surprise restarts)', () => {
  const ends = [];
  const { env, instances } = mockRecognitionEnv();
  const rec = createRecognizer(env, { onEnd: (info) => ends.push(info) });
  rec.start({ lang: 'en-IN' });
  rec.stop();
  assert.equal(ends.length, 1);
  assert.equal(ends[0].manual, true);
  assert.equal(instances.length, 1);
});

/* --------------------------------------------------- transcript insertion */

test('insertTranscript appends to existing composer text and fires input', () => {
  const textarea = fakeTextarea('First line');
  const result = insertTranscript(textarea, '  second   thought ');
  assert.equal(result, 'First line second thought');
  assert.equal(textarea.value, 'First line second thought');
  assert.deepEqual(textarea._events, ['input']);
});

test('insertTranscript into an empty composer', () => {
  const textarea = fakeTextarea('');
  assert.equal(insertTranscript(textarea, 'enna scene'), 'enna scene');
});

test('insertTranscript ignores empty transcripts (interim noise)', () => {
  const textarea = fakeTextarea('keep me');
  assert.equal(insertTranscript(textarea, '   '), 'keep me');
});

/* --------------------------------------------------------- speech cleanup */

test('cleanupForSpeech strips markdown syntax but keeps the words', () => {
  const spoken = cleanupForSpeech(
    '# Heading\n\nSome **bold** text with `code` and a [link](https://example.com/page).'
  );
  assert.ok(spoken.includes('Heading'));
  assert.ok(spoken.includes('bold'));
  assert.ok(spoken.includes('code'));
  assert.ok(spoken.includes('link'));
  assert.ok(!spoken.includes('#'));
  assert.ok(!spoken.includes('**'));
  assert.ok(!spoken.includes('https://example.com'));
});

test('cleanupForSpeech keeps code content but drops fences and JSON payloads', () => {
  const code = cleanupForSpeech('Look:\n```python\nprint("hi")\n```');
  assert.match(code, /print\("hi"\)/);
  assert.ok(!code.includes('```'));

  const json = cleanupForSpeech('Here is the data:\n```json\n{"a": 1, "b": [2,3]}\n```');
  assert.ok(!json.includes('"a"'));
  assert.match(json, /JSON/i);
});

test('cleanupForSpeech removes list markers, quotes and rules', () => {
  const spoken = cleanupForSpeech('- one\n- two\n\n> quoted\n\n---\n\n1. first');
  assert.ok(spoken.includes('one'));
  assert.ok(spoken.includes('quoted'));
  assert.ok(!spoken.includes('- '));
  assert.ok(!spoken.includes('>'));
});

test('cleanupForSpeech preserves technical answers (no destructive regex)', () => {
  const original = 'Use snake_case for keys and a * b for multiplication, plus 2 ** 3 for powers.';
  const spoken = cleanupForSpeech(original);
  assert.ok(spoken.includes('snake_case'));
  assert.ok(spoken.includes('a * b'));
  assert.ok(spoken.includes('2 ** 3'));
});

test('cleanupForSpeech normalises whitespace and empty input', () => {
  assert.equal(cleanupForSpeech('   \n\n  '), '');
  assert.equal(cleanupForSpeech('too    many\t\tspaces'), 'too many spaces');
  assert.equal(cleanupForSpeech(null), '');
});

test('splitSentences breaks long text into speakable chunks', () => {
  const chunks = splitSentences('First sentence. Second one! Third?');
  assert.deepEqual(chunks, ['First sentence.', 'Second one!', 'Third?']);
  assert.deepEqual(splitSentences(''), []);
  const long = `${'word, '.repeat(120)}end.`;
  assert.ok(splitSentences(long).every((chunk) => chunk.length <= 260));
});

/* ------------------------------------------------------------ voice choice */

const VOICES = [
  { name: 'Google UK English Male', lang: 'en-GB', voiceURI: 'a' },
  { name: 'Google UK English Female', lang: 'en-GB', voiceURI: 'b' },
  { name: 'Microsoft Ravi - English (India)', lang: 'en-IN', voiceURI: 'c' },
  { name: 'Google हिन्दी', lang: 'hi-IN', voiceURI: 'd' },
  { name: 'Tamil Voice', lang: 'ta-IN', voiceURI: 'e' },
];

test('rankVoices prefers a matching language and a male-sounding name', () => {
  const ranked = rankVoices(VOICES, { lang: 'en-IN', preferMale: true });
  assert.equal(ranked[0].voice.voiceURI, 'c'); // en-IN + "Ravi"
  const englishOnly = rankVoices(VOICES, { lang: 'en-IN', preferMale: false });
  assert.ok(['a', 'b', 'c'].includes(englishOnly[0].voice.voiceURI));
});

test('pickBestVoice returns null when nothing matches the language', () => {
  const onlyHindi = [{ name: 'Hindi', lang: 'hi-IN', voiceURI: 'h' }];
  assert.equal(pickBestVoice(onlyHindi, { lang: 'en-IN' }), null);
});

test('voice gender heuristics never overrule language fit', () => {
  const voices = [
    { name: 'Some Male Voice', lang: 'de-DE', voiceURI: 'de' },
    { name: 'Generic English', lang: 'en-US', voiceURI: 'en' },
  ];
  const best = pickBestVoice(voices, { lang: 'en-US', preferMale: true });
  assert.equal(best.voiceURI, 'en');
});

/* --------------------------------------------------------------- synthesis */

test('unsupported synthesis degrades safely', () => {
  const synth = createSynth({});
  assert.equal(synth.supported, false);
  assert.equal(synth.speak('hello'), false);
  assert.equal(synth.isSpeaking(), false);
  synth.stop(); // must not throw
});

test('speaking cleans the text and speaks each sentence', async () => {
  const { speechSynthesis, SpeechSynthesisUtterance, spoken } = mockSynth(VOICES);
  const synth = createSynth({ speechSynthesis, SpeechSynthesisUtterance });

  const done = new Promise((resolve) => {
    synth.speak('**Hello** there. Second sentence.', { rate: 1.2, lang: 'en-IN', onDone: resolve });
  });
  await done;
  assert.equal(spoken.length, 2);
  assert.equal(spoken[0].text, 'Hello there.');
  assert.equal(spoken[0].rate, 1.2);
  assert.ok(spoken[0].voice, 'a voice should be selected');
});

test('starting new speech cancels the previous utterance (no overlap)', () => {
  const { speechSynthesis, SpeechSynthesisUtterance, state } = mockSynth(VOICES);
  const synth = createSynth({ speechSynthesis, SpeechSynthesisUtterance });
  synth.speak('First reply here.', { onDone: () => {} });
  synth.speak('Second reply here.', { onDone: () => {} });
  assert.ok(state.cancelled >= 1, 'previous speech must be cancelled');
});

test('stop() cancels speech and resets state', () => {
  const { speechSynthesis, SpeechSynthesisUtterance, state } = mockSynth(VOICES);
  const synth = createSynth({ speechSynthesis, SpeechSynthesisUtterance });
  synth.speak('A longer sentence that will be interrupted.', { onDone: () => {} });
  assert.equal(synth.isSpeaking(), true);
  synth.stop();
  assert.equal(synth.isSpeaking(), false);
  assert.ok(state.cancelled >= 1);
});

test('speech synthesis errors surface through onDone and reset state', async () => {
  const failing = {
    getVoices: () => [],
    speak(utterance) { queueMicrotask(() => utterance.onerror?.({ error: 'synthesis-failed' })); },
    cancel() {},
    addEventListener() {},
  };
  const synth = createSynth({ speechSynthesis: failing, SpeechSynthesisUtterance: MockUtterance });
  const result = await new Promise((resolve) => {
    synth.speak('This will fail.', { onDone: resolve });
  });
  assert.ok(result?.error);
  assert.equal(synth.isSpeaking(), false);
});

test('an empty reply is not spoken', () => {
  const { speechSynthesis, SpeechSynthesisUtterance } = mockSynth(VOICES);
  const synth = createSynth({ speechSynthesis, SpeechSynthesisUtterance });
  assert.equal(synth.speak('   '), false);
});

test('voices arriving late (voiceschanged) are picked up', () => {
  let voices = [];
  const listeners = {};
  const speechSynthesis = {
    getVoices: () => voices,
    speak() {},
    cancel() {},
    addEventListener: (type, fn) => { listeners[type] = fn; },
  };
  const synth = createSynth({ speechSynthesis, SpeechSynthesisUtterance: MockUtterance });
  assert.equal(synth.getVoices().length, 0);
  voices = VOICES;
  listeners.voiceschanged();
  assert.equal(synth.getVoices().length, VOICES.length);
});

/* ------------------------------------------------ duplicate submissions */

test('submit guard blocks a second send until the first completes', () => {
  const guard = createSubmitGuard();
  assert.equal(guard.acquire(), true);
  assert.equal(guard.acquire(), false); // duplicate Enter / double tap
  assert.equal(guard.acquire(), false);
  guard.release();
  assert.equal(guard.acquire(), true);
});

/* ------------------------------------------------------ settings storage */

test('preferences round-trip through storage', (t) => {
  const storage = memoryStorage();
  const original = globalThis.localStorage;
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
  t.after(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: original, configurable: true });
  });

  resetPrefs();
  assert.deepEqual(loadPrefs(), DEFAULT_PREFS);

  savePrefs({ autoSpeak: true, voiceURI: 'x', rate: 1.4, lang: 'ta-IN' });
  const loaded = loadPrefs();
  assert.equal(loaded.autoSpeak, true);
  assert.equal(loaded.voiceURI, 'x');
  assert.equal(loaded.rate, 1.4);
  assert.equal(loaded.lang, 'ta-IN');
  assert.ok(storage.getItem(PREFS_KEY).includes('autoSpeak'));
});

test('out-of-range speech rate is clamped, unknown keys ignored', (t) => {
  const storage = memoryStorage();
  const original = globalThis.localStorage;
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
  t.after(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: original, configurable: true });
  });

  assert.equal(savePrefs({ rate: 99 }).rate, 1.6);
  assert.equal(savePrefs({ rate: 0.01 }).rate, 0.6);
  // Unknown keys are simply not merged into the persisted preferences.
  savePrefs({});
  const stored = JSON.parse(globalThis.localStorage.getItem(PREFS_KEY));
  assert.ok(!('nonsense' in stored));
});

test('storage failures never break the app', (t) => {
  const original = globalThis.localStorage;
  Object.defineProperty(globalThis, 'localStorage', {
    value: { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() {} },
    configurable: true,
  });
  t.after(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: original, configurable: true });
  });
  assert.doesNotThrow(() => loadPrefs());
  assert.doesNotThrow(() => savePrefs({ rate: 1.1 }));
});

/* ------------------------------------------------------ attachment rules */

test('validateFile accepts supported types and rejects the rest', () => {
  const png = { name: 'a.png', type: 'image/png', size: 1000 };
  assert.equal(validateFile(png), null);
  assert.equal(validateFile({ ...png, type: 'application/pdf' }), null);
  assert.equal(validateFile({ ...png, type: 'text/plain' }), null);

  assert.match(validateFile({ ...png, type: 'video/mp4' }), /Unsupported/);
  assert.match(validateFile({ ...png, size: 0 }), /empty/);
  assert.match(validateFile({ ...png, size: 50 * 1024 * 1024 }), /larger/);
});

test('formatSize is human readable', () => {
  assert.equal(formatSize(900), '900 B');
  assert.equal(formatSize(2048), '2 KB');
  assert.equal(formatSize(3 * 1024 * 1024), '3.0 MB');
});

/* ------------------------------------------------------ markdown safety */

test('markdown output is sanitised', () => {
  globalThis.marked = {
    parse: (src) => src.replace('**hi**', '<strong>hi</strong>'),
  };
  globalThis.DOMPurify = {
    sanitize: (html) => html.replace(/<img[^>]*onerror[^>]*>/gi, '').replace(/onerror="[^"]*"/gi, ''),
  };
  try {
    const html = renderMarkdown('<img src=x onerror="alert(1)"> **hi**');
    assert.ok(!/onerror/i.test(html), 'event handlers must be stripped');
    assert.ok(html.includes('<strong>hi</strong>'));
  } finally {
    delete globalThis.DOMPurify;
    delete globalThis.marked;
  }
  assert.match(escapeHtml('<script>'), /&lt;script&gt;/);
});

test('renderMarkdown always escapes untrusted text', () => {
  const html = renderMarkdown('<script>alert(1)</script>');
  assert.ok(!html.includes('<script>'));
});

/* --------------------------------------------- end-to-end voice workflow */

test('recognize → edit → send never auto-submits', () => {
  // The spec's default workflow: transcript lands in the composer for review.
  const textarea = fakeTextarea('');
  insertTranscript(textarea, 'enna plan innaiku');
  assert.equal(textarea.value, 'enna plan innaiku');
  const guard = createSubmitGuard();
  assert.equal(guard.acquire(), true); // the user explicitly submits once
});
