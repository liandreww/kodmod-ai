# KODMOD AI — Accessibility Design

KODMOD AI is built **voice-first** for learners who are blind or have
low vision. This document captures the non-negotiable rules every
contributor must follow.

## 1. The Audio-Only Reality

Every assistant turn will be read by TTS. The learner cannot:

- See colors, shapes, charts, or diagrams.
- Scroll back to re-read a long paragraph.
- Skim — they listen sequentially.
- Easily resume mid-sentence after a pause.

Implications:

- Sentences ≤ **22 words** (`MAX_SPOKEN_SENTENCE_WORDS`). Long sentences
  exhaust working memory.
- No markdown, asterisks, or symbols that don't speak well.
- Numbers are spelled out for clarity ("3,14" → "tiga koma satu empat").
- Section structure is conveyed by ordinal words ("pertama, kedua") not
  punctuation.

## 2. Visual References — Forbidden Vocabulary

The accessibility agent (`accessibility/narration.py`) automatically
strips and rewrites these patterns. Any agent that emits user-facing
text **must** route through `accessibility_node` before TTS:

| Forbidden                       | Replacement                                |
|---------------------------------|---------------------------------------------|
| "lihat gambar 3.1"              | description from chunk's accessibility_metadata |
| "perhatikan diagram di atas"    | "perhatikan penjelasan berikut"             |
| "garis berwarna merah"          | "garis penanda"                             |
| "see the figure"                | "based on the described illustration"       |
| "as shown in"                   | dropped + restated as an inline description |

## 3. Pacing & Control

The learner controls pacing via voice commands
(`accessibility/voice_commands.py`):

- **ulangi / repeat** — replay the last assistant turn.
- **lebih pelan / slower** — reduce TTS rate by 0.1.
- **lebih cepat / faster** — increase TTS rate by 0.1.
- **lanjut / next** — advance.
- **kembali / back** — step back.
- **berhenti / stop** — cancel current generation.
- **bantuan / help** — read the available commands.
- **mulai kuis / start quiz** — initiate quiz mode.

These commands short-circuit the LLM router for sub-millisecond
response.

## 4. Onboarding Without Sight

- First-run: speak welcome + commands within 3 seconds of connecting.
- Use audio cues (short tones) for connection state changes.
- Confirm every destructive action twice.
- Provide a "skip onboarding" command for repeat users.

## 5. Multimodal Content Ingestion

Source materials often contain figures, tables, and diagrams. The
ingestion pipeline (`rag/ingestion.py` + `accessibility/narration.py::describe_image`)
generates audio-friendly descriptions at chunking time and stores them
in `curriculum_chunks.accessibility_metadata`. At retrieval time, those
descriptions are surfaced inline so the tutor can speak them naturally.

## 6. Emotional Support

The intent router classifies emotion (`detected_emotion`):
`engaged | neutral | frustrated | fatigued | motivated`. The tutor
adjusts:

- **frustrated** → simplify, validate effort, slow down.
- **fatigued** → suggest a break, shorten responses.
- **motivated** → push challenge level up; offer a stretch question.

## 7. Teacher Settings

Teachers can configure per-student:

- Speech rate baseline.
- Voice gender / locale (`TTS_VOICE`).
- Verbosity level (`SOCRATIC_DEPTH`).
- Language preference (`preferred_language`).

## 8. Testing for Accessibility

CI runs unit tests for:

- `describe_visuals_in_text` — ensures visual references are removed.
- `voice_commands.detect_command` — ensures all commands match.
- Output sentence-length checker — fails the build if any tutoring
  example response in `tests/fixtures/` contains a sentence > 22 words.

## 9. WCAG / Standards Alignment

While KODMOD's primary surface is audio, the dashboards (teacher and
student) target **WCAG 2.2 Level AA**:

- Keyboard-only navigation
- Screen-reader compatibility (semantic HTML, ARIA labels)
- Color contrast ≥ 4.5:1
- Text resize up to 200% without loss of function
