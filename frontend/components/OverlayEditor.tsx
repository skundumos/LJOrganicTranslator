"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job, OverlayRegion } from "@/lib/api";

type Props = {
  job: Job;
  onSaved?: () => void;
};

function regionLabel(region: OverlayRegion, idx: number, totalHeightHint: number): string {
  // Heuristic: a bbox center in the top half of the frame is "Top", else "Bottom".
  // totalHeightHint is unused now (we don't have video height in the Job payload), so
  // fall back to relative order — region 0 is top, region 1 is bottom.
  void totalHeightHint;
  void region;
  if (idx === 0) return "Top overlay";
  if (idx === 1) return "Bottom overlay";
  return `Overlay #${idx + 1}`;
}

function RegionEditor({
  job,
  region,
  index,
  onSaved,
}: {
  job: Job;
  region: OverlayRegion;
  index: number;
  onSaved?: () => void;
}) {
  const [text, setText] = useState(region.translated ?? "");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const lastUrlRef = useRef<string | null>(null);

  useEffect(() => {
    setText(region.translated ?? "");
  }, [region.translated]);

  useEffect(() => {
    if (!text.trim()) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      try {
        setLoading(true);
        const url = await api.renderPreview(job.id, text, index);
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
  }, [text, job.id, index]);

  useEffect(() => {
    return () => {
      if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
    };
  }, []);

  const save = async () => {
    await api.updateOverlay(job.id, text, index);
    onSaved?.();
  };

  const regenerate = async () => {
    setRegenerating(true);
    try {
      await api.regenerateOverlay(job.id, index);
      onSaved?.();
    } finally {
      setRegenerating(false);
    }
  };

  const conf = typeof region.confidence === "number" ? region.confidence : null;
  const showLowConf = conf !== null && conf < 0.7;

  return (
    <div className="card p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="chip">{regionLabel(region, index, 0)}</div>
            {showLowConf && (
              <div
                className="chip"
                style={{
                  backgroundColor:
                    conf! < 0.5 ? "rgba(239,68,68,0.2)" : "rgba(234,179,8,0.2)",
                  color: conf! < 0.5 ? "#fca5a5" : "#fde68a",
                }}
                title={`OCR confidence ${(conf! * 100).toFixed(0)}% — verify the detected text below before rendering.`}
              >
                Low OCR confidence ({(conf! * 100).toFixed(0)}%)
              </div>
            )}
          </div>
          <h3 className="text-lg font-medium">Translated overlay</h3>
        </div>
        <button
          className="btn btn-secondary"
          onClick={regenerate}
          disabled={regenerating || !region.detected}
        >
          {regenerating ? "Regenerating…" : "↻ Regenerate"}
        </button>
      </div>

      <div className="text-xs text-muted mb-1">
        Detected English: <span className="text-gray-200">{region.detected || "—"}</span>
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

export function OverlayEditor({ job, onSaved }: Props) {
  // Prefer the multi-region list. If it's empty but legacy bbox + translated text exist,
  // synthesize a single region so older jobs still render in the UI.
  const regions: OverlayRegion[] = job.regions && job.regions.length > 0
    ? job.regions
    : (job.bbox
      ? [{
          detected: job.detected_overlay_text ?? "",
          translated: job.translated_overlay_text,
          bbox: job.bbox,
        }]
      : []);

  if (regions.length === 0) {
    return (
      <div className="card p-5">
        <div className="chip">Step 2 · Overlay text</div>
        <div className="text-sm text-muted mt-2">No overlay text detected on this video.</div>
      </div>
    );
  }

  return (
    <div>
      <div className="chip mb-2">Step 2 · Overlay text ({regions.length})</div>
      {regions.map((r, i) => (
        <RegionEditor key={i} job={job} region={r} index={i} onSaved={onSaved} />
      ))}
    </div>
  );
}
