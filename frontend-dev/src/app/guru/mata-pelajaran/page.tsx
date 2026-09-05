"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Card, EmptyState, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Subject } from "@/lib/types";

export default function SubjectsPage() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: () => api<Subject[]>("/subjects"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<Subject>("/subjects", {
        method: "POST",
        body: { name: name.trim(), description: description.trim() || null },
      }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setCreating(false);
      void queryClient.invalidateQueries({ queryKey: ["subjects"] });
      toast.success("Mata pelajaran dibuat.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal membuat mata pelajaran."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/subjects/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["subjects"] });
      toast.success("Mata pelajaran dihapus.");
    },
    onError: () => toast.error("Gagal menghapus."),
  });

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl font-bold tracking-tight text-ink">Mata pelajaran</h2>
        <Button onClick={() => setCreating((was) => !was)} aria-expanded={creating}>
          <Plus aria-hidden className="h-4 w-4" />
          Tambah
        </Button>
      </div>

      {creating ? (
        <Card>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) create.mutate();
            }}
            className="flex flex-col gap-4"
          >
            <Field label="Nama">
              {({ id }) => (
                <Input
                  id={id}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                  required
                />
              )}
            </Field>
            <Field label="Deskripsi">
              {({ id }) => (
                <Input
                  id={id}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              )}
            </Field>
            <div className="flex gap-2">
              <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
                Simpan
              </Button>
              <Button type="button" variant="secondary" onClick={() => setCreating(false)}>
                Batal
              </Button>
            </div>
          </form>
        </Card>
      ) : null}

      {subjects.isLoading ? (
        <p role="status" className="text-ink-soft">
          Memuat
        </p>
      ) : null}

      {subjects.data?.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="h-6 w-6" />}
          title="Belum ada mata pelajaran."
          action={<Button onClick={() => setCreating(true)}>Tambah mata pelajaran</Button>}
        />
      ) : null}

      <ul className="flex flex-col gap-3">
        {subjects.data?.map((subject) => (
          <li key={subject.id}>
            <Card className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/guru/mata-pelajaran/${subject.id}`}
                  className="text-lg font-bold text-brand-deep underline underline-offset-4"
                >
                  {subject.name}
                </Link>
                <p className="text-sm text-ink-soft">
                  {subject.n_concepts} konsep, {subject.n_documents} dokumen
                </p>
              </div>
              <Button
                variant="danger"
                iconOnly
                onClick={() => {
                  if (
                    window.confirm(
                      `Hapus "${subject.name}" beserta konsep dan dokumennya? Tindakan ini tidak dapat dibatalkan.`,
                    )
                  ) {
                    remove.mutate(subject.id);
                  }
                }}
                title={`Hapus ${subject.name}`}
              >
                <Trash2 aria-hidden className="h-5 w-5" />
                <span className="sr-only">Hapus {subject.name}</span>
              </Button>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
