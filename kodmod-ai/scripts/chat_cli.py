"""
KODMOD AI — Text-mode Chat CLI
==============================

REPL interaktif ala `ollama run` untuk mencoba fitur tutor dalam mode teks
(tanpa STT/TTS), memakai OpenAI untuk LLM & embedding.

Jalankan dari direktori `kodmod-ai/` (nested), setelah:
    docker compose -f docker/docker-compose.test.yml up -d
    python -m scripts.create_test_db
    python -m scripts.seed_curriculum

    python -m scripts.chat_cli

Ketik teks biasa -> satu giliran penuh lewat graf (tutoring / analytics / dst,
intent diklasifikasi otomatis). Ketik `/help` untuk daftar perintah.

Setiap fitur dibungkus penangan error: kalau gagal, CLI menampilkan pesan +
saran perbaikan dan tetap jalan (tidak crash). `/debug on` untuk traceback penuh.
"""

from __future__ import annotations

import os
import pathlib


# --------------------------------------------------------------------------- #
# 1. Environment — HARUS sebelum import modul proyek apa pun.
# --------------------------------------------------------------------------- #
def _setup_env() -> pathlib.Path:
    root = pathlib.Path.cwd()
    if not (root / "graphs" / "main_graph.py").exists():
        raise SystemExit(
            f"Jalankan dari direktori kodmod-ai/ (nested). cwd sekarang: {root}"
        )

    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")  # .env menang atas default di bawah
    except Exception:
        pass

    runtime = root / ".runtime"
    (runtime / "audio").mkdir(parents=True, exist_ok=True)
    (runtime / "uploads").mkdir(parents=True, exist_ok=True)

    forced = {
        "ENV": "dev",
        "DEBUG": "false",
        "LOG_JSON": "false",
        "KODMOD_LLM_PROVIDER": "openai",
        "KODMOD_EMBED_BACKEND": "openai",
        "KODMOD_EMBED_MODEL": "text-embedding-3-small",
        "KODMOD_EMBED_DIM": "1024",
        "VECTOR_BACKEND": "pgvector",
        "RAG_TOP_K": "4",
        "TTS_ENABLED": "false",
        "STT_ENABLED": "false",
        "KODMOD_TTS_OUTPUT_DIR": str(runtime / "audio"),
        "AUDIO_DIR": str(runtime / "audio"),
        "UPLOAD_DIR": str(runtime / "uploads"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    os.environ.update(forced)
    for k, v in {
        "DB_HOST": "localhost",
        "DB_PORT": "5433",
        "DB_USER": "kodmod",
        "DB_PASSWORD": "kodmod",
        "DB_NAME": "kodmod",
    }.items():
        os.environ.setdefault(k, v)

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY belum di-set (export, atau taruh di kodmod-ai/.env).")
    return root


ROOT = _setup_env()

import asyncio  # noqa: E402
import datetime as dt  # noqa: E402
import traceback  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import select, text as sql_text  # noqa: E402

from analytics.student_model import update_student_model_node  # noqa: E402
from agents.analytics_agent import analytics_node  # noqa: E402
from agents.quiz_agent import mini_quiz_node, quiz_node  # noqa: E402
from agents.quiz_analyzer import quiz_analyzer_node  # noqa: E402
from agents.recommendation_agent import recommendation_node  # noqa: E402
from agents.scoring_agent import scoring_node  # noqa: E402
from database.models import (  # noqa: E402
    Concept,
    LearningSession,
    QuizAttempt,
    QuizQuestion,
    QuizSession,
    Student,
)
from database.session import async_session, close_db, init_db  # noqa: E402
from graphs.main_graph import build_kodmod_graph  # noqa: E402
from graphs.state import initial_state  # noqa: E402


# --------------------------------------------------------------------------- #
# Kosmetik
# --------------------------------------------------------------------------- #
_COLOR = os.environ.get("NO_COLOR") is None
if os.name == "nt":
    os.system("")  # aktifkan ANSI di konsol Windows lama


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def bot(s: str) -> None:
    print(_c("36", "kodmod> ") + s)


def sys_(s: str) -> None:
    print(_c("90", "· " + s))


def warn(s: str) -> None:
    print(_c("33", "! " + s))


def err(s: str) -> None:
    print(_c("31", "✗ " + s))


# --------------------------------------------------------------------------- #
# Sesi
# --------------------------------------------------------------------------- #
STUDENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = "cli-text-mode"

_DIFF_WORDS = {
    "mudah": "easy", "gampang": "easy", "easy": "easy",
    "sedang": "medium", "medium": "medium",
    "sulit": "hard", "susah": "hard", "sukar": "hard", "hard": "hard",
}
_QUIZ_WORDS = ("kuis", "quiz", "latihan soal", "soal latihan", "kerjakan soal", "ujian")
_QUIT_QUIZ_WORDS = ("stop", "berhenti", "keluar", "selesai", "batal", "cukup")

_CARRY_KEYS = (
    "messages", "tutoring_context", "mastery_scores", "analytics_summary",
    "learning_profile", "emotional_state", "current_topic", "current_concept_id",
    "current_difficulty",
    "quiz_session_id", "quiz_questions", "current_question_index", "quiz_question",
    "quiz_attempts", "cumulative_quiz_score", "misconceptions_detected",
)


class Ctx:
    """State yang dibawa antar giliran + flag CLI."""

    def __init__(self) -> None:
        self.graph = None
        self.concepts: dict[str, uuid.UUID] = {}          # slug -> id
        self.concept_names: dict[str, str] = {}           # slug -> display name
        self.concept_lookup: list[tuple[str, str]] = []   # (needle, slug), longest first
        self.carry: dict = {}
        self.debug = False
        self.last_out: dict = {}

    def resolve_concept(self, phrase: str) -> tuple[str, str] | None:
        """Cocokkan potongan teks bebas ke (slug, difficulty)."""
        p = " ".join(phrase.lower().split())
        diff = "easy"
        for word, d in _DIFF_WORDS.items():
            if word in p:
                diff = d
                p = p.replace(word, "").strip()
        if p in self.concepts:
            return p, diff
        for needle, slug in self.concept_lookup:
            if needle and needle in p:
                return slug, diff
        return None

    def build_state(self, user_text: str, **overrides) -> dict:
        st = initial_state(session_id=SESSION_ID, student_id=str(STUDENT_ID))
        st["user_input"] = user_text
        st["audio_input_path"] = ""
        for k in _CARRY_KEYS:
            if k in self.carry:
                st[k] = self.carry[k]
        st.update(overrides)
        return st

    def absorb(self, out: dict) -> None:
        self.last_out = out
        for k in _CARRY_KEYS:
            if k in out and out[k] is not None:
                self.carry[k] = out[k]


CTX = Ctx()


# --------------------------------------------------------------------------- #
# Penangan error umum
# --------------------------------------------------------------------------- #
def _explain(exc: Exception) -> None:
    msg = str(exc)
    low = msg.lower()
    err(f"{type(exc).__name__}: {msg[:400]}")
    if any(t in low for t in ("model", "does not exist", "invalid_request", "not found")) and (
        "gpt-5.6-luna" in low or "model" in low
    ):
        warn("Sepertinya id model OpenAI tidak valid. Ubah keempat entri \"openai\" di "
             "tools/llm_client.py (mis. ke gpt-4.1-mini), lalu jalankan ulang.")
    elif "api key" in low or "apikey" in low or "authentication" in low:
        warn("Masalah OPENAI_API_KEY. Cek nilainya di kodmod-ai/.env atau environment.")
    elif "connect" in low or "refused" in low or "not initialized" in low:
        warn("Postgres tidak terjangkau. Cek: docker compose -f docker/docker-compose.test.yml ps "
             "dan DB_PORT di .env (default 5433).")
    elif "rate limit" in low or "429" in low:
        warn("Kena rate limit OpenAI. Tunggu sebentar lalu coba lagi.")
    if CTX.debug:
        print(_c("90", "".join(traceback.format_exception(exc))))
    else:
        sys_("(`/debug on` untuk traceback penuh)")


async def guarded(label: str, coro):
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — CLI harus tetap hidup
        err(f"fitur '{label}' gagal.")
        _explain(exc)
        return None


# --------------------------------------------------------------------------- #
# Aksi
# --------------------------------------------------------------------------- #
async def do_turn(user_text: str) -> None:
    out = await guarded("graf", CTX.graph.ainvoke(CTX.build_state(user_text)))
    if out is None:
        return
    CTX.absorb(out)
    sys_(f"intent={out.get('intent')!r} conf={out.get('intent_confidence')} "
         f"last_node={out.get('last_node')!r}")
    resp = out.get("accessible_response") or out.get("generated_response") or "(kosong)"
    bot(resp)
    if out.get("retrieved_docs"):
        sys_(f"{len(out['retrieved_docs'])} potongan kurikulum dipakai")


async def do_quiz(arg: str) -> None:
    if not arg.strip():
        warn(f"beri concept: /quiz <{'|'.join(CTX.concepts)}> [mudah|sedang|sulit]")
        return
    resolved = CTX.resolve_concept(arg)
    if resolved is None:
        warn(f"concept tidak dikenali dari '{arg}'. Pilihan: {', '.join(CTX.concepts)}")
        return
    await _start_quiz(*resolved)


async def _start_quiz(slug: str, diff: str) -> None:
    name = CTX.concept_names.get(slug, slug)
    # mulai bersih supaya state kuis lama tidak terbawa
    for k in ("quiz_session_id", "quiz_questions", "current_question_index",
              "quiz_question", "quiz_attempts", "cumulative_quiz_score"):
        CTX.carry.pop(k, None)
    out = await guarded(
        "quiz",
        CTX.graph.ainvoke(CTX.build_state(
            f"Aku mau kuis tentang {name} tingkat {diff}",
            current_concept_id=str(CTX.concepts[slug]),
            current_topic=name,
            current_difficulty=diff,
        )),
    )
    if out is None:
        return
    CTX.absorb(out)
    qs = out.get("quiz_questions", [])
    sys_(f"quiz_session_id={out.get('quiz_session_id')} · topik='{name}' · {len(qs)} soal")
    q = out.get("quiz_question") or (qs[0] if qs else None)
    CTX.carry["quiz_question"] = q
    if q:
        bot(f"Soal 1/{len(qs)} ({q.get('type')}): {q.get('text','')}")
        for opt in q.get("options", []):
            print("   ", opt)
        sys_("jawab dengan:  /answer <jawabanmu>   ·   keluar kuis: /reset")
    else:
        warn("Tidak ada soal yang dihasilkan.")


def _guess_quiz(text: str) -> tuple[str, str] | None:
    low = text.lower()
    if not any(w in low for w in _QUIZ_WORDS):
        return None
    return CTX.resolve_concept(low)


async def do_answer(arg: str) -> None:
    q = CTX.carry.get("quiz_question")
    qs = CTX.carry.get("quiz_questions", [])
    idx = CTX.carry.get("current_question_index", 0)
    if not q:
        warn("Belum ada kuis aktif. Mulai dengan /quiz <concept>, atau /mini <concept>.")
        return
    if arg.strip().lower() in _QUIT_QUIZ_WORDS:
        for k in ("quiz_session_id", "quiz_questions", "current_question_index",
                  "quiz_question", "quiz_attempts", "cumulative_quiz_score"):
            CTX.carry.pop(k, None)
        sys_("keluar dari kuis. (jalankan /analyze kalau mau analisa jawaban yang sudah masuk)")
        return
    st = {
        "student_id": str(STUDENT_ID),
        "quiz_session_id": CTX.carry.get("quiz_session_id", "cli-quiz"),
        "quiz_questions": qs or [q],
        "quiz_question": q,
        "current_question_index": idx,
        "quiz_attempts": CTX.carry.get("quiz_attempts", []),
        "student_answer": arg.strip(),
    }
    res = await guarded("scoring", scoring_node(st))
    if res is None:
        return
    st.update(res)
    CTX.carry["quiz_attempts"] = st["quiz_attempts"]
    bot(f"Skor: {st.get('quiz_score'):.2f}  ·  {st.get('generated_response', '')}")

    nxt = idx + 1
    CTX.carry["current_question_index"] = nxt
    if nxt < len(qs):
        ask = await guarded("quiz_ask", quiz_node({
            "quiz_questions": qs, "current_question_index": nxt,
        }))
        if ask:
            CTX.carry["quiz_question"] = ask.get("quiz_question", qs[nxt])
            bot(f"Soal {nxt + 1}/{len(qs)}: {ask.get('generated_response', '')}")
            for opt in (CTX.carry["quiz_question"] or {}).get("options", []):
                print("   ", opt)
    else:
        CTX.carry["quiz_question"] = None
        sys_("Semua soal terjawab. Jalankan /analyze untuk analisa + update mastery.")


async def do_mini(arg: str) -> None:
    slug = arg.strip()
    cid = CTX.concepts.get(slug) or CTX.carry.get("current_concept_id")
    if not cid:
        warn(f"beri concept: /mini <{'|'.join(CTX.concepts)}>")
        return
    res = await guarded("mini_quiz", mini_quiz_node({
        "generated_response": CTX.last_out.get("generated_response")
        or "Pecahan adalah bagian dari keseluruhan.",
        "current_concept_id": str(cid),
        "current_difficulty": CTX.carry.get("current_difficulty", "easy"),
    }))
    if not res:
        return
    for k in ("quiz_session_id", "quiz_questions", "current_question_index", "quiz_question"):
        if k in res:
            CTX.carry[k] = res[k]
    CTX.carry["quiz_attempts"] = []
    q = res.get("quiz_question") or {}
    bot(f"Mini-kuis: {q.get('text', res.get('generated_response', ''))}")
    sys_("jawab dengan:  /answer <jawabanmu>")


async def do_analyze() -> None:
    attempts = CTX.carry.get("quiz_attempts", [])
    if not attempts:
        warn("Belum ada jawaban kuis. Jalankan /quiz lalu /answer beberapa kali.")
        return
    st = {
        "quiz_attempts": attempts,
        "quiz_questions": CTX.carry.get("quiz_questions", []),
        "analytics_summary": CTX.carry.get("analytics_summary", {}),
        "student_id": str(STUDENT_ID),
        "current_question_index": CTX.carry.get("current_question_index", 0),
    }
    a = await guarded("quiz_analyzer", quiz_analyzer_node(st))
    if a:
        st.update(a)
        CTX.carry["analytics_summary"] = st.get("analytics_summary", {})
        CTX.carry["misconceptions_detected"] = st.get("misconceptions_detected", [])
        bot(st.get("generated_response", "(tidak ada ringkasan)"))
        sys_(f"miskonsepsi: {st.get('misconceptions_detected')}")
        sys_(f"rekomendasi: {st.get('recommendations')}")
    u = await guarded("update_student_model", update_student_model_node(st))
    if u:
        CTX.carry["mastery_scores"] = u.get("mastery_scores", CTX.carry.get("mastery_scores", {}))
        sys_(f"mastery ter-update: {u.get('mastery_scores')}")


async def do_analytics() -> None:
    st = {"student_id": str(STUDENT_ID), "analytics_summary": CTX.carry.get("analytics_summary", {})}
    a = await guarded("analytics", analytics_node(st))
    if not a:
        return
    st.update(a)
    r = await guarded("recommendation", recommendation_node(st))
    if r:
        st.update(r)
    CTX.carry["analytics_summary"] = st.get("analytics_summary", {})
    CTX.carry["recommendations"] = st.get("recommendations", [])
    bot(st.get("generated_response", "(tidak ada ringkasan)"))
    summ = st.get("analytics_summary", {})
    sys_(f"overall_mastery={summ.get('overall_mastery')} sessions_total={summ.get('sessions_total')} "
         f"avg_quiz_score={summ.get('avg_quiz_score')}")
    sys_(f"rekomendasi: {st.get('recommendations')}")


async def do_mastery() -> None:
    async def _q():
        async with async_session() as s:
            rows = (await s.execute(sql_text(
                "SELECT concept_id, mastery, confidence, n_attempts FROM mastery_scores "
                "WHERE student_id = CAST(:sid AS uuid)"), {"sid": str(STUDENT_ID)})).all()
        return [tuple(r) for r in rows]

    rows = await guarded("mastery (DB)", _q())
    if rows is not None:
        bot(f"mastery_scores untuk siswa uji: {rows or '(kosong — jalankan /analyze dulu)'}")


async def do_history() -> None:
    async def _seed():
        async with async_session() as s:
            started = dt.datetime.utcnow() - dt.timedelta(days=1)
            s.add(LearningSession(student_id=STUDENT_ID, mode="tutoring",
                                  started_at=started, ended_at=started + dt.timedelta(minutes=12)))
            qs = QuizSession(student_id=STUDENT_ID, concept_id=CTX.concepts["pecahan"],
                             started_at=started, ended_at=started + dt.timedelta(minutes=6),
                             total_questions=2, correct_count=1, final_score=0.6, status="completed")
            s.add(qs)
            await s.flush()
            q1 = QuizQuestion(quiz_session_id=qs.id, order_index=0, question="1/2 + 1/4 = ?",
                              question_type="mcq", correct_answer="A",
                              concept_id=CTX.concepts["pecahan"])
            q2 = QuizQuestion(quiz_session_id=qs.id, order_index=1, question="Sederhanakan 2/4.",
                              question_type="spoken", correct_answer="1/2",
                              concept_id=CTX.concepts["pecahan"])
            s.add_all([q1, q2])
            await s.flush()
            s.add_all([
                QuizAttempt(quiz_session_id=qs.id, quiz_question_id=q1.id,
                            student_answer="A", score=0.9, is_correct=True, confidence=0.9),
                QuizAttempt(quiz_session_id=qs.id, quiz_question_id=q2.id,
                            student_answer="setengah", score=0.4, is_correct=False, confidence=0.6),
            ])
        return True

    if await guarded("seed history", _seed()):
        sys_("Riwayat contoh (1 sesi + 1 kuis 2 soal) ditambahkan. Coba /analytics.")


def do_state() -> None:
    o = CTX.last_out
    keys = ("intent", "last_node", "current_concept_id", "quiz_session_id",
            "current_question_index", "cumulative_quiz_score")
    sys_("carry: " + ", ".join(sorted(CTX.carry)))
    sys_("last turn: " + ", ".join(f"{k}={o.get(k)!r}" for k in keys))


HELP = """
Perintah:
  <teks bebas>          satu giliran lewat graf (intent diklasifikasi otomatis)
  /quiz <concept> [diff] mulai kuis (concept: {concepts})
  /answer <jawaban>      jawab soal kuis yang sedang aktif
  /mini <concept>        buat 1 mini-kuis (klaster tutoring)
  /analyze              analisa kuis + update mastery (tulis ke DB)
  /analytics            ringkasan analitik + rekomendasi
  /mastery              tampilkan baris mastery_scores dari DB
  /history              sisipkan riwayat sesi/kuis contoh (biar /analytics ada isinya)
  /concepts             daftar concept
  /state                lihat state giliran terakhir
  /reset                bersihkan konteks percakapan
  /debug on|off         tampilkan traceback penuh saat error
  /help                 pesan ini
  /quit                 keluar
"""


async def dispatch(line: str) -> bool:
    """Return False untuk keluar."""
    line = line.strip()
    if not line:
        return True
    if not line.startswith("/"):
        if CTX.carry.get("quiz_question"):        # kuis aktif -> perlakukan sebagai jawaban
            sys_("(kuis aktif — ketik /reset untuk keluar)")
            await do_answer(line)
            return True
        guess = _guess_quiz(line)
        if guess:
            sys_(f"(terdeteksi permintaan kuis → topik '{CTX.concept_names.get(guess[0], guess[0])}', "
                 f"tingkat {guess[1]})")
            await _start_quiz(*guess)
            return True
        if any(w in line.lower() for w in _QUIZ_WORDS):
            sys_(f"(sebutkan topik untuk kuis yang terarah, mis:  /quiz {next(iter(CTX.concepts), 'pecahan')})")
        await do_turn(line)
        return True

    cmd, _, arg = line[1:].partition(" ")
    cmd = cmd.lower()
    if cmd in ("quit", "exit", "q"):
        return False
    elif cmd == "help":
        print(HELP.format(concepts=", ".join(CTX.concepts) or "(seed dulu)"))
    elif cmd == "concepts":
        for slug, cid in CTX.concepts.items():
            print(f"  {slug:20} {cid}")
    elif cmd == "quiz":
        await do_quiz(arg)
    elif cmd == "answer":
        await do_answer(arg)
    elif cmd == "mini":
        await do_mini(arg)
    elif cmd == "analyze":
        await do_analyze()
    elif cmd == "analytics":
        await do_analytics()
    elif cmd == "mastery":
        await do_mastery()
    elif cmd == "history":
        await do_history()
    elif cmd == "state":
        do_state()
    elif cmd == "reset":
        CTX.carry.clear()
        CTX.last_out = {}
        sys_("konteks dibersihkan.")
    elif cmd == "debug":
        CTX.debug = arg.strip().lower() in ("on", "1", "true", "yes")
        sys_(f"debug = {CTX.debug}")
    else:
        warn(f"perintah tidak dikenal: /{cmd} (coba /help)")
    return True


async def ainput(prompt: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(None, lambda: input(prompt))


async def bootstrap() -> None:
    sys_("menghubungkan ke Postgres ...")
    await init_db()
    async with async_session() as s:
        if await s.get(Student, STUDENT_ID) is None:
            s.add(Student(id=STUDENT_ID, full_name="Siswa Uji",
                          accessibility_profile="blind", preferred_language="id"))
        rows = (await s.execute(select(Concept.slug, Concept.id, Concept.name))).all()
    CTX.concepts = {slug: cid for slug, cid, _ in rows}
    CTX.concept_names = {slug: name for slug, _, name in rows}
    lookup: list[tuple[str, str]] = []
    for slug, _, name in rows:
        lookup.append((slug.replace("-", " ").lower(), slug))
        if name:
            lookup.append((name.lower(), slug))
    CTX.concept_lookup = sorted(set(lookup), key=lambda t: -len(t[0]))
    if not CTX.concepts:
        warn("Tabel concepts kosong. Jalankan: python -m scripts.seed_curriculum")
    sys_("membangun graf ...")
    CTX.graph = await build_kodmod_graph(checkpointer=None)


async def main() -> None:
    print(_c("1;36", "KODMOD AI — chat mode teks (TTS/STT nonaktif, LLM=OpenAI)"))
    try:
        await bootstrap()
    except Exception as exc:  # noqa: BLE001
        err("bootstrap gagal — CLI tidak bisa mulai.")
        _explain(exc)
        return
    sys_(f"siswa uji: {STUDENT_ID} · concept: {', '.join(CTX.concepts) or '-'}")
    print(HELP.format(concepts=", ".join(CTX.concepts) or "(seed dulu)"))

    try:
        while True:
            try:
                line = await ainput(_c("32", "\nyou> "))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            try:
                if not await dispatch(line):
                    break
            except Exception as exc:  # noqa: BLE001 — jangan pernah mematikan REPL
                err("terjadi error tak terduga saat memproses perintah.")
                _explain(exc)
    finally:
        await close_db()
        sys_("sampai jumpa.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
