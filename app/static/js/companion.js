/* The companion's display name.
 *
 * The name is owned by the backend (it also goes into the system prompt), so
 * this module only mirrors it into the DOM and gives other modules a single
 * place to read it from.
 */

const DEFAULT_NAME = 'Gethu';

let currentName = DEFAULT_NAME;

export function getCompanionName() {
  return currentName;
}

/** The single letter used in the assistant's avatar bubble. */
export function getCompanionInitial() {
  return (currentName.trim()[0] || 'G').toUpperCase();
}

/**
 * Set the name and update every element that shows it.
 *
 * Elements opt in with `data-companion-name` (plain text) or
 * `data-companion-placeholder` (a template where `{name}` is replaced).
 */
export function setCompanionName(name) {
  const clean = String(name ?? '').trim() || DEFAULT_NAME;
  currentName = clean;

  // Guarded so the module stays usable outside a browser (unit tests, or a
  // future headless context) instead of throwing on a missing document.
  const doc = globalThis.document;
  if (!doc) return clean;

  doc.querySelectorAll?.('[data-companion-name]').forEach((node) => {
    node.textContent = clean;
  });
  doc.querySelectorAll?.('[data-companion-placeholder]').forEach((node) => {
    const template = node.getAttribute('data-companion-placeholder') || '';
    node.setAttribute('placeholder', template.replaceAll('{name}', clean));
  });

  doc.title = `${clean} — Your AI Companion`;
  return clean;
}

export { DEFAULT_NAME };
