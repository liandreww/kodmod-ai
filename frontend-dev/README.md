# KODMOD AI, frontend

Next.js App Router frontend for the KODMOD API. Three surfaces, one for each
role: Ruang Belajar for students, a dashboard for teachers, and account plus
invitation management for admins.

## Running it

```bash
npm install
cp .env.example .env.local     # then fill in OPENAI_API_KEY
npm run dev                    # http://localhost:3000
```

The backend must be running too (`cd ../kodmod-ai && make dev`), and its
`CORS_ALLOW_ORIGINS` must list `http://localhost:3000`.

| Command | Does |
|---|---|
| `npm run dev` | Development server |
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |

## Where speech happens

Both directions of speech run here, never in the Python backend.

* **Microphone to text.** The browser records with `MediaRecorder` and posts the
  blob to `/api/transcribe`, a Next.js route handler that calls OpenAI with the
  server-side key. The key never reaches the browser.
* **Text to speech.** Off by default. When switched on, `/api/speak` returns
  audio one sentence at a time so playback starts before the answer is finished.

Both routes verify the caller's KODMOD token against the backend before spending
anything. Without that check they would be an open relay to a paid API.

Models come from the environment: `OPENAI_TRANSCRIBE_MODEL` and
`OPENAI_TTS_MODEL`.

## Routes

| Path | Role |
|---|---|
| `/masuk`, `/daftar` | anyone |
| `/belajar` | student |
| `/guru`, `/guru/siswa/[id]`, `/guru/mata-pelajaran` | teacher |
| `/admin`, `/admin/undangan` | admin |

Role gates in `src/components/guard.tsx` decide what to render. They are not
security: the API enforces every role on every request.

## Design

Everything is set in **Atkinson Hyperlegible**, the typeface the Braille
Institute drew so that characters which normally collide stay distinct for
low-vision readers. Invitation codes and ids use its monospace companion, where
a misread character costs someone their account.

The palette is `#E4F9F5 / #30E3CA / #11999E / #40514E` plus one derived shade.
`#30E3CA` is 1.7:1 on white and `#11999E` is 3.5:1, both below the 4.5:1 floor,
so neither carries small text: `#0B6E72` (6.1:1) does, and `#30E3CA` is reserved
for state, meaning recording, selected, and focused. No gradients.

### Accessibility rules this codebase follows

* Streaming text is `aria-hidden`; the finished answer is announced once through
  a separate live region. Announcing a growing paragraph token by token makes a
  screen reader unusable.
* Every control has a visible 3px focus ring. There is no `outline: none`
  anywhere.
* Space starts and stops recording from anywhere on the page, Escape discards
  the recording, `/` moves focus to the text input, Enter sends typed text.
* Targets are at least 44px. Zoom is not capped.
* `prefers-reduced-motion` disables both animations.
