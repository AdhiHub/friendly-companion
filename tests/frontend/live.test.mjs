// Tests for the hands-free live conversation state machine.
// No microphone, speaker, or network is involved: every dependency is a stub.

import test from 'node:test';
import assert from 'node:assert/strict';

import { createLiveConversation, liveStateLabel } from '../../app/static/js/voice.js';

/** Minimal recogniser stub mirroring the real factory's surface. */
function fakeRecognizer({ supported = true } = {}) {
  const calls = { start: 0, stop: 0, abort: 0 };
  let running = false;
  return {
    supported,
    calls,
    isRunning: () => running,
    start() {
      calls.start += 1;
      running = true;
      return true;
    },
    stop() {
      calls.stop += 1;
      running = false;
    },
    abort() {
      calls.abort += 1;
      running = false;
    },
  };
}

/** Synthesis stub that lets a test decide when speech "finishes". */
function fakeSynth({ available = true } = {}) {
  const spoken = [];
  let onDoneCb = null;
  return {
    spoken,
    // Mirrors createSynth: onDone receives { error } or null.
    finish(error = null) {
      const cb = onDoneCb;
      onDoneCb = null;
      cb?.(error ? { error } : null);
    },
    speak(text, opts = {}) {
      if (!available) return false;
      spoken.push(text);
      onDoneCb = opts.onDone || null;
      return true;
    },
    stop() { onDoneCb = null; },
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

test('liveStateLabel maps each state to a readable label', () => {
  assert.equal(liveStateLabel('listening'), 'Listening…');
  assert.equal(liveStateLabel('thinking'), 'Thinking…');
  assert.equal(liveStateLabel('speaking'), 'Speaking…');
  assert.equal(liveStateLabel('idle'), 'Ready');
  assert.equal(liveStateLabel('anything-else'), 'Ready');
});

test('start() begins listening and reports the state', () => {
  const rec = fakeRecognizer();
  const states = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => 'hi',
    onState: (s) => states.push(s),
  });

  live.start();

  assert.equal(live.isActive(), true);
  assert.equal(live.getState(), 'listening');
  assert.equal(rec.calls.start, 1);
  assert.deepEqual(states, ['listening']);
});

test('start() is a no-op when recognition is unsupported', () => {
  const rec = fakeRecognizer({ supported: false });
  const errors = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => 'hi',
    onError: (e) => errors.push(e),
  });

  live.start();

  assert.equal(live.isActive(), false);
  assert.equal(rec.calls.start, 0);
  assert.deepEqual(errors, ['not-supported']);
});

test('a full turn goes listening → thinking → speaking → listening', async () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  const states = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => 'Vanakkam da!',
    onState: (s) => states.push(s),
  });

  live.start();
  live.handleFinal('hello gethu');
  await flush();

  assert.equal(live.getState(), 'speaking');
  assert.deepEqual(synth.spoken, ['Vanakkam da!']);

  synth.finish();
  assert.equal(live.getState(), 'listening');
  assert.deepEqual(states, ['listening', 'thinking', 'speaking', 'listening']);
});

test('the mic is released before Gethu speaks (never hears itself)', async () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => 'reply',
  });

  live.start();
  live.handleFinal('hello');
  await flush();

  assert.equal(rec.calls.stop, 1, 'recogniser stopped before speaking');
  assert.equal(rec.isRunning(), false);
});

test('empty final transcripts keep the loop alive without sending', () => {
  const rec = fakeRecognizer();
  const sent = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async (t) => { sent.push(t); return 'x'; },
  });

  live.start();
  const handled = live.handleFinal('   ');

  assert.equal(handled, true);
  assert.deepEqual(sent, [], 'nothing was sent');
  assert.equal(live.getState(), 'listening');
});

test('handleFinal returns false when no live session is running', () => {
  const live = createLiveConversation({
    recognizer: fakeRecognizer(),
    synth: fakeSynth(),
    send: async () => 'x',
  });

  assert.equal(live.handleFinal('hello'), false);
  assert.equal(live.handleError('no-speech'), false);
  assert.equal(live.handleEnd(), false);
});

