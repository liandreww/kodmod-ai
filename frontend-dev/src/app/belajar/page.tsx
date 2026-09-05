"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, MessageSquare, Plus, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Composer } from "@/components/composer";
import { ThemeToggle } from "@/components/theme-toggle";
import { Transcript } from "@/components/transcript";
import { Button, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { ChatSessionDetail, ChatSessionSummary, Subject } from "@/lib/types";
import { useChat } from "@/lib/use-chat";
import { useSpeech } from "@/lib/use-speech";
import { cn, timeAgo } from "@/lib/utils";

const ALL_SUBJECTS = "";

export default function RuangBelajar() {
  const { user, signOut } = useAuth();
  const queryClient = useQueryClient();
  const speech = useSpeech();
  const [subjectId, setSubjectId] = useState<string>(ALL_SUBJECTS);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const onAnswer = useCallback(
    (text: string) => {
      void speech.speak(text);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    [speech, queryClient],
  );

  const chat = useChat({ onAnswer });

  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: () => api<Subject[]>("/subjects"),
  });

  const sessions = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api<ChatSessionSummary[]>("/chat/sessions"),
  });

  const openSession = useCallback(
    async (id: string) => {
      try {
        const detail = await api<ChatSessionDetail>(`/chat/sessions/${id}`);
        chat.resume(detail.id, detail.turns);
        if (detail.subject_id) setSubjectId(detail.subject_id);
        setSidebarOpen(false);
        return true;
      } catch {
        toast.error("Sesi tidak dapat dibuka.");
        return false;
      }
    },
    [chat],
  );

  function newSession() {
    speech.stop();
    chat.startNew();
    setSidebarOpen(false);
  }

  // A refresh, or any remount of this page, restarts `useChat` with the
  // session id it found in localStorage but no transcript to show for it —
  // reload that conversation once so "send another message" continues it
  // instead of silently starting a new one on the next send.
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const id = chat.sessionId;
    if (!id || chat.messages.length > 0) return;
    void openSession(id).then((ok) => {
      if (!ok) chat.startNew();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden">
      <a href="#composer" className="skip-link">
        Lompat ke kotak bicara
      </a>

      <header className="flex items-center gap-2 border-b border-line bg-surface px-4 py-3 sm:px-6">
        <Button
          variant="ghost"
          iconOnly
          onClick={() => setSidebarOpen((was) => !was)}
          aria-expanded={sidebarOpen}
          aria-controls="riwayat"
          className="lg:hidden"
        >
          <MessageSquare aria-hidden className="h-5 w-5" />
          <span className="sr-only">Riwayat sesi</span>
        </Button>

        <h1 className="mr-auto text-lg font-bold tracking-tight text-ink">Ruang Belajar</h1>

        <label htmlFor="subject" className="sr-only">
          Mata pelajaran
        </label>
        <Select
          id="subject"
          value={subjectId}
          onChange={(event) => setSubjectId(event.target.value)}
          className="w-auto max-w-[12rem]"
        >
          <option value={ALL_SUBJECTS}>Semua mata pelajaran</option>
          {subjects.data?.map((subject) => (
            <option key={subject.id} value={subject.id}>
              {subject.name}
            </option>
          ))}
        </Select>

        <Button
          variant="ghost"
          iconOnly
          onClick={speech.toggle}
          aria-pressed={speech.enabled}
          title={speech.enabled ? "Matikan suara" : "Bacakan jawaban"}
        >
          {speech.enabled ? (
            <Volume2 aria-hidden className="h-5 w-5" />
          ) : (
            <VolumeX aria-hidden className="h-5 w-5" />
          )}
          <span className="sr-only">
            {speech.enabled ? "Matikan pembacaan jawaban" : "Bacakan jawaban dengan suara"}
          </span>
        </Button>

        <ThemeToggle />

        <Button variant="ghost" iconOnly onClick={signOut} title="Keluar">
          <LogOut aria-hidden className="h-5 w-5" />
          <span className="sr-only">Keluar dari akun {user?.full_name}</span>
        </Button>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav
          id="riwayat"
          aria-label="Riwayat sesi"
          className={cn(
            "flex w-64 shrink-0 flex-col border-r border-line bg-surface",
            sidebarOpen ? "flex" : "hidden lg:flex",
          )}
        >
          <div className="shrink-0 p-3">
            <Button variant="secondary" onClick={newSession} className="w-full">
              <Plus aria-hidden className="h-4 w-4" />
              Sesi baru
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
            <ul className="flex flex-col gap-1">
              {sessions.data?.map((session) => (
                <li key={session.id}>
                  <button
                    type="button"
                    onClick={() => void openSession(session.id)}
                    aria-current={chat.sessionId === session.id ? "true" : undefined}
                    className={cn(
                      "w-full rounded-[10px] px-3 py-2 text-left",
                      chat.sessionId === session.id ? "bg-brand-wash" : "hover:bg-sunken",
                    )}
                  >
                    <span className="block truncate font-semibold text-ink">{session.title}</span>
                    <span className="block truncate text-sm text-ink-soft">
                      {[session.subject_name, timeAgo(session.started_at)]
                        .filter(Boolean)
                        .join(", ")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>

            {sessions.data?.length === 0 ? (
              <p className="mt-6 px-3 text-sm text-ink-soft">Belum ada sesi.</p>
            ) : null}
          </div>
        </nav>

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <Transcript
              messages={chat.messages}
              progress={chat.progress}
              readAloud={speech.enabled}
              onReplay={(text) => void speech.speak(text)}
            />
          </div>

          <div id="composer">
            {chat.status === "offline" ? (
              <p
                role="alert"
                className="mx-auto flex max-w-3xl items-center justify-between gap-3 border-t border-line bg-danger-wash px-4 py-3 text-danger sm:px-6"
              >
                Koneksi terputus.
                <Button variant="secondary" onClick={chat.reconnect} className="h-9 min-h-9">
                  Sambungkan lagi
                </Button>
              </p>
            ) : null}

            <Composer
              onSend={(text) => chat.send(text, subjectId || null)}
              busy={chat.status === "thinking"}
              disabled={chat.status === "offline" || chat.status === "connecting"}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
