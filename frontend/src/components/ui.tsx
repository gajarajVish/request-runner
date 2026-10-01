import { type ButtonHTMLAttributes, type ReactNode, useState } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "secondary", size = "md", className, busy, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 border-transparent shadow-sm",
    secondary: "bg-white text-slate-700 border-slate-300 hover:bg-slate-50 shadow-sm",
    ghost: "bg-transparent text-slate-600 border-transparent hover:bg-slate-100",
    danger: "bg-white text-red-700 border-red-300 hover:bg-red-50",
  }[variant];
  const s = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm";
  return (
    <button className={cx("inline-flex items-center gap-1.5 rounded-md border font-medium transition disabled:cursor-not-allowed disabled:opacity-50", v, s, className)} disabled={busy || rest.disabled} {...rest}>
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)} aria-hidden />;
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cx("rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
          <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-brand-50 text-brand-700 ring-brand-100",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "slate", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

export const STATE_TONE: Record<string, Tone> = {
  scoping: "slate",
  waiting_requester: "amber",
  ready_to_send: "blue",
  waiting_provider: "blue",
  checking: "violet",
  needs_more: "amber",
  handed_back: "red",
  complete: "green",
  closed_by_provider: "slate",
  accepted: "green",
  cancelled: "slate",
};

export function StateBadge({ state, label }: { state: string; label?: string }) {
  return <Badge tone={STATE_TONE[state] ?? "slate"}>{label ?? state.replace(/_/g, " ")}</Badge>;
}

export const VERDICT: Record<string, { tone: Tone; label: string; icon: string }> = {
  met: { tone: "green", label: "Met", icon: "✓" },
  partly_met: { tone: "amber", label: "Partly met", icon: "◐" },
  not_met: { tone: "red", label: "Not met", icon: "✕" },
  unreadable: { tone: "violet", label: "Unreadable", icon: "?" },
  pending: { tone: "slate", label: "Waiting", icon: "…" },
  not_applicable: { tone: "slate", label: "N/A", icon: "–" },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const v = VERDICT[verdict] ?? VERDICT.pending;
  return (
    <Badge tone={v.tone}>
      <span aria-hidden>{v.icon}</span> {v.label}
    </Badge>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">{children}</div>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="mt-2 text-sm text-red-600">{error instanceof Error ? error.message : String(error)}</p>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputBase = "rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100";
export const inputCls = "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100";

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", value === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-slate-500 hover:text-slate-700">
        <span className={cx("inline-block transition", open && "rotate-90")}>▸</span>
        {summary}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:p-10" onMouseDown={onClose}>
      <div className={cx("w-full rounded-lg bg-white shadow-xl", wide ? "max-w-4xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            ✕
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function FlagList({ flags }: { flags: { code: string; message: string; blocking?: boolean }[] }) {
  if (!flags?.length) return null;
  return (
    <ul className="space-y-1">
      {flags.map((f) => (
        <li key={f.code} className={cx("rounded-md px-2.5 py-1.5 text-xs", f.blocking ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900")}>
          <span className="font-semibold">{f.code.replace(/_/g, " ")}</span> · {f.message}
        </li>
      ))}
    </ul>
  );
}
