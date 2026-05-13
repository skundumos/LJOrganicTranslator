"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, Job } from "@/lib/api";
import { ProgressTimeline } from "@/components/ProgressTimeline";
import { OverlayEditor } from "@/components/OverlayEditor";
import { ScriptEditor } from "@/components/ScriptEditor";
import { VideoPreview } from "@/components/VideoPreview";

export default function JobPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  const reload = async () => {
    try {
      const j = await api.job(id);
      setJob(j);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void reload();
    const t = window.setInterval(reload, 1500);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!job) {
    return (
      <div className="text-muted text-sm">
        {error ? `Error: ${error}` : "Loading job…"}
      </div>
    );
  }

  const ready = job.status === "awaiting_review" || job.status === "rendering_final" || job.status === "completed";
  const failed = job.status === "failed";

  const renderFinal = async () => {
    setRendering(true);
    try {
      await api.renderFinal(job.id);
      await reload();
    } finally {
      setRendering(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="chip">Job #{job.id}</div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Ad → {job.target_language.toUpperCase()}
          </h1>
        </div>
        {job.urls.final_video && (
          <a
            href={job.urls.final_video}
            download={`localized_${job.id}.mp4`}
            className="btn btn-primary"
          >
            ⬇ Download localized MP4
          </a>
        )}
      </div>

      <ProgressTimeline status={job.status} error={job.error_message} />

      {ready && (
        <div className="grid lg:grid-cols-2 gap-6">
          <ScriptEditor job={job} onSaved={reload} />
          <OverlayEditor job={job} onSaved={reload} />
        </div>
      )}

      {ready && (
        <div className="card p-5 flex items-center justify-between">
          <div>
            <div className="chip">Final render</div>
            <div className="text-sm text-muted">
              Renders a localized MP4 using the script + overlay above.
              Re-renders cost nothing extra (no re-translation, no new TTS).
            </div>
          </div>
          <button
            className="btn btn-primary"
            onClick={renderFinal}
            disabled={rendering || job.status === "rendering_final"}
          >
            {job.status === "rendering_final" || rendering ? "Rendering…" : "▶ Render final video"}
          </button>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <VideoPreview src={job.urls.input_video} label="Original" />
        <VideoPreview src={job.urls.final_video} label="Localized" />
      </div>

      {failed && (
        <div className="card p-4 border-rose-900 bg-rose-950/30 text-sm text-rose-200">
          <strong>Job failed.</strong> {job.error_message}
        </div>
      )}
    </div>
  );
}
