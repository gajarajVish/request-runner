import { Component, type ErrorInfo, type ReactNode } from "react";

/** A render error anywhere would otherwise blank the whole page. Show a way back, and report it. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    report(error, info.componentStack ?? "");
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid min-h-full place-items-center bg-canvas px-4">
        <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 text-center shadow-xs">
          <h1 className="text-[16px] font-semibold text-slate-900">Something went wrong</h1>
          <p className="mt-1.5 text-[13px] text-slate-600">The page hit an error. Your work is saved; reloading usually fixes it.</p>
          <button onClick={() => location.reload()} className="mt-4 h-9 w-full rounded-md bg-brand-600 text-[13px] font-medium text-white hover:bg-brand-700">
            Reload
          </button>
        </div>
      </div>
    );
  }
}

export function report(error: unknown, componentStack = "") {
  const e = error instanceof Error ? error : new Error(String(error));
  try {
    void fetch("/api/client-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: e.message, stack: e.stack ?? "", component_stack: componentStack, url: location.href }),
      keepalive: true,
    });
  } catch {
    /* reporting must never throw */
  }
}
