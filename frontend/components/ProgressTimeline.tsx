"use client";

import { JobStatus, PROGRESS_ORDER, STATUS_LABEL, progressPct } from "@/lib/api";

type Props = {
  status: JobStatus;
  error?: string | null;
};

export function ProgressTimeline({ status, error }: Props) {
  const pct = progressPct(status);
  const failed = status === "failed";

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="chip">Status</div>
          <div className="text-lg font-medium">
            {failed ? "Failed" : STATUS_LABEL[status]}
          </div>
        </div>
        <div className="text-sm text-muted">{failed ? "—" : `${pct}%`}</div>
      </div>
      <div className="h-2 bg-bg rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${
            failed ? "bg-rose-600" : "bg-gradient-to-r from-accent to-accent2"
          }`}
          style={{ width: failed ? "100%" : `${pct}%` }}
        />
      </div>
      {failed && error && (
        <div className="mt-3 text-xs text-rose-300 bg-rose-950/40 border border-rose-900 rounded p-2">
          {error}
        </div>
      )}
      <ol className="mt-4 grid grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1.5 text-xs text-muted">
        {PROGRESS_ORDER.filter((s) => s !== "created" && s !== "completed").map((s) => {
          const idx = PROGRESS_ORDER.indexOf(s);
          const cur = PROGRESS_ORDER.indexOf(status);
          const done = idx < cur;
          const here = idx === cur;
          return (
            <li
              key={s}
              className={here ? "text-gray-100 font-medium" : done ? "text-emerald-400" : ""}
            >
              {done ? "✓ " : here ? "● " : "○ "}
              {STATUS_LABEL[s]}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
