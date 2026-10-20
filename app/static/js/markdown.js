/* Markdown → sanitized HTML for assistant messages.
   Untrusted model output is always escaped/sanitised before insertion. */

export function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function fallbackMarkdown(text) {
  // No renderer available: escaped plain text with paragraph breaks.
  return escapeHtml(text)
    .split(/\n{2,}/)
    .map((para) => `<p>${para.replace(/\n/g, '<br>')}</p>`)
    .join('');
}

export function renderMarkdown(text) {
  const source = String(text ?? '');
  const markedLib = globalThis.marked;
  let html;
  if (markedLib?.parse) {
    try {
      html = markedLib.parse(source, { gfm: true, breaks: true, async: false });
    } catch {
      html = fallbackMarkdown(source);
    }
  } else {
    html = fallbackMarkdown(source);
  }

  const dompurify = globalThis.DOMPurify;
  if (dompurify?.sanitize) {
    return dompurify.sanitize(html, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ['style', 'form', 'input', 'button', 'iframe', 'object', 'embed'],
      FORBID_ATTR: ['style', 'onerror', 'onclick'],
    });
  }
  return fallbackMarkdown(source); // never return unsanitised HTML
}

/** Wrap bare <pre><code> blocks with a caption bar and copy button. */
export function enhanceCodeBlocks(root) {
  if (!root?.querySelectorAll) return;
  root.querySelectorAll('pre').forEach((pre) => {
    if (pre.parentElement?.classList.contains('code-block')) return;
    const code = pre.querySelector('code');
    const langClass = code?.className?.match(/language-([\w+-]+)/)?.[1] || '';
    const wrapper = document.createElement('div');
    wrapper.className = 'code-block';
    const head = document.createElement('div');
    head.className = 'code-block-head';
    const label = document.createElement('span');
    label.textContent = langClass || 'code';
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'code-copy';
    copy.textContent = 'Copy';
    copy.dataset.copyCode = '1';
    head.append(label, copy);
    pre.replaceWith(wrapper);
    wrapper.append(head, pre);
  });
}
