"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, EmptyState, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Concept, CurriculumDocument, DocumentStatus, Subject } from "@/lib/types";
import { formatBytes, slugify, timeAgo } from "@/lib/utils";

const STATUS: Record<DocumentStatus, { label: string; tone: "neutral" | "brand" | "danger" }> = {
  pending: { label: "Menunggu", tone: "neutral" },
  processing: { label: "Diproses", tone: "neutral" },
  ready: { label: "Siap dicari", tone: "brand" },
  failed: { label: "Gagal", tone: "danger" },
};

const DIFFICULTIES = ["beginner", "easy", "medium", "hard", "expert"] as const;

export default function SubjectDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [conceptName, setConceptName] = useState("");
  const [difficulty, setDifficulty] = useState<string>("medium");

  const subject = useQuery({
    queryKey: ["subject", id],
    queryFn: () => api<Subject>(`/subjects/${id}`),
  });

  const concepts = useQuery({
    queryKey: ["subject", id, "concepts"],
    queryFn: () => api<Concept[]>(`/subjects/${id}/concepts`),
  });

  const documents = useQuery({
    queryKey: ["subject", id, "documents"],
    queryFn: () => api<CurriculumDocument[]>(`/subjects/${id}/documents`),
    // Ingestion runs in the background, so poll while anything is still moving.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "pending" || d.status === "processing")
        ? 2000
        : false,
  });

  const addConcept = useMutation({
    mutationFn: () =>
      api<Concept>(`/subjects/${id}/concepts`, {
        method: "POST",
        body: {
          subject_id: id,
          name: conceptName.trim(),
          slug: slugify(conceptName),
          difficulty_level: difficulty,
        },
      }),
    onSuccess: () => {
      setConceptName("");
      void queryClient.invalidateQueries({ queryKey: ["subject", id, "concepts"] });
      toast.success("Konsep ditambahkan.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal menambah konsep."),
  });

  const removeDocument = useMutation({
    mutationFn: (documentId: string) => api<void>(`/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["subject", id, "documents"] });
      toast.success("Dokumen dihapus.");
    },
    onError: () => toast.error("Gagal menghapus dokumen."),
  });

  async function upload(file: File) {
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api<CurriculumDocument>(`/subjects/${id}/documents`, { method: "POST", body: form });
      void queryClient.invalidateQueries({ queryKey: ["subject", id, "documents"] });
      toast.success("Dokumen diunggah, sedang diproses.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Unggahan gagal.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <Link
        href="/guru/mata-pelajaran"
        className="inline-flex w-fit items-center gap-2 font-semibold text-brand-deep underline underline-offset-4"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Semua mata pelajaran
      </Link>

      <h2 className="text-2xl font-bold tracking-tight text-ink">
        {subject.data?.name ?? "Memuat"}
      </h2>

      <section>
        <h3 className="mb-3 text-xl font-bold tracking-tight text-ink">Dokumen</h3>

        <Card className="flex flex-wrap items-center gap-3">
          <label htmlFor="dokumen" className="sr-only">
            Pilih berkas PDF, Markdown, atau teks
          </label>
          <input
            ref={fileRef}
            id="dokumen"
            type="file"
            accept=".pdf,.md,.txt"
            disabled={uploading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
            className="min-h-11 flex-1 rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-ink file:mr-3 file:rounded-[8px] file:border-0 file:bg-brand-deep file:px-3 file:py-1.5 file:font-semibold file:text-white"
          />
          {uploading ? (
            <span role="status" className="flex items-center gap-2 text-ink-soft">
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
              Mengunggah
            </span>
          ) : (
            <span className="flex items-center gap-2 text-sm text-ink-soft">
              <Upload aria-hidden className="h-4 w-4" />
              PDF, MD, TXT
            </span>
          )}
        </Card>

        {documents.data?.length === 0 ? (
          <div className="mt-3">
            <EmptyState title="Belum ada dokumen. Unggah materi agar tutor dapat mengutipnya." />
          </div>
        ) : null}

        <ul className="mt-3 flex flex-col gap-2">
          {documents.data?.map((document) => (
            <li key={document.id}>
              <Card className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-ink">{document.filename}</p>
                  <p className="text-sm text-ink-soft">
                    {formatBytes(document.size_bytes)}
                    {document.status === "ready" ? `, ${document.n_chunks} potongan` : ""}
                    {`, ${timeAgo(document.created_at)}`}
                  </p>
                  {document.error_message ? (
                    <p className="mt-1 flex items-center gap-1.5 text-sm text-danger">
                      <AlertCircle aria-hidden className="h-4 w-4" />
                      {document.error_message}
                    </p>
                  ) : null}
                </div>

                <Badge tone={STATUS[document.status].tone}>
                  {document.status === "ready" ? (
                    <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
                  ) : document.status === "failed" ? (
                    <AlertCircle aria-hidden className="h-3.5 w-3.5" />
                  ) : (
                    <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />
                  )}
                  {STATUS[document.status].label}
                </Badge>

                <Button
                  variant="danger"
                  iconOnly
                  onClick={() => {
                    if (window.confirm(`Hapus "${document.filename}" dan hasil indeksnya?`)) {
                      removeDocument.mutate(document.id);
                    }
                  }}
                  title={`Hapus ${document.filename}`}
                >
                  <Trash2 aria-hidden className="h-5 w-5" />
                  <span className="sr-only">Hapus {document.filename}</span>
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="mb-3 text-xl font-bold tracking-tight text-ink">Konsep</h3>

        <Card>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (conceptName.trim()) addConcept.mutate();
            }}
            className="flex flex-wrap items-end gap-3"
          >
            <div className="min-w-[12rem] flex-1">
              <Field label="Nama konsep">
                {({ id: fieldId }) => (
                  <Input
                    id={fieldId}
                    value={conceptName}
                    onChange={(event) => setConceptName(event.target.value)}
                  />
                )}
              </Field>
            </div>
            <div className="w-40">
              <Field label="Tingkat">
                {({ id: fieldId }) => (
                  <Select
                    id={fieldId}
                    value={difficulty}
                    onChange={(event) => setDifficulty(event.target.value)}
                  >
                    {DIFFICULTIES.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
            <Button type="submit" loading={addConcept.isPending} disabled={!conceptName.trim()}>
              Tambah
            </Button>
          </form>
        </Card>

        <ul className="mt-3 flex flex-col gap-2">
          {concepts.data?.map((concept) => (
            <li key={concept.id}>
              <Card className="flex items-center gap-3 py-3">
                <span className="flex-1 font-semibold text-ink">{concept.name}</span>
                <Badge>{concept.difficulty_level}</Badge>
                <span className="font-mono text-sm text-ink-soft">{concept.slug}</span>
              </Card>
            </li>
          ))}
        </ul>

        {concepts.data?.length === 0 ? (
          <div className="mt-3">
            <EmptyState title="Belum ada konsep." />
          </div>
        ) : null}
      </section>
    </div>
  );
}
