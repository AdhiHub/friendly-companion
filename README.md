# Gethu — Your Personal AI Companion

Gethu is a local, free-to-start personal AI companion: a friendly FastAPI +
Gemini chat app with a professional dark UI, natural **Tanglish** conversation,
voice input/output through your browser, and image/document sharing.

It runs on your own machine and talks to Google Gemini for replies. No paid
voice subscription, no separate speech server, no cloud database.

---

## What it does

**Conversation**
- Streams Gemini replies token-by-token as they are generated.
- Replies in natural Romanized Tanglish or English by default (never Tamil script
  unless you explicitly ask).
- Five conversation modes: **Friendly**, **Respectful**, **Playful** (light
  roast), **Supportive**, **Focused**.
- Remembers context within the active conversation and trims history to a
  bounded size automatically.

**Voice**
- Speech **input** via the browser Web Speech API — dictation lands in the
  composer so you can edit before sending.
- Speech **output** via the browser SpeechSynthesis API, with male-voice
  preference, speed control and a per-message speak button.
- Auto-speak toggle, stop-speaking control, and clear unsupported-browser /
  permission messages.
- Markdown is cleaned before speaking, so Gethu never reads `#`, `**`, code
  fences or JSON aloud.
- **Live conversation mode** — tap the radio button and talk hands-free. The
  loop runs *listening → thinking → speaking → listening* until you stop it,
  releasing the microphone before each reply so Gethu never hears itself.

**Files**
- Attach JPEG, PNG, WebP images, PDF and plain-text files (drag-drop or picker).
- The real file bytes are sent to Gemini, so you can ask questions about them.
- Files are validated by content (not extension), size-limited, stored under
  generated names, and never executed.

**Chat history**
- Conversations, messages, modes and attachment metadata persist in local SQLite.
- Search, rename, delete, clear-all (with confirmation).
- Everything survives a restart.

**UI**
- Dark theme (default) with an optional light theme.
- Responsive sidebar (collapsible drawer on mobile), header controls, settings
  modal, empty-state suggestions, streaming indicator, copy-code and per-message
  copy/regenerate.
- Errors are shown in a plain-language notice bar — never raw tracebacks.

---

## Requirements

- **Python 3.11+** (developed and tested on 3.12).
- A **Gemini API key** from <https://aistudio.google.com/apikey> (the free tier
  is enough to start).
