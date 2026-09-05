"use client";

import { Loader2, Mic, Send, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { getToken } from "@/lib/api";
import { useRecorder } from "@/lib/use-recorder";
import { cn } from "@/lib/utils";

type Phase = "idle" | "listening" | "transcribing" | "thinking";

const TEXTAREA_MAX_HEIGHT = 200;

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Tekan untuk bicara",
  listening: "Mendengarkan",
  transcribing: "Menulis",
  thinking: "Menjawab",
};

interface Props {
  onSend: (text: string) => void;
  busy: boolean;
  disabled?: boolean;
}

/**
 * The composer.
 *
 * In a normal chat the microphone is a small icon beside a large text box. Here
 * that is inverted, because voice is the primary input for this product: the
 * press-to-talk control is the widest thing on the page and carries the one
 * status label that tells the student what the system is doing. Typing is the
 * quieter second row, always present so testing costs nothing, never the
 * headline.
 */
export function Composer({ onSend, busy, disabled }: Props) {
  const { recording, level, error, start, stop, cancel } = useRecorder();
  const [transcribing, setTranscribing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const talkRef = useRef<HTMLButtonElement>(null);

  const phase: Phase = recording
    ? "listening"
    : transcribing
      ? "transcribing"
      : busy
        ? "thinking"
        : "idle";

  useEffect(() => {
    if (error) toast.error(error);
  }, [error]);

  const transcribe = useCallback(
    async (blob: Blob) => {
      setTranscribing(true);
      try {
        const form = new FormData();
        form.append("audio", blob, "rekaman.webm");
        form.append("language", "id");

        const token = getToken();
        const response = await fetch("/api/transcribe", {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        });
        const body = (await response.json()) as { text?: string; error?: string };

        if (!response.ok) {
          toast.error(body.error ?? "Transkripsi gagal.");
          return;
        }
        const text = (body.text ?? "").trim();
        if (!text) {
          toast.error("Tidak ada suara yang terdengar.");
          return;
        }
        onSend(text);
      } catch {
        toast.error("Tidak dapat menghubungi layanan transkripsi.");
      } finally {
        setTranscribing(false);
      }
    },
    [onSend],
  );

  const toggleTalk = useCallback(async () => {
    if (recording) {
      const blob = await stop();
      if (blob) await transcribe(blob);
      return;
    }
    await start();
  }, [recording, start, stop, transcribe]);

  // Space starts and stops recording from anywhere; Escape throws the recording
  // away. Both are ignored while the caret is in a text field, where Space is
  // just a space.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable;

      if (event.code === "Space" && !typing && !event.repeat) {
        event.preventDefault();
        void toggleTalk();
      } else if (event.key === "Escape" && recording) {
        event.preventDefault();
        cancel();
        toast("Rekaman dibatalkan.");
      } else if (event.key === "/" && !typing) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleTalk, cancel, recording]);

  function submitDraft(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    onSend(text);
  }

  function onDraftKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function onDraftChange(event: React.ChangeEvent<HTMLTextAreaElement>) {
    setDraft(event.target.value);
    const textarea = event.target;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, TEXTAREA_MAX_HEIGHT)}px`;
  }

  const talkDisabled = disabled || transcribing || (busy && !recording);

  return (
    <div className="border-t border-line bg-surface">
      <div className="mx-auto w-full max-w-3xl px-4 py-4 sm:px-6">
        <button
          ref={talkRef}
          type="button"
          onClick={() => void toggleTalk()}
          disabled={talkDisabled}
          aria-pressed={recording}
          className={cn(
            "flex min-h-[88px] w-full items-center gap-4 rounded-[16px] border-2 px-5 text-left",
            "transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
            recording
              ? "border-accent bg-brand-wash"
              : "border-line-strong bg-sunken hover:border-brand",
          )}
        >
          <span
            className={cn(
              "relative flex h-14 w-14 shrink-0 items-center justify-center rounded-full",
              recording ? "recording-ring bg-brand-deep text-white" : "bg-brand-deep text-white",
            )}
            style={
              recording
                ? { transform: `scale(${1 + Math.min(level, 1) * 0.18})` }
                : undefined
            }
          >
            {transcribing || (busy && !recording) ? (
              <Loader2 aria-hidden className="h-6 w-6 animate-spin" />
            ) : recording ? (
              <Square aria-hidden className="h-5 w-5" fill="currentColor" />
            ) : (
              <Mic aria-hidden className="h-6 w-6" />
            )}
          </span>

          <span className="flex flex-col">
            <span className="text-lg font-bold text-ink">{PHASE_LABEL[phase]}</span>
            <span className="text-sm text-ink-soft">
              {recording ? "Spasi untuk kirim, Escape untuk batal" : "Spasi"}
            </span>
          </span>
        </button>

        <form onSubmit={submitDraft} className="mt-3 flex items-center gap-2">
          <label htmlFor="chat-text" className="sr-only">
            Ketik pertanyaan
          </label>
          <textarea
            ref={inputRef}
            id="chat-text"
            value={draft}
            onChange={onDraftChange}
            onKeyDown={onDraftKeyDown}
            disabled={disabled}
            placeholder="Atau ketik di sini"
            autoComplete="off"
            rows={1}
            className="min-h-11 flex-1 resize-none overflow-y-hidden rounded-[10px] border border-line bg-surface px-3 py-2 text-ink placeholder:text-ink-soft"
          />
          <Button type="submit" iconOnly disabled={disabled || !draft.trim()} title="Kirim">
            <Send aria-hidden className="h-5 w-5" />
            <span className="sr-only">Kirim pesan</span>
          </Button>
        </form>
      </div>
    </div>
  );
}
