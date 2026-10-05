import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtTime, useLiveUpdates, type Me } from "../api";
import { Avatar, Button, Card, ErrorText, Field, Icon, type IconName, Spinner, cx, inputCls } from "./ui";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me"), staleTime: 30_000 });
}

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Requests", icon: "requests", end: true },
  { to: "/dashboard", label: "Who's behind", icon: "dashboard" },
  { to: "/imports", label: "Request lists", icon: "imports" },
];
const NAV_MORE: { to: string; label: string; icon: IconName }[] = [
  { to: "/inbox", label: "Unmatched email", icon: "inbox" },
  { to: "/activity", label: "Audit log", icon: "activity" },
];

function Logo({ name, dark }: { name: string; dark?: boolean }) {
  return (
    <NavLink to="/" className={cx("flex items-center gap-2.5 text-[14px] font-semibold tracking-tight", dark ? "text-slate-900" : "text-white")}>
      <span className={cx("grid h-7 w-7 place-items-center rounded-md text-[15px] font-bold leading-none text-white", dark ? "bg-brand-700" : "bg-brand-600 ring-1 ring-white/15")} aria-hidden>
        R
      </span>
      {name}
    </NavLink>
  );
}

export function Shell() {
  const me = useMe();
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => {
    setMenu(false);
  }, [loc.pathname]);
  useLiveUpdates(!!me.data?.user);
  if (me.isLoading) {
    return (
      <div className="grid h-full place-items-center text-slate-500">
        <Spinner />
      </div>
    );
  }
  if (!me.data?.user) return <Login me={me.data} />;
  const link = (n: { to: string; label: string; icon: IconName; end?: boolean }, small?: boolean) => (
    <NavLink
      key={n.to}
      to={n.to}
      end={n.end}
      className={({ isActive }) =>
        cx(
          "flex items-center gap-2.5 rounded-md px-2.5 font-medium transition-colors",
          small ? "h-7 text-xs" : "h-8 text-[13px]",
          isActive ? "bg-white/10 text-white" : small ? "text-ink-500 hover:bg-white/5 hover:text-white" : "text-ink-300 hover:bg-white/5 hover:text-white",
        )
      }
    >
      <Icon name={n.icon} size={small ? 14 : 16} />
      {n.label}
    </NavLink>
  );
  const nav = (
    <nav aria-label="Main">
      <div className="space-y-0.5">{NAV.map((n) => link(n))}</div>
      <div className="mt-5 space-y-0.5">{NAV_MORE.map((n) => link(n, true))}</div>
    </nav>
  );
  return (
    <div className="min-h-full lg:pl-56">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col bg-ink-900 px-3 py-4 lg:flex">
        <div className="px-1.5">
          <Logo name={me.data.app_name} />
        </div>
        <div className="mt-6">{nav}</div>
        <div className="mt-auto space-y-2 border-t border-white/10 pt-3">
          {me.data.dev && <DemoClock me={me.data} />}
          <UserMenu me={me.data} />
        </div>
      </aside>
      <header className="sticky top-0 z-30 flex h-12 items-center gap-3 bg-ink-900 px-4 lg:hidden">
        <button onClick={() => setMenu(!menu)} className="-ml-1 rounded p-1.5 text-ink-300 hover:bg-white/10 hover:text-white" aria-label="Menu" aria-expanded={menu}>
          <Icon name={menu ? "x" : "menu"} size={18} />
        </button>
        <Logo name={me.data.app_name} />
      </header>
      {menu && (
        <div className="fixed inset-x-0 top-12 z-30 space-y-3 border-t border-white/10 bg-ink-900 px-3 pb-4 pt-2 shadow-pop lg:hidden">
          {nav}
          <div className="space-y-2 border-t border-white/10 pt-3">
            {me.data.dev && <DemoClock me={me.data} />}
            <UserMenu me={me.data} />
          </div>
        </div>
      )}
      <main className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}

