"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";

import { Badge, Card, EmptyState, Meter, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChatSessionDetail, StudentAnalytics, User } from "@/lib/types";
import { formatDate, percent, timeAgo } from "@/lib/utils";

interface Detail {
  account: User;
  analytics: StudentAnalytics;
  teacher_summary: { headline: string; alerts: { level: string; title: string; detail: string }[] };
}

interface SessionRow {
  id: string;
  title: string;
  subject_name: string | null;
  mode: string;
  started_at: string | null;
}

export default function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const [openSession, setOpenSession] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["teacher", "student", id],
    queryFn: () => api<Detail>(`/teacher/students/${id}`),
  });

  const sessions = useQuery({
    queryKey: ["teacher", "student", id, "sessions"],
    queryFn: () => api<SessionRow[]>(`/teacher/students/${id}/sessions`),
  });

  const transcript = useQuery({
    queryKey: ["teacher", "session", openSession],
    queryFn: () => api<ChatSessionDetail>(`/teacher/sessions/${openSession}`),
    enabled: !!openSession,
  });

  const analytics = detail.data?.analytics;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <Link
        href="/guru"
        className="inline-flex w-fit items-center gap-2 font-semibold text-brand-deep underline underline-offset-4"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Semua siswa
      </Link>

      {detail.isLoading ? (
        <p role="status" className="text-ink-soft">
          Memuat
        </p>
      ) : null}

      {detail.data ? (
        <>
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-ink">
              {detail.data.account.full_name}
            </h2>
            <p className="text-ink-soft">
              <span className="font-mono">{detail.data.account.username}</span>, bergabung{" "}
              {formatDate(detail.data.account.created_at)}
            </p>
          </div>

          {detail.data.teacher_summary?.alerts?.length ? (
            <ul className="flex flex-col gap-2">
              {detail.data.teacher_summary.alerts.map((alert) => (
                <li key={alert.title}>
                  <Card className="py-3">
                    <p className="font-semibold text-ink">{alert.title}</p>
                    <p className="text-sm text-ink-soft">{alert.detail}</p>
                  </Card>
                </li>
              ))}
            </ul>
          ) : null}

          {analytics ? (
            <Card className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Penguasaan" value={percent(analytics.overall_mastery)} />
              <Stat label="Akurasi kuis" value={percent(analytics.quiz_accuracy)} />
              <Stat label="Sesi" value={String(analytics.n_sessions)} />
              <Stat label="Menit belajar" value={String(Math.round(analytics.total_minutes))} />
            </Card>
          ) : null}

          {analytics?.weak_concepts?.length ? (
            <Card>
              <h3 className="font-bold text-ink">Konsep yang perlu diperkuat</h3>
              <ul className="mt-3 flex flex-col gap-3">
                {analytics.weak_concepts.map((concept) => (
                  <li key={concept.concept_name} className="flex items-center gap-3">
                    <span className="w-40 truncate text-ink">{concept.concept_name}</span>
                    <span className="w-12 tabular-nums text-ink-soft">
                      {percent(concept.mastery)}
                    </span>
                    <span className="flex-1">
                      <Meter value={concept.mastery} label={`Penguasaan ${concept.concept_name}`} />
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {analytics?.open_misconceptions?.length ? (
            <Card>
              <h3 className="font-bold text-ink">Miskonsepsi terbuka</h3>
              <ul className="mt-3 flex flex-col gap-2">
                {analytics.open_misconceptions.map((item) => (
                  <li key={item.description} className="text-ink">
                    {item.description}{" "}
                    <span className="text-sm text-ink-soft">{timeAgo(item.detected_at)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <section>
            <h3 className="mb-3 text-xl font-bold tracking-tight text-ink">Percakapan</h3>

            {sessions.data?.length === 0 ? (
              <EmptyState title="Belum ada percakapan." />
            ) : (
              <ul className="flex flex-col gap-2">
                {sessions.data?.map((session) => (
                  <li key={session.id}>
                    <Card className="py-3">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenSession((current) => (current === session.id ? null : session.id))
                        }
                        aria-expanded={openSession === session.id}
                        className="flex w-full items-center gap-3 text-left"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold text-ink">
                            {session.title}
                          </span>
                          <span className="block text-sm text-ink-soft">
                            {[session.subject_name, timeAgo(session.started_at)]
                              .filter(Boolean)
                              .join(", ")}
                          </span>
                        </span>
                        <Badge>{openSession === session.id ? "Tutup" : "Baca"}</Badge>
                      </button>

                      {openSession === session.id ? (
                        <div className="mt-3 border-t border-line pt-3">
                          {transcript.isLoading ? (
                            <p role="status" className="text-ink-soft">
                              Memuat transkrip
                            </p>
                          ) : (
                            <ol className="flex flex-col gap-3">
                              {transcript.data?.turns.map((turn, index) => (
                                <li key={index}>
                                  <p className="text-sm font-semibold text-ink-soft">
                                    {turn.role === "student" ? "Siswa" : "Tutor"}
                                  </p>
                                  <p className="text-ink">{turn.text}</p>
                                </li>
                              ))}
                            </ol>
                          )}
                        </div>
                      ) : null}
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
