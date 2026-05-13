"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job } from "@/lib/api";

type Props = {
  job: Job;
  onSaved?: () => void;
};

export function OverlayEditor({ job, onSaved }: Props) {
  const [text, setText] = useState(job.translated_overlay_text ?? "");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const lastUrlRef = useRef<string | null>(null);

  useEffect(() => {
    setText(job.translated_overlay_text ?? "");
  }, [job.translated_overlay_text]);

  useEffect(() => {
    if (!text.trim() || !job.bbox) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      try {
        setLoading(true);
        const url = await api.renderPreview(job.id, text);
        if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
        lastUrlRef.current = url;
        setPreviewUrl(url);
      } catch (err) {
        console.warn("preview failed", err);
      } finally {
        setLoading(false);
      }
    }, 400);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [text, job.id, job.bbox]);

  useEffect(() => {
    return () => {
      if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
    };
  }, []);

  const save = async () => {
    await api.updateOverlay(job.id, text);
    onSaved?.();
  };

  const regenerate = async () => {
    setRegenerating(true);
    try {
      await api.regenerateOverlay(job.id);
      onSaved?.();
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="chip">Step 2 · Overlay text</div>
          <h3 className="text-lg font-medium">Translated overlay</h3>
        </div>
        <button
          className="btn btn-secondary"
          onClick={regenerate}
          disabled={regenerating || !job.detected_overlay_text}
        >
          {regenerating ? "Regenerating…" : "↻ Regenerate"}
        </button>
      </div>

      <div className="text-xs text-muted mb-1">
        Detected English: <span className="text-gray-200">{job.detected_overlay_text || "—"}</span>
      </div>

      <textarea
        className="textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="Translated overlay text…"
      />

      <div className="flex items-center justify-between mt-3">
        <div className="text-xs text-muted">
          {loading ? "Updating preview…" : "Live preview updates as you type."}
        </div>
        <button className="btn btn-primary" onClick={save}>
          Save overlay
        </button>
      </div>

      {previewUrl && (
        <div className="mt-4">
          <div className="chip mb-2">Preview frame</div>
          <div className="rounded-lg overflow-hidden border border-border bg-black">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewUrl}
              alt="Overlay preview"
              className="w-full h-auto block"
            />
          </div>
        </div>
      )}
    </div>
  );
}