- A modern browser. **Chrome or Edge** for voice input (see
  [Voice support](#gethu-voice-setup)); any current browser for text chat.

---

## Install

### Windows (PowerShell)

```powershell
git clone <your-repo-url> gethu-companion   # or copy the folder
cd gethu-companion
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env      # paste your GEMINI_API_KEY
```

### macOS / Linux

```bash
cd gethu-companion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
$EDITOR .env      # paste your GEMINI_API_KEY
```

> On Debian/Ubuntu, if `python3 -m venv` complains about `ensurepip`, install
> `python3-venv` (`sudo apt install python3.12-venv`) first.

## Configure

`.env` (copied from `.env.example`) is the only place secrets live:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | **Required.** Your key. Never committed, never sent to the browser. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Default model. |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.6-flash,gemini-3.8-flash,gemini-flash-latest` | Tried in order if the chosen model isn't available to your account. |
| `GETHU_HOST` | `127.0.0.1` | Bind address. Keep local unless you secured the app. |
| `GETHU_PORT` | `8000` | Server port. |
| `MAX_UPLOAD_MB` | `20` | Attachment size limit. |
| `MAX_HISTORY_MESSAGES` | `40` | Context window sent to Gemini per request. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |

`.env`, the SQLite database, and uploads are all in `.gitignore`.

**Choosing a model:** Gemini model availability changes over time. The defaults
are current stable Flash models; the app automatically falls back through
`GEMINI_FALLBACK_MODELS` if a model returns "unavailable" for your account, and
you can pick any other model in **Settings → Model**.

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open **<http://127.0.0.1:8000>**.

Startup check: <http://127.0.0.1:8000/api/health> should return
`"status":"ok"` and `"api_key_configured":true`.

## Test

```bash
pytest                                  # 54 backend tests (Gemini mocked)
ruff check app tests                    # lint
node --test "tests/frontend/*.test.mjs" # 39 frontend tests (browser APIs mocked)
```

Frontend tests need Node 18+ and no extra packages. They mock
`SpeechRecognition`, `SpeechSynthesis` and `localStorage`, so no microphone,
speaker, network or API key is required.

---

## Gethu Voice Setup

### Supported browsers

| Feature | Chrome / Edge | Firefox | Safari |
| --- | --- | --- | --- |
| Speech input (`SpeechRecognition`) | ✅ (Chrome & Edge) | ❌ not implemented | ⚠️ partial, `webkitSpeechRecognition` |
| Speech output (`SpeechSynthesis`) | ✅ | ✅ | ✅ |
| Male voice available | Usually (device/OS voices) | Depends on OS voices | Depends on OS voices |

Gethu detects capabilities at runtime. If `SpeechRecognition` /
`webkitSpeechRecognition` is missing, the mic button is disabled and a message
explains that you can type instead. Nothing else breaks.

### Microphone permission

- Gethu only asks for the microphone **after you click the mic button** — never on
  page load, never silently.
- Browsers require a **secure context**: `http://127.0.0.1` / `http://localhost`
  count as secure. If you open the app over a LAN IP or plain HTTP, speech input
  may be blocked; the app tells you when that happens.
- Denied permission shows a clear message: *"Microphone permission was blocked.
  Allow the microphone for this site, then try again."* Re-allow it in the
  browser's site settings (padlock icon in the address bar).

### Using voice input

1. Click the **mic** button.
2. Speak. Interim words appear in the listening banner, final text is inserted
   into the composer.
3. **Edit the text** if the recogniser misheard you.
4. Press **Enter** or the send button (or **Send now** in the banner).

Gethu does **not** send a message automatically — recognised speech always lands
in the composer for review first. Recognition is one utterance per click (no
always-listening loop, no accidental restarts). **Stop listening** cancels, and
**Discard** clears the transcript.

### Choosing a voice

**Settings → Voice output → Voice.** Gethu lists the voices your device exposes
and marks a *suggested* one. Selection logic:

1. Language fit comes first (your recognition language, then any `en-*` voice).
2. A male-sounding name (`Male`, `David`, `Daniel`, `Ravi`, `Hemant`, …) is
   preferred **when the browser gives a usable hint**.
3. Local (offline) voices are slightly preferred.

Voice **gender metadata is not reliably provided by browsers** — Gethu never
hardcodes a voice name, and if no suitable male voice exists it uses the best
available voice instead. Pick any voice you like in the same dropdown.

### Speaking speed and auto-speak

- **Settings → Speaking speed**: 0.6×–1.6×, default 1.0×, applied immediately
  and remembered.
- **Settings → Auto-speak replies**: off by default. When on, each completed reply
  is spoken automatically.
- **Header speaker button**: master on/off for voice output.
- **Header stop button / per-message speaker**: stop playback, or replay any
  individual assistant reply.

### Why Tanglish pronunciation varies

Browser voices are general-purpose OS/browser voices, not Tamil-native models.
A Romanized word like *"innaiku"* may be read with English phonetics on one
device and near-Tamil phonetics on another. That is a limitation of the free
browser stack, **not** a bug — Gethu deliberately does not promise native-quality
Tanglish speech. Switching to a Tamil (`ta-IN`) voice often helps; the speech
layer is isolated in `app/static/js/voice.js` so a dedicated TTS provider can be
dropped in later.

### Why speech recognition may need corrections

The recogniser is configured for one language at a time (`en-IN`, `ta-IN`, or
`en-US` in **Settings → Recognition language**). Genuinely mixed
Tamil+English sentences are the hardest case for any single-language model, so
Gethu always lets you fix the transcript before sending. That review step is the
intended workflow, not a workaround.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| Mic button greyed out | Browser has no speech recognition (e.g. Firefox). Use Chrome/Edge or type. |
| "Microphone permission was blocked" | Allow the mic for this site in the address-bar padlock menu, reload. |
| "needs HTTPS or localhost" | Open `http://127.0.0.1:8000` instead of a LAN IP/plain HTTP address. |
| "No microphone was found" | Check OS input device; the system must expose one to the browser. |
| Recognition stops instantly | Browser speech service may be offline or rate-limited; retry. |
| Nothing is spoken | Speech output unsupported in this browser, or voice output is off (header speaker toggle). |
| Speech is cut off / choppy | Lower the speaking speed, or pick a local voice in Settings. |
| Wrong voice gender | Pick a different voice in Settings → Voice output → Voice. |
| Model errors | Choose another model in Settings → Model, or update `GEMINI_MODEL`. |

### Privacy notes

- Gethu never activates the microphone silently and never sends raw audio
  anywhere itself — only the **recognised text** goes to the backend, and only
  when you press send.
- Browser speech recognition may use your browser vendor's or operating system's
  speech service. **Gethu cannot promise offline recognition or that audio never
  leaves your device** — that depends on the browser implementation.
- Google Gemini receives your messages and any attachments you explicitly send.

### What works without a paid voice API

Everything: recognition and synthesis use the browser's built-in Web Speech
APIs, and replies come from Gemini's free tier. There is no paid voice
subscription anywhere in the stack.

---

## Architecture

```
gethu-companion/
├── app/
│   ├── main.py                     # FastAPI factory, routers, exception handlers
│   ├── config.py                   # .env loading + validation
│   ├── api/
│   │   ├── chat.py                 # POST /api/chat  → SSE stream
│   │   ├── conversations.py        # history CRUD
│   │   ├── attachments.py          # upload / download / delete
│   │   └── settings.py             # non-secret settings
│   ├── services/
│   │   ├── gemini_service.py       # one client, streaming, bounded retries
│   │   ├── conversation_service.py # orchestration + SSE events
│   │   ├── prompt_service.py       # system prompt + modes + trimming
│   │   ├── attachment_service.py   # sniffing, safe storage, traversal guard
│   │   └── settings_service.py     # persisted preferences
│   ├── database/                   # connection.py, repository.py (SQLite)
│   ├── models/schemas.py           # pydantic request/response models
│   ├── prompts/companion_system_prompt.txt
│   ├── utils/                      # ids, timestamps, logging redaction
│   └── static/
│       ├── index.html
│       ├── css/styles.css
│       ├── js/                     # app, api, chat, voice, attachments,
│       │                           # settings, storage, markdown
│       └── vendor/                 # marked, DOMPurify, lucide (local, no CDN)
├── tests/                          # pytest + tests/frontend (node --test)
├── data/                           # runtime DB + uploads (gitignored)
├── .env.example · requirements.txt · pyproject.toml · README.md
```

**Design notes**

- `chat.py` validates and persists the user turn *before* opening the SSE
  response, so attachment/permission errors return proper HTTP status codes
  instead of failing mid-stream.
- Retries happen only before the first token is emitted, so a retried request can
  never duplicate text already shown.
- `voice.js` is DOM-light and dependency-free by design, which is why its logic
  is unit-testable in Node with mocked browser APIs.
- The Gemini API key stays server-side; the frontend only talks to `/api/*`.

## Security & privacy

- Secrets live only in `.env`; `.env` and runtime data are gitignored.
- The API key is never exposed to frontend JavaScript and never logged
  (a redacting filter scrubs anything key-shaped).
- Uploads are validated by magic bytes, size-limited, stored under generated
  names inside one directory, and blocked from path traversal.
- Model output is rendered through DOMPurify before insertion into the DOM.
- Gemini responses are streamed; window sizes and upload sizes are bounded.
- **This is a local, single-user app.** Bind to `127.0.0.1` (the default). Before
  exposing it on a network you must add authentication and TLS yourself.

## Known limitations

- Speech **input** is unavailable in Firefox and only partially in Safari.
- Browser voice quality and male-voice availability depend on the device/OS.
- Tanglish pronunciation is approximate (see above).
- This is a voice-enabled chat interface — **not** full-duplex, always-listening
  conversation. Wake-word activation is intentionally not implemented.
- Automated tests mock the browser speech APIs; they cover logic, not real audio.
  Real microphone and audio playback need a manual browser check.

## Next improvements

- Dedicated low-latency STT/TTS provider (the voice layer is already isolated).
- Wake-word activation.
- Long-term companion memory with explicit user control.
- Optional web search and reminders.
- Packaged desktop/mobile build.
