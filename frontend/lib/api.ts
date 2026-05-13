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

export const api = {
  upload: async (file: File, language: string): Promise<Job> => {
    const fd = new FormData();
    fd.append("video", file);
    fd.append("target_language", language);
    return asJson<Job>(await fetch("/api/upload", { method: "POST", body: fd }));
  },

  job: async (id: number): Promise<Job> =>
    asJson<Job>(await fetch(`/api/job/${id}`)),

  updateOverlay: async (id: number, text: string) =>
    asJson<{ ok: boolean }>(
      await fetch(`/api/translate-overlay/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    ),

  regenerateOverlay: async (id: number) =>
    asJson<{ ok: boolean }>(
      await fetch(`/api/translate-overlay/${id}`, { method: "POST" }),
    ),

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

  renderPreview: async (id: number, text: string): Promise<string> => {
    const r = await fetch(`/api/render-preview/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
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
