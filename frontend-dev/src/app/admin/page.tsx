"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Role, User } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

const ROLE_LABEL: Record<Role, string> = { student: "Siswa", teacher: "Guru", admin: "Admin" };

export default function AdminUsers() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [form, setForm] = useState({
    username: "",
    password: "",
    full_name: "",
    role: "student" as Role,
  });

  const users = useQuery({
    queryKey: ["admin", "users", filter, search],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filter) params.set("role", filter);
      if (search.trim()) params.set("q", search.trim());
      const query = params.toString();
      return api<User[]>(`/admin/users${query ? `?${query}` : ""}`);
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });

  const create = useMutation({
    mutationFn: () => api<User>("/admin/users", { method: "POST", body: form }),
    onSuccess: () => {
      setForm({ username: "", password: "", full_name: "", role: "student" });
      setCreating(false);
      void invalidate();
      toast.success("Akun dibuat.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal membuat akun."),
  });

  const setActive = useMutation({
    mutationFn: (input: { id: string; is_active: boolean }) =>
      api<User>(`/admin/users/${input.id}`, {
        method: "PATCH",
        body: { is_active: input.is_active },
      }),
    onSuccess: () => void invalidate(),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal mengubah akun."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/admin/users/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void invalidate();
      toast.success("Akun dihapus.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Gagal menghapus akun."),
  });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl font-bold tracking-tight text-ink">Akun</h2>
        <Button onClick={() => setCreating((was) => !was)} aria-expanded={creating}>
          <Plus aria-hidden className="h-4 w-4" />
          Buat akun
        </Button>
      </div>

      {creating ? (
        <Card>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
            className="grid gap-4 sm:grid-cols-2"
          >
            <Field label="Nama lengkap">
              {({ id }) => (
                <Input
                  id={id}
                  value={form.full_name}
                  onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                  required
                  autoFocus
                />
              )}
            </Field>
            <Field label="Nama pengguna">
              {({ id }) => (
                <Input
                  id={id}
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                  autoCapitalize="none"
                  required
                />
              )}
            </Field>
            <Field label="Kata sandi" hint="Minimal 8 karakter.">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  type="text"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                  minLength={8}
                  required
                />
              )}
            </Field>
            <Field label="Peran">
              {({ id }) => (
                <Select
                  id={id}
                  value={form.role}
                  onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
                >
                  <option value="student">Siswa</option>
                  <option value="teacher">Guru</option>
                  <option value="admin">Admin</option>
                </Select>
              )}
            </Field>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" loading={create.isPending}>
                Simpan
              </Button>
              <Button type="button" variant="secondary" onClick={() => setCreating(false)}>
                Batal
              </Button>
            </div>
          </form>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-40">
          <Field label="Peran">
            {({ id }) => (
              <Select id={id} value={filter} onChange={(event) => setFilter(event.target.value)}>
                <option value="">Semua</option>
                <option value="student">Siswa</option>
                <option value="teacher">Guru</option>
                <option value="admin">Admin</option>
              </Select>
            )}
          </Field>
        </div>
        <div className="min-w-[12rem] flex-1">
          <Field label="Cari">
            {({ id }) => (
              <Input
                id={id}
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Nama atau nama pengguna"
              />
            )}
          </Field>
        </div>
      </div>

      <div className="overflow-x-auto rounded-[16px] border border-line bg-surface">
        <table className="w-full min-w-[42rem] border-collapse text-left">
          <caption className="sr-only">Daftar akun</caption>
          <thead>
            <tr className="border-b border-line text-sm text-ink-soft">
              <th scope="col" className="px-4 py-3 font-semibold">Nama</th>
              <th scope="col" className="px-4 py-3 font-semibold">Nama pengguna</th>
              <th scope="col" className="px-4 py-3 font-semibold">Peran</th>
              <th scope="col" className="px-4 py-3 font-semibold">Terakhir masuk</th>
              <th scope="col" className="px-4 py-3 font-semibold">Tindakan</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((account) => {
              const self = account.id === me?.id;
              return (
                <tr key={account.id} className="border-b border-line last:border-0">
                  <th scope="row" className="px-4 py-3 font-semibold text-ink">
                    {account.full_name}
                    {!account.is_active ? (
                      <span className="ml-2">
                        <Badge tone="danger">Nonaktif</Badge>
                      </span>
                    ) : null}
                  </th>
                  <td className="px-4 py-3 font-mono text-sm">{account.username}</td>
                  <td className="px-4 py-3">{ROLE_LABEL[account.role]}</td>
                  <td className="px-4 py-3 text-ink-soft">
                    {account.last_login_at ? timeAgo(account.last_login_at) : "belum pernah"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        className="h-9 min-h-9 px-3 text-sm"
                        disabled={self}
                        onClick={() =>
                          setActive.mutate({ id: account.id, is_active: !account.is_active })
                        }
                      >
                        {account.is_active ? "Nonaktifkan" : "Aktifkan"}
                      </Button>
                      <Button
                        variant="danger"
                        iconOnly
                        disabled={self}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Hapus akun ${account.full_name} beserta seluruh datanya? Tindakan ini tidak dapat dibatalkan.`,
                            )
                          ) {
                            remove.mutate(account.id);
                          }
                        }}
                        title={`Hapus ${account.full_name}`}
                      >
                        <Trash2 aria-hidden className="h-5 w-5" />
                        <span className="sr-only">Hapus {account.full_name}</span>
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {users.data?.length === 0 ? <p className="text-ink-soft">Tidak ada akun yang cocok.</p> : null}
    </div>
  );
}
