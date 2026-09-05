"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Info, Users } from "lucide-react";

import { Badge, Card, EmptyState, Meter, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import type { Alert, CohortSummary } from "@/lib/types";
import { percent } from "@/lib/utils";

const ALERT_ICON = {
  warning: <AlertTriangle aria-hidden className="h-4 w-4" />,
  info: <Info aria-hidden className="h-4 w-4" />,
  success: <CheckCircle2 aria-hidden className="h-4 w-4" />,
} as const;

const ALERT_TONE = { warning: "warning", info: "neutral", success: "brand" } as const;

export default function TeacherHome() {
  const roster = useQuery({
    queryKey: ["teacher", "students"],
    queryFn: () => api<CohortSummary>("/teacher/students"),
  });

  const alerts = useQuery({
    queryKey: ["teacher", "alerts"],
    queryFn: () => api<{ alerts: Alert[]; summary: CohortSummary }>("/analytics/cohort/alerts"),
  });

  const data = roster.data;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <h2 className="text-2xl font-bold tracking-tight text-ink">Siswa</h2>

      {alerts.data?.alerts?.length ? (
        <ul className="flex flex-col gap-2">
          {alerts.data.alerts.map((alert) => (
            <li key={alert.title}>
              <Card className="flex items-start gap-3 py-3">
                <span className="mt-0.5 text-brand">{ALERT_ICON[alert.level]}</span>
                <div>
                  <p className="font-semibold text-ink">{alert.title}</p>
                  <p className="text-sm text-ink-soft">{alert.detail}</p>
                </div>
                <span className="ml-auto">
                  <Badge tone={ALERT_TONE[alert.level]}>{alert.level}</Badge>
                </span>
              </Card>
            </li>
          ))}
        </ul>
      ) : null}

      {data && data.n_students > 0 ? (
        <Card className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Stat label="Siswa aktif" value={String(data.n_students)} />
          <Stat label="Rata-rata penguasaan" value={percent(data.avg_mastery)} />
          <Stat label="Akurasi kuis" value={percent(data.avg_quiz_accuracy)} />
          <Stat label="Keterlibatan" value={percent(data.avg_engagement_index)} />
        </Card>
      ) : null}

      {roster.isLoading ? (
        <p role="status" className="text-ink-soft">
          Memuat
        </p>
      ) : null}

      {data && data.n_students === 0 ? (
        <EmptyState icon={<Users className="h-6 w-6" />} title="Belum ada siswa terdaftar." />
      ) : null}

      {data && data.n_students > 0 ? (
        <div className="overflow-x-auto rounded-[16px] border border-line bg-surface">
          <table className="w-full min-w-[38rem] border-collapse text-left">
            <caption className="sr-only">
              Daftar siswa dengan penguasaan, akurasi kuis, dan keterlibatan
            </caption>
            <thead>
              <tr className="border-b border-line text-sm text-ink-soft">
                <th scope="col" className="px-4 py-3 font-semibold">
                  Nama
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Penguasaan
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Akurasi kuis
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Sesi
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Miskonsepsi
                </th>
              </tr>
            </thead>
            <tbody>
              {data.students.map((student) => (
                <tr key={student.student_id} className="border-b border-line last:border-0">
                  <th scope="row" className="px-4 py-3 font-semibold">
                    <Link
                      href={`/guru/siswa/${student.student_id}`}
                      className="text-brand-deep underline underline-offset-4"
                    >
                      {student.student_name}
                    </Link>
                  </th>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="w-10 tabular-nums">{percent(student.overall_mastery)}</span>
                      <span className="w-24">
                        <Meter
                          value={student.overall_mastery}
                          label={`Penguasaan ${student.student_name}`}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 tabular-nums">{percent(student.quiz_accuracy)}</td>
                  <td className="px-4 py-3 tabular-nums">{student.n_sessions}</td>
                  <td className="px-4 py-3">
                    {student.open_misconceptions > 0 ? (
                      <Badge tone="warning">{student.open_misconceptions}</Badge>
                    ) : (
                      <span className="text-ink-soft">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
