export type JobStatus =
  | "created"
  | "extracting_audio"
  | "transcribing"
  | "translating_script"
  | "generating_voiceover"
  | "extracting_frame"
  | "detecting_text"
  | "translating_overlay"
  | "awaiting_review"
  | "rendering_final"
  | "completed"
  | "failed";

export type BoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
  font_size_hint: number;
};

export type OverlayRegion = {
  detected: string;
  translated: string | null;
  bbox: BoundingBox;
  confidence?: number | null;
};

export type Job = {
  id: number;
  status: JobStatus;
  target_language: string;
  original_duration_s: number | null;
  original_transcript: string | null;
  translated_script: string | null;
  translated_script_natural: string | null;
  translated_script_compact: string | null;
  detected_overlay_text: string | null;
  translated_overlay_text: string | null;
  bbox: BoundingBox | null;
  regions: OverlayRegion[];
  has_preview_frame: boolean;
  has_voiceover: boolean;
  has_final_video: boolean;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  urls: {
    input_video: string | null;
    voiceover: string | null;
    preview_frame: string | null;
    background_frame: string | null;
    final_video: string | null;
  };
};

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  return r.json();
}

// The Next.js dev rewrite proxy buffers request bodies in memory and caps them at 10 MB,
// which would truncate any video larger than that. For the one large-payload endpoint
// (upload) we bypass the proxy and POST straight to the backend — CORS is already
// configured for http://localhost:3001 in backend/.env. Other endpoints (small JSON
// payloads, file responses) keep going through the proxy so prod deploys behind a single
// origin still work unchanged.
const UPLOAD_DIRECT_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "");

export const api = {
  upload: async (file: File, language: string): Promise<Job> => {
    const fd = new FormData();
    fd.append("video", file);
    fd.append("target_language", language);
    return asJson<Job>(
      await fetch(`${UPLOAD_DIRECT_BASE}/api/upload`, { method: "POST", body: fd }),
    );
  },

  job: async (id: number): Promise<Job> =>
    asJson<Job>(await fetch(`/api/job/${id}`)),

  updateOverlay: async (id: number, text: string, regionIndex?: number) =>
    asJson<{ ok: boolean }>(
      await fetch(`/api/translate-overlay/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, region_index: regionIndex ?? null }),
      }),
    ),

  regenerateOverlay: async (id: number, regionIndex?: number) => {
    const qs = regionIndex !== undefined ? `?region_index=${regionIndex}` : "";
    return asJson<{ ok: boolean }>(
      await fetch(`/api/translate-overlay/${id}${qs}`, { method: "POST" }),
    );
  },

  updateScript: async (id: number, text: string) =>
    asJson<{ ok: boolean; translated_script: string }>(
      await fetch(`/api/translate-script/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    ),

  regenerateScript: async (id: number) =>
    asJson<{ ok: boolean; translated_script: string; natural: string; compact: string }>(
      await fetch(`/api/translate-script/${id}`, { method: "POST" }),
    ),

  regenerateVoiceover: async (id: number, text?: string) =>
    asJson<{ ok: boolean }>(
      await fetch(`/api/generate-voiceover/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text ?? null }),
      }),
    ),

  renderPreview: async (id: number, text: string, regionIndex?: number): Promise<string> => {
    const r = await fetch(`/api/render-preview/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, region_index: regionIndex ?? null }),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const blob = await r.blob();
    return URL.createObjectURL(blob);
  },

  renderFinal: async (id: number) =>
    asJson<{ ok: boolean }>(
      await fetch(`/api/render-final/${id}`, { method: "POST" }),
    ),
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  created: "Created",
  extracting_audio: "Extracting audio",
  transcribing: "Transcribing voiceover",
  translating_script: "Translating script",
  generating_voiceover: "Generating localized voiceover",
  extracting_frame: "Extracting frame",
  detecting_text: "Detecting overlay text",
  translating_overlay: "Translating overlay",
  awaiting_review: "Ready for review",
  rendering_final: "Rendering final video",
  completed: "Completed",
  failed: "Failed",
};

export const PROGRESS_ORDER: JobStatus[] = [
  "created",
  "extracting_audio",
  "transcribing",
  "translating_script",
  "generating_voiceover",
  "extracting_frame",
  "detecting_text",
  "translating_overlay",
  "awaiting_review",
  "rendering_final",
  "completed",
];

export function progressPct(status: JobStatus): number {
  const i = PROGRESS_ORDER.indexOf(status);
  if (i < 0) return 0;
  return Math.round((i / (PROGRESS_ORDER.length - 1)) * 100);
}
