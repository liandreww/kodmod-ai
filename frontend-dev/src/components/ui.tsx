"use client";

import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { forwardRef, useId } from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  // brand-deep, not brand: #11999E on white is 3.5:1 and fails AA for label text.
  primary: "bg-brand-deep text-white hover:opacity-90 border border-transparent",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-sunken",
  ghost: "bg-transparent text-ink border border-transparent hover:bg-brand-wash",
  danger: "bg-transparent text-danger border border-danger hover:bg-danger-wash",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  /** Renders icon-only; the label still reaches screen readers. */
  iconOnly?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", loading, iconOnly, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[10px] font-semibold",
        "transition-opacity disabled:opacity-50 disabled:cursor-not-allowed",
        // 44px minimum target, which is the smallest reliably hittable size.
        iconOnly ? "h-11 w-11" : "min-h-11 px-4 py-2",
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  );
});

/* -------------------------------------------------------------------------- */
/* Field                                                                       */
/* -------------------------------------------------------------------------- */

interface FieldProps {
  label: string;
  error?: string;
  hint?: string;
  children: (props: { id: string; describedBy: string | undefined }) => ReactNode;
}

/**
 * Label, control, and message wired together by id.
 *
 * The error is rendered inside the described-by region rather than as loose
 * text, so a screen reader announces the problem when focus lands on the field
 * instead of leaving the user to hunt for it.
 */
export function Field({ label, error, hint, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-semibold text-ink">
        {label}
      </label>
      {hint ? (
        <p id={hintId} className="text-sm text-ink-soft">
          {hint}
        </p>
      ) : null}
      {children({ id, describedBy })}
      {error ? (
        <p id={errorId} className="text-sm font-semibold text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "min-h-11 w-full rounded-[10px] border border-line-strong bg-surface px-3 py-2",
          "text-ink placeholder:text-ink-soft",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...props }, ref) {
    return (
      <select
        ref={ref}
        className={cn(
          "min-h-11 w-full rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-ink",
          className,
        )}
        {...props}
      >
        {children}
      </select>
    );
  },
);

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                    */
/* -------------------------------------------------------------------------- */

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-[16px] border border-line bg-surface p-5", className)}>
      {children}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  action,
}: {
  icon?: ReactNode;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[16px] border border-dashed border-line-strong px-6 py-12 text-center">
      {icon ? <span className="text-brand">{icon}</span> : null}
      <p className="text-ink-soft">{title}</p>
      {action}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-sm text-ink-soft">{label}</span>
      <span className="text-2xl font-bold tabular-nums text-ink">{value}</span>
    </div>
  );
}

const BADGE_TONES = {
  neutral: "bg-sunken text-ink-soft border-line",
  brand: "bg-brand-wash text-brand-deep border-brand",
  danger: "bg-danger-wash text-danger border-danger",
  warning: "bg-warning-wash text-warning border-warning",
} as const;

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof BADGE_TONES;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-sm font-semibold",
        BADGE_TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

/** A horizontal meter. `label` is what a screen reader reads. */
export function Meter({ value, label }: { value: number; label: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-2 w-full overflow-hidden rounded-full bg-sunken"
    >
      <div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
    </div>
  );
}
