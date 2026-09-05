"use client";

import { ChevronDown, FileText, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge, Button } from "@/components/ui";
import type { Message } from "@/lib/use-chat";
import { cn } from "@/lib/utils";

/** Labels for the intents worth showing the student. Anything else stays hidden. */
const INTENT_LABELS: Record<string, string> = {
  quiz: "Kuis",
  exercise_request: "Latihan soal",
  tutoring: "Penjelasan",
  analytics: "Analisis",
};

function intentBadgeText(message: Message): string | null {
  const label = message.intent ? INTENT_LABELS[message.intent] : undefined;
  if (!label) return null;
  if (message.intent === "quiz" && message.quizProgress) {
    return `${label} · soal ${message.quizProgress.index + 1}/${message.quizProgress.total}`;
  }
  return label;
}

interface Props {
  messages: Message[];
  progress: string | null;
  readAloud: boolean;
  onReplay: (text: string) => void;
}

/**
 * The conversation.
 *
 * Streaming text plus `aria-live` makes a screen reader re-announce the growing
 * paragraph on every token, which is unusable. So the streaming bubble is
 * hidden from assistive tech entirely, and the settled answer is announced once
 * through a separate live region when it is complete.
 */
export function Transcript({ messages, progress, readAloud, onReplay }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  // Derived, not stored: the live region announces because its text node
  // changed, so an extra piece of state would only add a render.
  const announcement =
    [...messages].reverse().find((m) => m.role === "assistant" && !m.streaming)?.text ?? "";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, progress]);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      {/* Announced once per completed answer, never token by token. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {messages.length === 0 ? (
        <div className="py-16 text-center">
          <h2 className="text-2xl font-bold tracking-tight text-ink">Mau belajar apa hari ini?</h2>
          <p className="mt-2 text-ink-soft">Tekan spasi untuk mulai bicara.</p>
        </div>
      ) : null}

      <ol className="flex flex-col gap-6">
        {messages.map((message) => (
          <li
            key={message.id}
            className={cn(
              "animate-rise",
              message.role === "student" ? "flex justify-end" : "flex justify-start",
            )}
          >
            {message.role === "student" ? (
              <p className="max-w-[85%] rounded-[16px] rounded-br-sm bg-brand-deep px-4 py-3 text-white">
                <span className="sr-only">Kamu bertanya: </span>
                {message.text}
              </p>
            ) : (
              <div className="w-full max-w-[92%]">
                <div
                  // While streaming this is a visual preview only; the settled
                  // text is announced through the live region above.
                  aria-hidden={message.streaming ? true : undefined}
                  className="rounded-[16px] rounded-bl-sm border border-line bg-surface px-4 py-3 text-[1.0625rem] leading-[1.75] text-ink"
                >
                  {message.text}
                  {message.streaming ? (
                    <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.15em] bg-brand" />
                  ) : null}
                </div>

                {!message.streaming ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {intentBadgeText(message) ? (
                      <Badge tone={message.intent === "quiz" ? "brand" : "neutral"}>
                        {intentBadgeText(message)}
                      </Badge>
                    ) : null}
                    {readAloud ? (
                      <Button
                        variant="ghost"
                        onClick={() => onReplay(message.text)}
                        className="h-9 min-h-9 px-2 text-sm"
                      >
                        <Volume2 aria-hidden className="h-4 w-4" />
                        Dengarkan lagi
                      </Button>
                    ) : null}
                    {message.sources?.length ? <Sources sources={message.sources} /> : null}
                  </div>
                ) : null}
              </div>
            )}
          </li>
        ))}
      </ol>

      {progress ? (
        <p role="status" className="mt-6 flex items-center gap-2 text-ink-soft">
          <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
          {progress}
        </p>
      ) : null}

      <div ref={endRef} />
    </div>
  );
}

/** Windows paths arrive with the other separator, hence the char code. */
const SEPARATOR = String.fromCharCode(92);

/** Show just the file name; the stored path is a server detail. */
function basename(path: string): string {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf(SEPARATOR));
  return cut >= 0 ? path.slice(cut + 1) : path;
}

function Sources({ sources }: { sources: NonNullable<Message["sources"]> }) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <Button
        variant="ghost"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="h-9 min-h-9 px-2 text-sm"
      >
        <FileText aria-hidden className="h-4 w-4" />
        {sources.length} sumber
        <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
      </Button>

      {open ? (
        <ul className="mt-2 flex flex-col gap-1 rounded-[10px] bg-sunken px-3 py-2 text-sm text-ink-soft">
          {sources.map((source) => (
            <li key={source.source}>
              {source.section_title ? `${source.section_title}, ` : ""}
              {basename(source.source)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