test('a speak failure reports the error and returns to listening', async () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  const errors = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => 'reply',
    onError: (e) => errors.push(e),
  });

  live.start();
  live.handleFinal('hello');
  await flush();
  assert.equal(live.getState(), 'speaking');

  // e.g. no installed voice: synthesis reports a non-cancel error.
  synth.finish('synthesis-failed');

  assert.deepEqual(errors, ['speak-failed']);
  assert.equal(live.getState(), 'listening', 'kept the conversation going');
  assert.equal(live.isActive(), true);
});

test('an empty assistant reply re-listens rather than speaking', async () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => '   ',
  });

  live.start();
  live.handleFinal('hello');
  await flush();

  assert.deepEqual(synth.spoken, []);
  assert.equal(live.getState(), 'listening');
});

test('a send failure ends the session with an error', async () => {
  const rec = fakeRecognizer();
  const errors = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => { throw Object.assign(new Error('nope'), { kind: 'network' }); },
    onError: (e) => errors.push(e),
  });

  live.start();
  live.handleFinal('hello');
  await flush();

  assert.deepEqual(errors, ['network']);
  assert.equal(live.isActive(), false);
  assert.equal(live.getState(), 'idle');
});

test('no-speech and aborted are treated as normal pauses', () => {
  const rec = fakeRecognizer();
  const errors = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => 'x',
    onError: (e) => errors.push(e),
  });

  live.start();
  assert.equal(live.handleError('no-speech'), true);
  assert.equal(live.isActive(), true, 'session survives a pause');
  assert.deepEqual(errors, []);
});

test('a fatal recognition error stops the session', () => {
  const rec = fakeRecognizer();
  const errors = [];
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => 'x',
    onError: (e) => errors.push(e),
  });

  live.start();
  live.handleError('not-allowed');

  assert.equal(live.isActive(), false);
  assert.equal(live.getState(), 'idle');
  assert.deepEqual(errors, ['not-allowed']);
  assert.equal(rec.calls.abort, 1);
});

test('stop() halts the loop and aborts both mic and speech', () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => 'x',
  });

  live.start();
  live.stop();

  assert.equal(live.isActive(), false);
  assert.equal(live.getState(), 'idle');
  assert.equal(rec.calls.abort, 1);
});

test('mid-flight replies are ignored after stop()', async () => {
  const rec = fakeRecognizer();
  const synth = fakeSynth();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });

  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => { await gate; return 'late reply'; },
  });

  live.start();
  live.handleFinal('hello');
  live.stop();
  release();
  await flush();

  assert.deepEqual(synth.spoken, [], 'stopped session does not speak');
  assert.equal(live.getState(), 'idle');
});

test('handleEnd re-listens only while still listening', () => {
  const rec = fakeRecognizer();
  const live = createLiveConversation({
    recognizer: rec,
    synth: fakeSynth(),
    send: async () => 'x',
  });

  live.start();
  assert.equal(rec.calls.start, 1);

  live.handleEnd();
  assert.equal(rec.calls.start, 2, 're-listened after a silent end');
});

test('a transcript is surfaced to the caller', async () => {
  const seen = [];
  const live = createLiveConversation({
    recognizer: fakeRecognizer(),
    synth: fakeSynth(),
    send: async () => 'ok',
    onTranscript: (t) => seen.push(t),
  });

  live.start();
  live.handleFinal('enna panra');
  await flush();

  assert.deepEqual(seen, ['enna panra']);
});

test('speech options are forwarded to the synth', async () => {
  const rec = fakeRecognizer();
  let received = null;
  const synth = {
    speak(text, opts) { received = opts; return true; },
    stop() {},
  };
  const live = createLiveConversation({
    recognizer: rec,
    synth,
    send: async () => 'reply',
    speechOpts: { voiceURI: 'v1', rate: 1.2, lang: 'en-IN', preferMale: true },
  });

  live.start();
  live.handleFinal('hi');
  await flush();

  assert.equal(received.voiceURI, 'v1');
  assert.equal(received.rate, 1.2);
  assert.equal(typeof received.onDone, 'function');
});
