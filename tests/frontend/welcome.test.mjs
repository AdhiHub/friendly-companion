// Frontend unit tests — Node's built-in test runner, no extra dependencies.
// The welcome screen talks to the API through a mocked `fetch`, so no network
// access is needed.

import test from 'node:test';
import assert from 'node:assert/strict';

import { createWelcomeScreen } from '../../app/static/js/welcome.js';

/* ------------------------------------------------------------- helpers */

function makeEls() {
  return {
    modal: { hidden: true },
    name: { value: '', focus() {}, addEventListener() {} },
    key: { value: '', focus() {}, addEventListener() {} },
    keyStep: { hidden: false },
    brand: { textContent: '' },
    error: { textContent: '', hidden: true },
    save: { disabled: false, textContent: 'Start chatting', addEventListener() {} },
    skip: { disabled: false, addEventListener() {} },
    suggestions: {
      addEventListener() {},
      querySelectorAll() {
        return [];
      },
    },
  };
}

/**
 * Replace global fetch with a stub. `routes` maps "METHOD /path" to a handler
 * returning { status, body }.
 */
function installFetch(routes) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    calls.push({ method, path, body: options.body ? JSON.parse(options.body) : null });
    const handler = routes[`${method} ${path}`];
    if (!handler) {
      return {
        ok: false,
        status: 404,
        json: async () => ({ detail: 'no route' }),
      };
    }
    const { status = 200, body = {} } = handler;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    };
  };
  return {
    calls,
    restore() {
      globalThis.fetch = original;
    },
  };
}

/* --------------------------------------------------------------- tests */

test('the key step is hidden when a key already exists', () => {
  const els = makeEls();
  const screen = createWelcomeScreen({ els });
  screen.open({ companion_name: 'Mithu', api_key_configured: true });
  assert.equal(els.keyStep.hidden, true);
  assert.equal(els.name.value, 'Mithu');
  assert.equal(els.modal.hidden, false);
});

test('the key step is shown when there is no key', () => {
  const els = makeEls();
  const screen = createWelcomeScreen({ els });
  screen.open({ companion_name: 'Friendly Companion', api_key_configured: false });
  assert.equal(els.keyStep.hidden, false);
});

test('saving only the name does not touch the key endpoint', async () => {
  const els = makeEls();
  const stub = installFetch({
    'PUT /api/settings': { body: { companion_name: 'Mithu' } },
  });
  try {
    const screen = createWelcomeScreen({ els });
    screen.open({ companion_name: 'Friendly Companion', api_key_configured: true });
    els.name.value = 'Mithu';
    await screen.save();
    assert.deepEqual(
      stub.calls.map((c) => `${c.method} ${c.path}`),
      ['PUT /api/settings'],
    );
    assert.equal(els.modal.hidden, true);
  } finally {
    stub.restore();
  }
});

test('a name and a key are both sent when both are given', async () => {
  const els = makeEls();
  const stub = installFetch({
    'POST /api/settings/api-key': { body: { ok: true } },
    'PUT /api/settings': { body: { companion_name: 'Mithu' } },
  });
  try {
    const screen = createWelcomeScreen({ els });
    screen.open({ companion_name: 'Friendly Companion', api_key_configured: false });
    els.name.value = 'Mithu';
    els.key.value = 'AIzaSyD-ExampleKey_1234567890abcdef';
    await screen.save();
    assert.deepEqual(
      stub.calls.map((c) => `${c.method} ${c.path}`),
      ['POST /api/settings/api-key', 'PUT /api/settings'],
    );
    assert.equal(stub.calls[0].body.api_key, 'AIzaSyD-ExampleKey_1234567890abcdef');
  } finally {
    stub.restore();
  }
});

test('a blank name is refused before anything is sent', async () => {
  const els = makeEls();
  const stub = installFetch({});
  try {
    const screen = createWelcomeScreen({ els });
    screen.open({ companion_name: 'Friendly Companion', api_key_configured: true });
    els.name.value = '   ';
    await screen.save();
    assert.equal(stub.calls.length, 0);
    assert.equal(els.error.hidden, false);
    assert.match(els.error.textContent, /name/i);
  } finally {
    stub.restore();
  }
});

test('a key rejected by the server is reported and the screen stays open', async () => {
  const els = makeEls();
  const stub = installFetch({
    'POST /api/settings/api-key': {
      status: 400,
      body: { detail: 'Gemini rejected that key.' },
    },
  });
  try {
    const screen = createWelcomeScreen({ els });
    screen.open({ companion_name: 'Friendly Companion', api_key_configured: false });
    els.name.value = 'Mithu';
    els.key.value = 'AIzaSyD-ExampleKey_1234567890abcdef';
    await screen.save();
    assert.equal(els.error.hidden, false);
    assert.match(els.error.textContent, /rejected/i);
    assert.equal(els.modal.hidden, false);
    // The name was not saved while the key was still failing.
    assert.equal(stub.calls.length, 1);
  } finally {
    stub.restore();
  }
});

test('skipping closes the screen without saving anything', async () => {
  const els = makeEls();
  const stub = installFetch({});
  let done = false;
  try {
    const screen = createWelcomeScreen({ els, onDone: () => { done = true; } });
    screen.open({ companion_name: 'Friendly Companion', api_key_configured: false });
    els.skip.dispatch?.();
    assert.equal(stub.calls.length, 0);
  } finally {
    stub.restore();
  }
});

test('the screen cannot be reopened over itself', () => {
  const els = makeEls();
  const screen = createWelcomeScreen({ els });
  screen.open({ companion_name: 'Friendly Companion', api_key_configured: false });
  const first = els.name.value;
  els.name.value = 'Changed';
  screen.open({ companion_name: 'Other', api_key_configured: false });
  // The second open is ignored, so the in-progress edit is not thrown away.
  assert.equal(els.name.value, 'Changed');
  assert.equal(first, 'Friendly Companion');
});