function Login({ me }: { me?: Me }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: () => api.post("/api/login", { email, password }), onSuccess: () => qc.invalidateQueries() });
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => api.get<{ id: number; name: string; email: string }[]>("/api/dev/users"), enabled: !!me?.dev });
  const sw = useMutation({ mutationFn: (id: number) => api.post(`/api/dev/switch-user/${id}`), onSuccess: () => qc.invalidateQueries() });
  const name = me?.app_name ?? "RequestRunner";
  return (
    <div className="grid min-h-full place-items-center bg-canvas px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        <Logo name={name} dark />
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
          <h1 className="mb-5 text-[18px] font-semibold tracking-tight text-slate-900">Sign in</h1>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              login.mutate();
            }}
          >
            <Field label="Email">
              <input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
            </Field>
            <Field label="Password">
              <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </Field>
            <Button variant="primary" className="h-9 w-full" busy={login.isPending}>
              Sign in
            </Button>
            <ErrorText error={login.error} />
          </form>
        </div>
        {me?.dev && users.data && (
          <Card title={<span className="text-amber-800">Development only: sign in as</span>} className="border-amber-300 bg-amber-50/40">
            <div className="flex flex-col gap-1.5">
              {users.data.map((u) => (
                <button key={u.id} onClick={() => sw.mutate(u.id)} className="flex items-center gap-2.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-left hover:border-slate-300">
                  <Avatar name={u.name} />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-slate-900">{u.name}</span>
                    <span className="block truncate text-xs text-slate-500">{u.email}</span>
                  </span>
                </button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return { open, setOpen, ref };
}

function UserMenu({ me }: { me: Me }) {
  const qc = useQueryClient();
  const { open, setOpen, ref } = usePopover();
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => api.get<{ id: number; name: string; email: string }[]>("/api/dev/users"), enabled: me.dev && open });
  const logout = useMutation({ mutationFn: () => api.post("/api/logout"), onSuccess: () => qc.clear() });
  const sw = useMutation({
    mutationFn: (id: number) => api.post(`/api/dev/switch-user/${id}`),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries();
    },
  });
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left hover:bg-white/5">
        <Avatar name={me.user!.name} className="bg-ink-700 text-ink-200" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-white">{me.user!.name}</span>
          <span className="block truncate text-2xs text-ink-300">{me.user!.email}</span>
        </span>
        <Icon name="chevronDown" size={14} className="text-ink-300" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-1 w-full min-w-56 rounded-md border border-slate-200 bg-white p-1 shadow-pop">
          {me.dev && users.data && users.data.length > 1 && (
            <>
              <div className="px-2.5 pb-1 pt-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">Switch user (dev)</div>
              {users.data
                .filter((u) => u.id !== me.user!.id)
                .map((u) => (
                  <button key={u.id} onClick={() => sw.mutate(u.id)} className="block w-full rounded px-2.5 py-1.5 text-left text-[13px] text-slate-700 hover:bg-slate-100">
                    {u.name}
                  </button>
                ))}
              <div className="my-1 border-t border-slate-100" />
            </>
          )}
          <button onClick={() => logout.mutate()} className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-[13px] text-slate-700 hover:bg-slate-100">
            <Icon name="logout" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function DemoClock({ me }: { me: Me }) {
  const qc = useQueryClient();
  const { open, setOpen, ref } = usePopover();
  const advance = useMutation({
    mutationFn: (seconds: number) => api.post<{ now: string }>("/api/dev/clock/advance", { seconds, key: crypto.randomUUID() }),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries();
    },
  });
  const steps = [
    { label: "+10 min", s: 600 },
    { label: "+1 hour", s: 3600 },
    { label: "+1 day", s: 86400 },
    { label: "+3 days", s: 3 * 86400 },
    { label: "+1 week", s: 7 * 86400 },
  ];
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-md border border-dashed border-amber-400/50 bg-amber-400/10 px-2.5 py-1.5 text-left text-xs text-amber-200 hover:bg-amber-400/15"
        title="Demo clock (development only)"
      >
        <Icon name="clock" size={14} />
        <span className="min-w-0 flex-1">
          <span className="block text-2xs uppercase tracking-[0.08em] text-amber-300/80">Demo clock</span>
          <span className="block font-medium tabular-nums">{fmtTime(me.now)}</span>
        </span>
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-1 w-72 rounded-md border border-slate-200 bg-white p-3 shadow-pop">
          <p className="mb-2 text-xs text-slate-600">Moving the clock forward runs reminders, overdue notices and escalations as if that time had passed.</p>
          <div className="flex flex-wrap gap-1.5">
            {steps.map((st) => (
              <Button key={st.s} size="sm" onClick={() => advance.mutate(st.s)} busy={advance.isPending && advance.variables === st.s}>
                {st.label}
              </Button>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => api.post("/api/dev/sweep")}>
            Run sweep now
          </Button>
          <ErrorText error={advance.error} />
        </div>
      )}
    </div>
  );
}
