/* Composer attachments: pick / drag-drop, client-side validation, upload with
   progress chips, and removal before sending. */

import { uploadFile } from './api.js';

export const ACCEPTED_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'application/pdf',
  'text/plain',
]);

export const DEFAULT_MAX_BYTES = 20 * 1024 * 1024;

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateFile(file, maxBytes = DEFAULT_MAX_BYTES) {
  if (!ACCEPTED_TYPES.has(file.type)) {
    return 'Unsupported file — use a JPEG, PNG, WebP image, PDF, or plain text file.';
  }
  if (file.size > maxBytes) {
    return `File is larger than the ${formatSize(maxBytes)} limit.`;
  }
  if (file.size === 0) return 'That file is empty.';
  return null;
}

export function createAttachmentManager({
  fileInput,
  previewsEl,
  dropTargetEl,
  maxBytes = DEFAULT_MAX_BYTES,
  onChange = null,
  onError = null,
}) {
  let items = [];
  let counter = 0;

  function readyIds() {
    return items.filter((i) => i.status === 'ready' && i.id).map((i) => i.id);
  }

  function emitChange() {
    onChange?.(readyIds());
  }

  function render() {
    if (!previewsEl) return;
    previewsEl.hidden = items.length === 0;
    previewsEl.innerHTML = '';
    for (const item of items) {
      const chip = document.createElement('div');
      chip.className = `att-chip${item.status === 'failed' ? ' failed' : ''}`;

      const isImage = item.file.type.startsWith('image/');
      const thumb = document.createElement(isImage && item.url ? 'img' : 'span');
      thumb.className = 'att-thumb';
      if (isImage && item.url) {
        thumb.src = item.url;
        thumb.alt = '';
      } else {
        thumb.textContent = item.file.type === 'application/pdf' ? 'PDF' : 'TXT';
        thumb.style.fontSize = '9.5px';
        thumb.style.fontWeight = '700';
      }

      const body = document.createElement('div');
      body.style.minWidth = '0';
      body.style.flex = '1';
      const name = document.createElement('div');
      name.className = 'att-name';
      name.textContent = item.file.name;
      const state = document.createElement('div');
      state.className = 'att-state';
      state.textContent =
        item.status === 'ready' ? formatSize(item.file.size)
          : item.status === 'uploading' ? 'Uploading…'
            : item.error || 'Failed';
      body.append(name, state);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'icon-btn';
      removeBtn.title = 'Remove attachment';
      removeBtn.setAttribute('aria-label', `Remove ${item.file.name}`);
      removeBtn.dataset.attRemove = String(item.localId);
      removeBtn.innerHTML = '<span aria-hidden="true">×</span>';

      chip.append(thumb, body, removeBtn);
      previewsEl.append(chip);
    }
  }

  async function add(fileList) {
    for (const file of Array.from(fileList || [])) {
      const problem = validateFile(file, maxBytes);
      if (problem) {
        onError?.(problem);
        continue;
      }
      const item = {
        localId: `att_${counter += 1}`,
        file,
        url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
        id: null,
        status: 'uploading',
        error: null,
      };
      items.push(item);
      render();
      try {
        const info = await uploadFile(file);
        item.id = info.id;
        item.status = 'ready';
      } catch (err) {
        item.status = 'failed';
        item.error = err?.message || 'Upload failed.';
        onError?.(item.error);
      }
      render();
      emitChange();
    }
  }

  function remove(localId) {
    const target = items.find((i) => String(i.localId) === String(localId));
    if (target?.url) URL.revokeObjectURL(target.url);
    items = items.filter((i) => i !== target);
    render();
    emitChange();
  }

  function clear() {
    for (const item of items) if (item.url) URL.revokeObjectURL(item.url);
    items = [];
    if (fileInput) fileInput.value = '';
    render();
    emitChange();
  }

  function busy() {
    return items.some((i) => i.status === 'uploading');
  }

  function bind() {
    fileInput?.addEventListener('change', () => {
      if (fileInput.files?.length) add(fileInput.files);
      fileInput.value = ''; // allow re-picking the same file
    });

    previewsEl?.addEventListener('click', (event) => {
      const btn = event.target.closest?.('[data-att-remove]');
      if (btn) remove(btn.dataset.attRemove);
    });

    if (dropTargetEl) {
      const setActive = (on) => dropTargetEl.classList.toggle('dragover', on);
      ['dragenter', 'dragover'].forEach((type) =>
        dropTargetEl.addEventListener(type, (event) => {
          event.preventDefault();
          setActive(true);
        })
      );
      ['dragleave', 'drop'].forEach((type) =>
        dropTargetEl.addEventListener(type, (event) => {
          event.preventDefault();
          if (type === 'drop') {
            setActive(false);
            if (event.dataTransfer?.files?.length) add(event.dataTransfer.files);
          } else if (event.relatedTarget === null || !dropTargetEl.contains(event.relatedTarget)) {
            setActive(false);
          }
        })
      );
    }
  }

  return { add, remove, clear, bind, readyIds, busy, count: () => items.length };
}
