"use client";

import { useEffect, useState } from "react";
import { api, Job } from "@/lib/api";

type Props = {
  job: Job;
  onSaved?: () => void;
};

export function ScriptEditor({ job, onSaved }: Props) {
  const [text, setText] = useState(job.translated_script ?? "");
  const [regenerating, setRegenerating] = useState(false);
  const [regeneratingVoice, setRegeneratingVoice] = useState(false);

  useEffect(() => setText(job.translated_script ?? ""), [job.translated_script]);

  const save = async () => {
    await api.updateScript(job.id, text);
    onSaved?.();
  };

  const regenerateScript = async () => {
    setRegenerating(true);
    try {
      const r = await api.regenerateScript(job.id);
      setText(r.translated_script);
      onSaved?.();
    } finally {
      setRegenerating(false);
    }
  };

  const regenerateVoice = async () => {
    setRegeneratingVoice(true);
    try {
      // Persist the latest script first so the regen uses it.
      await api.updateScript(job.id, text);
      await api.regenerateVoiceover(job.id, text);
      onSaved?.();
    } finally {
      setRegeneratingVoice(false);
    }
  };

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="chip">Step 1 · Voiceover script</div>
          <h3 className="text-lg font-medium">Translated script</h3>
        </div>
        <div className="flex gap-2">
          <button
            className="btn btn-secondary"
            onClick={regenerateScript}
            disabled={regenerating}
          >
            {regenerating ? "Regenerating…" : "↻ Re-translate"}
          </button>
        </div>
      </div>

      {job.original_transcript && (
        <details className="mb-3">
          <summary className="text-xs text-muted cursor-pointer">
            Original English transcript
          </summary>
          <div className="text-xs text-gray-300 mt-1 whitespace-pre-wrap">
            {job.original_transcript}
          </div>
        </details>
      )}

      <textarea
        className="textarea min-h-[150px]"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Translated voiceover script…"
      />

      <div className="flex items-center justify-between mt-3">
        <div className="text-xs text-muted">
          {job.has_voiceover ? "Voiceover ready ✓" : "Voiceover pending…"}
          {job.original_duration_s && (
            <span className="ml-2">Target: {job.original_duration_s.toFixed(1)}s</span>
          )}
        </div>
        <div className="flex gap-2">
          <button className="btn btn-secondary" onClick={save}>
            Save script
          </button>
          <button
            className="btn btn-primary"
            onClick={regenerateVoice}
            disabled={regeneratingVoice || !text.trim()}
          >
            {regeneratingVoice ? "Generating…" : "🔊 Regenerate voiceover"}
          </button>
        </div>
      </div>

      {job.urls.voiceover && (
        <audio controls src={job.urls.voiceover} className="mt-4 w-full" />
      )}
    </div>
  );
}
