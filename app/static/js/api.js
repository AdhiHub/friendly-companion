/* Thin API client + SSE streaming over fetch. The Gemini key never reaches
   this file — everything goes through the local backend. */

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'http' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
  }
}

function friendlyDetail(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const first = detail[0]?.msg;
    if (first) return first;
  }
  if (status === 413) return 'That file is too large.';
  if (status === 404) return 'Not found.';
  if (status >= 500) return 'Gethu had a server problem. Try again.';
  return `Request failed (${status}).`;
}

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof FormData) {
      options.body = body;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("Can't reach the Gethu server. Is it running?", { status: 0, kind: 'network' });
  }
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch { /* non-JSON error body */ }
    throw new ApiError(friendlyDetail(payload, response.status), {
      status: response.status,
      kind: payload?.kind || 'http',
    });
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  patch: (path, body) => request('PATCH', path, body),
  put: (path, body) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
};

export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file, file.name);
  return request('POST', '/api/attachments', form);
}

/**
 * POST /api/chat and consume the SSE stream.
 *
 * handlers: { onMeta, onDelta, onDone, onError } — each optional.
 * Returns { abort() } and resolves when the stream ends.
 */
export async function streamChat(payload, handlers = {}, signal) {
  let response;
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    handlers.onError?.({ message: "Can't reach the Gethu server.", kind: 'network' });
    return;
  }

  if (!response.ok) {
    let payloadJson = null;
    try { payloadJson = await response.json(); } catch { /* ignore */ }
    const message = friendlyDetail(payloadJson, response.status);
    handlers.onError?.({ message, kind: payloadJson?.kind || 'http' });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    handlers.onError?.({ message: 'Streaming is unavailable in this browser.', kind: 'stream' });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (frame) => {
    let eventName = 'message';
    let data = '';
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (!data) return;
    let parsed;
    try { parsed = JSON.parse(data); } catch { return; }
    if (eventName === 'meta') handlers.onMeta?.(parsed);
    else if (eventName === 'delta') handlers.onDelta?.(parsed);
    else if (eventName === 'done') handlers.onDone?.(parsed);
    else if (eventName === 'error') handlers.onError?.(parsed);
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        dispatch(frame);
      }
    }
    if (buffer.trim()) dispatch(buffer);
  } catch (err) {
    if (err?.name === 'AbortError') return; // user pressed stop — not an error
    handlers.onError?.({ message: 'The reply stream was interrupted.', kind: 'stream' });
  } finally {
    try { reader.releaseLock(); } catch { /* ignore */ }
  }
}
