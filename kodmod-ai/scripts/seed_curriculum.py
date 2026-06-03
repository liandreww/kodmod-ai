"""
KODMOD AI — Seed Curriculum Script
==================================

Bootstraps a small set of subjects/concepts/lessons useful for local
development and integration tests. Idempotent — safe to run repeatedly.

Run:
    python scripts/seed_curriculum.py
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import Concept, Lesson, Subject
from database.session import async_session, close_db, init_db

logger = logging.getLogger(__name__)

# (subject_name, [(concept_name, slug, description, difficulty), ...])
SEED_DATA = [
    ("Matematika", [
        ("Pecahan",        "pecahan",        "Konsep dasar pecahan: pembilang dan penyebut.",      "easy"),
        ("Persamaan Linear","persamaan-linear","Persamaan satu variabel berderajat satu.",          "medium"),
        ("Bangun Datar",   "bangun-datar",   "Sifat segitiga, persegi, lingkaran, dan luasnya.",   "easy"),
    ]),
    ("Sains", [
        ("Fotosintesis",   "fotosintesis",   "Proses tumbuhan mengubah cahaya menjadi energi.",    "medium"),
        ("Sistem Tata Surya","tata-surya",   "Matahari, planet-planet, dan orbitnya.",             "easy"),
    ]),
    ("Bahasa Indonesia", [
        ("Kalimat Efektif","kalimat-efektif","Ciri kalimat yang jelas, padat, dan tidak ambigu.",  "medium"),
    ]),
]

LESSON_TEMPLATES = {
    "pecahan": (
        "Pengantar Pecahan",
        "Pecahan adalah cara menyatakan bagian dari keseluruhan. "
        "Sebuah pecahan terdiri dari pembilang dan penyebut. "
        "Pembilang adalah angka di atas, dan penyebut adalah angka di bawah. "
        "Misalnya, satu per dua artinya satu bagian dari dua bagian yang sama besar. "
        "Bayangkan kue yang dipotong menjadi dua bagian sama, lalu diambil satu bagian. "
        "Itulah satu per dua.",
    ),
    "fotosintesis": (
        "Apa Itu Fotosintesis",
        "Fotosintesis adalah proses ketika tumbuhan membuat makanan sendiri. "
        "Tumbuhan menggunakan cahaya matahari, air dari tanah, dan udara karbon dioksida. "
        "Hasilnya adalah glukosa untuk energi tumbuhan, dan oksigen yang kita hirup. "
        "Proses ini terjadi di daun, terutama di bagian yang disebut kloroplas. "
        "Kloroplas mengandung zat hijau bernama klorofil yang menangkap cahaya.",
    ),
    "tata-surya": (
        "Mengenal Tata Surya",
        "Tata surya adalah kumpulan benda langit yang berputar mengelilingi Matahari. "
        "Ada delapan planet: Merkurius, Venus, Bumi, Mars, Jupiter, Saturnus, Uranus, dan Neptunus. "
        "Bumi adalah planet ketiga dari Matahari. "
        "Setiap planet memiliki orbit sendiri, yaitu jalur untuk berputar mengelilingi Matahari. "
        "Selain planet, ada juga asteroid, komet, dan satelit alami seperti bulan.",
    ),
}


async def upsert_subject(session, name: str) -> Subject:
    existing = (
        await session.execute(select(Subject).where(Subject.name == name))
    ).scalar_one_or_none()
    if existing:
        return existing
    subject = Subject(name=name, description=None)
    session.add(subject)
    await session.flush()
    return subject


async def upsert_concept(
    session,
    subject_id: uuid.UUID,
    name: str,
    slug: str,
    description: str,
    difficulty: str,
) -> Concept:
    existing = (
        await session.execute(select(Concept).where(Concept.slug == slug))
    ).scalar_one_or_none()
    if existing:
        return existing
    concept = Concept(
        subject_id=subject_id,
        name=name,
        slug=slug,
        description=description,
        difficulty_level=difficulty,
    )
    session.add(concept)
    await session.flush()
    return concept


async def upsert_lesson(session, concept: Concept) -> None:
    template = LESSON_TEMPLATES.get(concept.slug)
    if not template:
        return
    title, body = template
    existing = (
        await session.execute(
            select(Lesson).where(Lesson.concept_id == concept.id, Lesson.title == title)
        )
    ).scalar_one_or_none()
    if existing:
        return
    session.add(Lesson(
        concept_id=concept.id,
        title=title,
        body_md=body,
        audio_friendly_summary=body,
        estimated_minutes=8,
        accessibility_metadata={"prepared_for": "blind", "language": "id"},
    ))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    await init_db()
    try:
        async with async_session() as session:
            for subject_name, concepts in SEED_DATA:
                subject = await upsert_subject(session, subject_name)
                for cn, slug, desc, diff in concepts:
                    concept = await upsert_concept(session, subject.id, cn, slug, desc, diff)
                    await upsert_lesson(session, concept)
        logger.info("Curriculum seed complete.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
