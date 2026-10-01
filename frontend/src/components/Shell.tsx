import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtTime, useLiveUpdates, type Me } from "../api";
import { Button, Card, ErrorText, Field, Spinner, cx, inputCls } from "./ui";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me"), staleTime: 30_000 });
}

export function Shell() {
  const me = useMe();
  useLiveUpdates(!!me.data?.user);
  if (me.isLoading) {
    return (
      <div className="grid h-full place-items-center text-slate-400">
        <Spinner />
      </div>
    );
  }
  if (!me.data?.user) return <Login me={me.data} />;
  const nav = [
    { to: "/", label: "Requests", end: true },
    { to: "/imports", label: "Imports" },
    { to: "/dashboard", label: "Dashboard" },
    { to: "/inbox", label: "Inbox" },
    { to: "/activity", label: "Activity" },
  ];
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <NavLink to="/" className="flex items-center gap-2 font-semibold text-slate-900">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-600 text-sm text-white">R</span>
            {me.data.app_name}
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            {nav.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => cx("rounded-md px-2.5 py-1.5 text-sm font-medium", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {me.data.dev && <DemoClock me={me.data} />}
            <UserMenu me={me.data} />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
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
  return (
    <div className="grid min-h-full place-items-center px-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="text-center">
          <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-lg bg-brand-600 text-lg font-semibold text-white">R</div>
          <h1 className="text-xl font-semibold">{me?.app_name ?? "RequestRunner"}</h1>
          <p className="text-sm text-slate-500">Collect documents from people by email.</p>
        </div>
        <Card>
          <form
            className="space-y-3"
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
            <Button variant="primary" className="w-full justify-center" busy={login.isPending}>
              Sign in
            </Button>
            <ErrorText error={login.error} />
          </form>
        </Card>
        {me?.dev && users.data && (
          <Card title="Development: sign in as">
            <div className="flex flex-col gap-2">
              {users.data.map((u) => (
                <Button key={u.id} onClick={() => sw.mutate(u.id)} className="justify-between">
                  <span>{u.name}</span>
                  <span className="text-xs text-slate-400">{u.email}</span>
                </Button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function UserMenu({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => api.get<{ id: number; name: string; email: string }[]>("/api/dev/users"), enabled: me.dev && open });
  const logout = useMutation({ mutationFn: () => api.post("/api/logout"), onSuccess: () => qc.clear() });
  const sw = useMutation({ mutationFn: (id: number) => api.post(`/api/dev/switch-user/${id}`), onSuccess: () => { setOpen(false); qc.invalidateQueries(); } });
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-slate-100">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">{me.user!.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}</span>
        <span className="hidden sm:inline">{me.user!.name}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-64 rounded-md border border-slate-200 bg-white p-1 shadow-lg">
          <div className="px-3 py-2 text-xs text-slate-500">{me.user!.email}</div>
          {me.dev && users.data && (
            <>
              <div className="px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Switch user (dev)</div>
              {users.data
                .filter((u) => u.id !== me.user!.id)
                .map((u) => (
                  <button key={u.id} onClick={() => sw.mutate(u.id)} className="block w-full rounded px-3 py-1.5 text-left text-sm hover:bg-slate-100">
                    {u.name}
                  </button>
                ))}
            </>
          )}
          <button onClick={() => logout.mutate()} className="mt-1 block w-full rounded px-3 py-1.5 text-left text-sm text-red-700 hover:bg-red-50">
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function DemoClock({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
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
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 rounded-md border border-dashed border-amber-400 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900" title="Demo clock (development only)">
        ⏱ {fmtTime(me.now)}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-72 rounded-md border border-slate-200 bg-white p-3 shadow-lg">
          <p className="mb-2 text-xs text-slate-500">Demo clock. Moving it forward runs reminders, overdue notices and escalations as if that time had passed.</p>
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
