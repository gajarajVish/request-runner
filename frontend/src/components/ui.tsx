import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// --------------------------------------------------------------------------- icons (16px, 1.5 stroke)

const PATHS = {
  requests: "M4 4.5h12M4 10h12M4 15.5h7",
  imports: "M10 3v9m0 0-3.5-3.5M10 12l3.5-3.5M4 14v1.5A1.5 1.5 0 0 0 5.5 17h9a1.5 1.5 0 0 0 1.5-1.5V14",
  dashboard: "M3.5 3.5h5v6h-5zM11.5 3.5h5v3.5h-5zM11.5 10h5v6.5h-5zM3.5 12.5h5v4h-5z",
  inbox: "M3 11h4l1.5 2h3L13 11h4M3 11l2-6.5h10L17 11v4.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  activity: "M2.5 10h3l2-5.5 5 11 2-5.5h3",
  plus: "M10 4v12M4 10h12",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12Zm7 2-3-3",
  check: "m4.5 10.5 3.5 3.5 7.5-8",
  x: "m5 5 10 10M15 5 5 15",
  chevronRight: "m8 5 5 5-5 5",
  chevronDown: "m5 8 5 5 5-5",
  back: "M12 5 7 10l5 5",
  clock: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm0-10v3.5l2.5 1.5",
  file: "M11.5 3H6a1.5 1.5 0 0 0-1.5 1.5v11A1.5 1.5 0 0 0 6 17h8a1.5 1.5 0 0 0 1.5-1.5V7m-4-4 4 4m-4-4v4h4",
  mail: "M3 5.5h14v9H3zm0 0 7 5 7-5",
  alert: "M10 7.5v3.5m0 2.5v.01M8.6 3.6 2.7 14a1.6 1.6 0 0 0 1.4 2.4h11.8a1.6 1.6 0 0 0 1.4-2.4L11.4 3.6a1.6 1.6 0 0 0-2.8 0Z",
  more: "M5 10h.01M10 10h.01M15 10h.01",
  user: "M10 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5.5 6.5a5.5 5.5 0 0 1 11 0",
  upload: "M10 13V4m0 0L6.5 7.5M10 4l3.5 3.5M4 13v2.5A1.5 1.5 0 0 0 5.5 17h9a1.5 1.5 0 0 0 1.5-1.5V13",
  shield: "M10 2.5 4 5v4.5c0 3.7 2.6 6.6 6 8 3.4-1.4 6-4.3 6-8V5z",
  sparkle: "M10 3v3m0 8v3M3 10h3m8 0h3M5.5 5.5l2 2m5 5 2 2m0-9-2 2m-5 5-2 2",
  menu: "M3.5 5.5h13M3.5 10h13M3.5 14.5h13",
  logout: "M8 4H5.5A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8m5-9 3 3-3 3m3-3H8",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 4v3.5h-3.5",
  send: "M17 3 8.5 11.5M17 3l-5 14-3.5-5.5L3 8z",
  calendar: "M4 5.5h12V16H4zM4 9h12M7 3.5v3M13 3.5v3",
} as const;
export type IconName = keyof typeof PATHS;

export function Icon({ name, className, size = 16 }: { name: IconName; className?: string; size?: number }) {
  return (
    <svg viewBox="0 0 20 20" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={cx("shrink-0", className)} aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  );
}

// --------------------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "secondary", size = "md", className, busy, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  const v = {
    primary: "border-brand-700 bg-brand-600 text-white shadow-xs hover:bg-brand-700 disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none",
    secondary: "border-slate-300 bg-white text-slate-700 shadow-xs hover:border-slate-400 hover:bg-slate-50 disabled:text-slate-400",
    ghost: "border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-400",
    danger: "border-red-300 bg-white text-red-700 shadow-xs hover:border-red-400 hover:bg-red-50 disabled:text-red-300",
  }[variant];
  const s = size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]";
  return (
    <button className={cx("inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-medium transition-colors disabled:cursor-not-allowed", v, s, className)} disabled={busy || rest.disabled} {...rest}>
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)} aria-hidden />;
}

