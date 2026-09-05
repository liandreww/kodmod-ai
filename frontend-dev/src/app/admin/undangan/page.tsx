"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, EmptyState, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { InvitationCode } from "@/lib/types";
import { formatDate, timeAgo } from "@/lib/utils";

export default function Invitations() {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [maxUses, setMaxUses] = useState(1);
  const [expiresInDays, setExpiresInDays] = useState<string>("");
  const [copied, setCopied] = useState<string | null>(null);

  const codes = useQuery({
    queryKey: ["admin", "invitations"],
    queryFn: () => api<InvitationCode[]>("/admin/invitations"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<InvitationCode>("/admin/invitations", {
        method: "POST",
        body: {
          label: label.trim() || null,
          max_uses: maxUses,
          expires_in_days: expiresInDays ? Number(expiresInDays) : null,
        },
      }),
    onSuccess: (created) => {
      setLabel("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "invitations"] });
      toast.success(`Kode ${created.code} dibuat.`);
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal membuat kode."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/admin/invitations/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "invitations"] });
      toast.success("Kode dicabut.");
    },
    onError: () => toast.error("Gagal mencabut kode."),
  });

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(code);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.error("Salin gagal. Catat kodenya secara manual.");
    }
  }

  function statusOf(code: InvitationCode): { label: string; tone: "brand" | "neutral" | "danger" } {
    if (!code.is_active) return { label: "Dicabut", tone: "danger" };
    if (code.used_count >= code.max_uses) return { label: "Habis", tone: "neutral" };
    if (code.expires_at && new Date(code.expires_at) <= new Date()) {
      return { label: "Kedaluwarsa", tone: "neutral" };
    }
    return { label: "Aktif", tone: "brand" };
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <h2 className="text-2xl font-bold tracking-tight text-ink">Kode undangan</h2>

      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="min-w-[12rem] flex-1">
            <Field label="Keterangan">
              {({ id }) => (
                <Input
                  id={id}
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="Kelas 7A"
                />
              )}
            </Field>
          </div>
          <div className="w-32">
            <Field label="Jumlah pakai">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={1}
                  max={1000}
                  value={maxUses}
                  onChange={(event) => setMaxUses(Number(event.target.value) || 1)}
                />
              )}
            </Field>
          </div>
          <div className="w-36">
            <Field label="Berlaku (hari)">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={1}
                  max={365}
                  value={expiresInDays}
                  onChange={(event) => setExpiresInDays(event.target.value)}
                  placeholder="Selamanya"
                />
              )}
            </Field>
          </div>
          <Button type="submit" loading={create.isPending}>
            <Plus aria-hidden className="h-4 w-4" />
            Buat kode
          </Button>
        </form>
      </Card>

      {codes.data?.length === 0 ? (
        <EmptyState icon={<KeyRound className="h-6 w-6" />} title="Belum ada kode undangan." />
      ) : null}

      <ul className="flex flex-col gap-2">
        {codes.data?.map((code) => {
          const status = statusOf(code);
          return (
            <li key={code.id}>
              <Card className="flex flex-wrap items-center gap-4 py-3">
                <code className="font-mono text-xl font-semibold tracking-[0.2em] text-ink">
                  {code.code}
                </code>

                <Button
                  variant="ghost"
                  iconOnly
                  onClick={() => void copy(code.code)}
                  title={`Salin ${code.code}`}
                >
                  {copied === code.code ? (
                    <Check aria-hidden className="h-5 w-5" />
                  ) : (
                    <Copy aria-hidden className="h-5 w-5" />
                  )}
                  <span className="sr-only">Salin kode {code.code}</span>
                </Button>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-ink">{code.label ?? "Tanpa keterangan"}</p>
                  <p className="text-sm text-ink-soft">
                    {code.used_count} dari {code.max_uses} terpakai, dibuat{" "}
                    {timeAgo(code.created_at)}
                    {code.expires_at ? `, berlaku sampai ${formatDate(code.expires_at)}` : ""}
                  </p>
                </div>

                <Badge tone={status.tone}>{status.label}</Badge>

                <Button
                  variant="danger"
                  iconOnly
                  onClick={() => {
                    if (window.confirm(`Cabut kode ${code.code}?`)) remove.mutate(code.id);
                  }}
                  title={`Cabut ${code.code}`}
                >
                  <Trash2 aria-hidden className="h-5 w-5" />
                  <span className="sr-only">Cabut kode {code.code}</span>
                </Button>
              </Card>
            </li>
          );
        })}
      </ul>

      <p className="text-sm text-ink-soft">
        Kode menentukan siapa yang boleh mendaftar, bukan perannya. Peran dipilih pendaftar sendiri,
        dan akun admin hanya dibuat dari halaman Akun.
      </p>
    </div>
  );
}
