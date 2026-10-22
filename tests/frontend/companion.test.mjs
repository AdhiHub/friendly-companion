// Frontend unit tests — Node's built-in test runner, no extra dependencies.
// A minimal DOM stand-in is used for the parts of the companion-name module
// that touch the document.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_NAME,
  getCompanionInitial,
  getCompanionName,
  setCompanionName,
} from '../../app/static/js/companion.js';

/* ------------------------------------------------------------- DOM stub */

function makeNode(attrs = {}) {
  return {
    textContent: '',
    attrs: { ...attrs },
    getAttribute(name) {
      return this.attrs[name] ?? null;
    },
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
  };
}

function installDom(nodes, placeholderNodes = []) {
  const original = globalThis.document;
  globalThis.document = {
    title: '',
    querySelectorAll(selector) {
      if (selector === '[data-companion-name]') return nodes;
      if (selector === '[data-companion-placeholder]') return placeholderNodes;
      return [];
    },
  };
  return () => {
    globalThis.document = original;
  };
}

/* --------------------------------------------------------------- tests */

test('the default name is Friendly Companion', () => {
  const restore = installDom([]);
  try {
    setCompanionName('');
    assert.equal(getCompanionName(), DEFAULT_NAME);
    assert.equal(DEFAULT_NAME, 'Friendly Companion');
  } finally {
    restore();
  }
});

test('setting a name updates the page title', () => {
  const restore = installDom([]);
  try {
    setCompanionName('Mithu');
    assert.equal(getCompanionName(), 'Mithu');
    assert.equal(globalThis.document.title, 'Mithu — Your AI Companion');
  } finally {
    restore();
  }
});

test('setting a name updates every element that shows it', () => {
  const brand = makeNode();
  const title = makeNode();
  const restore = installDom([brand, title]);
  try {
    setCompanionName('Sahai');
    assert.equal(brand.textContent, 'Sahai');
    assert.equal(title.textContent, 'Sahai');
  } finally {
    restore();
  }
});

test('placeholders use the name in the template', () => {
  const input = makeNode({ 'data-companion-placeholder': 'Message {name}…' });
  const restore = installDom([], [input]);
  try {
    setCompanionName('Yaali');
    assert.equal(input.getAttribute('placeholder'), 'Message Yaali…');
  } finally {
    restore();
  }
});

test('a blank name falls back to the default', () => {
  const restore = installDom([]);
  try {
    setCompanionName('   ');
    assert.equal(getCompanionName(), DEFAULT_NAME);
  } finally {
    restore();
  }
});

test('the avatar letter comes from the name', () => {
  const restore = installDom([]);
  try {
    setCompanionName('Mithu');
    assert.equal(getCompanionInitial(), 'M');
    setCompanionName('yaali');
    assert.equal(getCompanionInitial(), 'Y');
    setCompanionName('Sahai bro');
    assert.equal(getCompanionInitial(), 'S');
  } finally {
    restore();
  }
});