/** Overflow menu for secondary / destructive actions. */
export function Menu({ label = "More actions", items }: { label?: string; items: ({ label: string; onClick: () => void; danger?: boolean; hint?: string } | false | null | undefined)[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const list = items.filter(Boolean) as { label: string; onClick: () => void; danger?: boolean; hint?: string }[];
  if (!list.length) return null;
  return (
    <div className="relative" ref={ref}>
      <Button aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} className="w-8 px-0">
        <Icon name="more" />
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-56 rounded-md border border-slate-200 bg-white p-1 shadow-pop">
          {list.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                it.onClick();
              }}
              className={cx("block w-full rounded px-2.5 py-1.5 text-left text-[13px]", it.danger ? "text-red-700 hover:bg-red-50" : "text-slate-700 hover:bg-slate-100")}
            >
              {it.label}
              {it.hint && <span className="block text-2xs text-slate-500">{it.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- layout

export function PageHeader({ title, eyebrow, meta, actions, back }: { title: ReactNode; eyebrow?: ReactNode; meta?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-slate-200 pb-4">
      <div className="min-w-0">
        {back}
        {eyebrow && <p className="text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">{eyebrow}</p>}
        <h1 className="mt-0.5 text-[20px] font-semibold tracking-tight text-slate-900">{title}</h1>
        {meta && <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-slate-600">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className, title, actions, flush }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; flush?: boolean }) {
  return (
    <section className={cx("rounded-md border border-slate-200 bg-white shadow-xs", className)}>
      {(title || actions) && (
        <header className="flex min-h-10 items-center justify-between gap-3 border-b border-slate-200 px-4 py-2">
          <h3 className="text-[13px] font-semibold text-slate-900">{title}</h3>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

/** KPI tile. `onClick` makes it a filter toggle. */
export function Stat({ label, value, sub, tone, active, onClick }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "danger" | "warning" | "success" | "brand"; active?: boolean; onClick?: () => void }) {
  const color = { default: "text-slate-900", danger: "text-red-700", warning: "text-amber-700", success: "text-emerald-700", brand: "text-brand-700" }[tone ?? "default"];
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      aria-pressed={onClick ? !!active : undefined}
      className={cx(
        "rounded-md border bg-white px-4 py-3 text-left shadow-xs",
        active ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200",
        onClick && "transition-colors hover:border-slate-300",
      )}
    >
      <p className="text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={cx("mt-1 text-[22px] font-semibold leading-none tabular-nums", color)}>{value}</p>
      {sub && <p className="mt-1.5 text-xs text-slate-500">{sub}</p>}
    </Tag>
  );
}

export function Progress({ value, total, className, showLabel = true }: { value: number; total: number; className?: string; showLabel?: boolean }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  const done = total > 0 && value >= total;
  return (
    <div className={cx("flex items-center gap-2", className)}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={value} aria-label={`${value} of ${total} met`}>
        <div className={cx("h-full rounded-full", done ? "bg-emerald-600" : "bg-brand-600")} style={{ width: `${pct}%` }} />
      </div>
      {showLabel && <span className="text-xs tabular-nums text-slate-600">{total ? `${value}/${total}` : "—"}</span>}
    </div>
  );
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  const initials = name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .map((p) => p[0]!.toUpperCase())
    .join("")
    .slice(0, 2);
  return <span className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full bg-slate-200 text-2xs font-semibold text-slate-700", className)}>{initials}</span>;
}

/** Table cell classes, so every data table shares one rhythm. */
export const th = "px-4 py-2 text-left text-2xs font-semibold uppercase tracking-[0.06em] text-slate-500";
export const td = "px-4 py-2.5 align-middle";

export function RefId({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono text-xs font-medium text-slate-500", className)}>{children}</span>;
}

// --------------------------------------------------------------------------- status

const TONES = {
  slate: "bg-slate-100 text-slate-700 ring-slate-300/70",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-600/25",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/30",
  red: "bg-red-50 text-red-800 ring-red-600/25",
  blue: "bg-brand-50 text-brand-800 ring-brand-600/25",
  violet: "bg-violet-50 text-violet-800 ring-violet-600/25",
} as const;
const DOTS = { slate: "bg-slate-400", green: "bg-emerald-600", amber: "bg-amber-500", red: "bg-red-600", blue: "bg-brand-600", violet: "bg-violet-600" } as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "slate", children, title, className, dot }: { tone?: Tone; children: ReactNode; title?: string; className?: string; dot?: boolean }) {
  return (
    <span title={title} className={cx("inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded px-1.5 text-2xs font-medium ring-1 ring-inset", TONES[tone], className)}>
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full", DOTS[tone])} aria-hidden />}
      {children}
    </span>
  );
}

/** Who holds the ball: provider (slate), you (blue), problems (amber/red), done (green). */
export const STATE_TONE: Record<string, Tone> = {
  scoping: "violet",
  waiting_requester: "blue",
  ready_to_send: "blue",
  waiting_provider: "slate",
  checking: "violet",
  needs_more: "amber",
  handed_back: "red",
  complete: "green",
  closed_by_provider: "amber",
  accepted: "green",
  cancelled: "slate",
};

/** Status names as the requester reads them. The server's labels are written for sentences
    ("replied after this request was cancelled") and stay as they are. */
export const STATE_LABEL: Record<string, string> = {
  scoping: "Drafting checklist",
  waiting_requester: "Needs your input",
  ready_to_send: "Ready to send",
  waiting_provider: "Awaiting provider",
  checking: "Reviewing evidence",
  needs_more: "Incomplete",
  handed_back: "Needs your decision",
  complete: "Complete",
  closed_by_provider: "Closed by provider",
  accepted: "Accepted",
  cancelled: "Cancelled",
};

export function StateBadge({ state, label }: { state: string; label?: string }) {
  return (
    <Badge tone={STATE_TONE[state] ?? "slate"} dot>
      {STATE_LABEL[state] ?? label ?? state.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
    </Badge>
  );
}

export const VERDICT: Record<string, { tone: Tone; label: string; icon: string }> = {
  met: { tone: "green", label: "Met", icon: "✓" },
  partly_met: { tone: "amber", label: "Partly met", icon: "◐" },
  not_met: { tone: "red", label: "Not met", icon: "✕" },
  unreadable: { tone: "violet", label: "Unreadable", icon: "?" },
  pending: { tone: "slate", label: "Awaiting evidence", icon: "…" },
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

// --------------------------------------------------------------------------- feedback & forms

export function Empty({ children, icon = "file" }: { children: ReactNode; icon?: IconName }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-[13px] text-slate-500">
      <Icon name={icon} size={20} className="text-slate-400" />
      {children}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-2 flex items-start gap-1.5 text-[13px] text-red-700">
      <Icon name="alert" className="mt-0.5" />
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputBase =
  "h-8 rounded-md border border-field bg-white px-2.5 text-[13px] text-slate-900 shadow-xs outline-none placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100";
export const inputCls =
  "w-full rounded-md border border-field bg-white px-2.5 py-1.5 text-[13px] text-slate-900 shadow-xs outline-none placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100";

/** Segmented control for mutually exclusive filters. */
export function Segmented<T extends string>({ options, value, onChange, label }: { options: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; label?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex h-8 max-w-full overflow-x-auto rounded-md border border-slate-300 bg-white p-0.5 shadow-xs">
      {options.map((o) => (
        <button
          key={o.id}
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={cx("shrink-0 whitespace-nowrap rounded-[4px] px-2.5 text-[13px] font-medium", value === o.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="flex gap-4 overflow-x-auto border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx("-mb-px shrink-0 whitespace-nowrap border-b-2 py-2 text-[13px] font-medium", value === t.id ? "border-brand-600 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800")}
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
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-1 text-left text-xs font-medium text-slate-600 hover:text-slate-900">
        <Icon name="chevronRight" size={14} className={cx("transition-transform", open && "rotate-90")} />
        {summary}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/50 p-4 sm:p-10" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" className={cx("w-full rounded-lg bg-white shadow-pop", wide ? "max-w-4xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800" aria-label="Close">
            <Icon name="x" />
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
    <ul className="space-y-1.5">
      {flags.map((f) => (
        <li key={f.code} className={cx("flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]", f.blocking ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900")}>
          <Icon name="alert" className="mt-0.5" />
          <span>
            <span className="font-semibold">{flagLabel(f.code)}.</span> {f.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function flagLabel(code: string) {
  const s = code.replace(/_/g, " ");
  return s[0]!.toUpperCase() + s.slice(1);
}
