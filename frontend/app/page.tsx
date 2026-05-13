"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { UploadDropzone } from "@/components/UploadDropzone";
import { LanguagePicker } from "@/components/LanguagePicker";
import { api } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("hi");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const job = await api.upload(file, language);
      router.push(`/job/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">Localize an Instagram ad</h1>
        <p className="text-muted max-w-2xl">
          Upload an English ad, pick a target Indian language, and get back an MP4 with a
          natural localized voiceover and translated overlay text. Visuals, timing, and pacing
          stay identical to the original.
        </p>
      </section>

      <section className="space-y-3">
        <div className="chip">Step 1</div>
        <UploadDropzone onFile={setFile} disabled={uploading} />
        {file && (
          <div className="text-sm text-muted">
            Selected: <span className="text-gray-200">{file.name}</span>{" "}
            ({(file.size / 1024 / 1024).toFixed(1)} MB)
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="chip">Step 2 · Target language</div>
        <LanguagePicker value={language} onChange={setLanguage} />
      </section>

      <section className="flex items-center gap-3">
        <button
          className="btn btn-primary"
          disabled={!file || uploading}
          onClick={submit}
        >
          {uploading ? "Uploading…" : "Localize this ad →"}
        </button>
        {error && (
          <div className="text-xs text-rose-300 bg-rose-950/40 border border-rose-900 rounded px-3 py-1.5">
            {error}
          </div>
        )}
      </section>
    </div>
  );
}
