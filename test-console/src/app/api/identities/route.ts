import { NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * There is no login endpoint and no password column anywhere in the schema,
 * so signing in means picking a real row and minting a token whose `sub` is
 * that row's id (api/dependencies.py:56-83 404s on an unknown sub).
 */
export async function GET() {
  const profile = await activeProfile();

  const [students, teachers, classrooms] = await Promise.all([
    query(
      profile,
      `select s.id, s.full_name, s.email, s.grade_level, s.accessibility_profile,
              s.preferred_language, s.created_at,
              (select count(*)::int from mastery_scores m where m.student_id = s.id)   as mastery_rows,
              (select count(*)::int from learning_sessions l where l.student_id = s.id) as sessions,
              (select count(*)::int from quiz_sessions q where q.student_id = s.id)     as quizzes
         from students s
        order by s.created_at desc nulls last
        limit 200`,
      [],
      { label: "list students" },
    ),
    query(
      profile,
      `select t.id, t.full_name, t.email, t.subject_specialty, t.created_at,
              (select count(*)::int from classrooms c where c.teacher_id = t.id) as classrooms
         from teachers t order by t.created_at desc nulls last limit 200`,
      [],
      { label: "list teachers" },
    ),
    query(
      profile,
      `select c.id, c.name, c.grade_level, c.teacher_id,
              (select count(*)::int from classroom_enrollment e where e.classroom_id = c.id) as enrolled
         from classrooms c order by c.created_at desc nulls last limit 200`,
      [],
      { label: "list classrooms" },
    ),
  ]);

  return NextResponse.json({
    students: students.rows,
    teachers: teachers.rows,
    classrooms: classrooms.rows,
  });
}
