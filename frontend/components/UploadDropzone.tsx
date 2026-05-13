"use client";

import { useCallback, useRef, useState } from "react";

type Props = {
  onFile: (file: File) => void;
  disabled?: boolean;
};

export function UploadDropzone({ onFile, disabled }: Props) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handle = useCallback(
    (f: File | null | undefined) => {
      if (!f) return;
      if (!/\.(mp4|mov|m4v)$/i.test(f.name)) {
        alert("Only MP4 / MOV files are supported.");
        return;
      }
      onFile(f);
    },
    [onFile],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        handle(e.dataTransfer.files?.[0]);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`card cursor-pointer flex flex-col items-center justify-center py-16 px-6 text-center
        transition-colors ${drag ? "border-accent2 bg-accent2/5" : "hover:border-muted"}
        ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/x-m4v"
        hidden
        disabled={disabled}
        onChange={(e) => handle(e.target.files?.[0])}
      />
      <div className="text-3xl mb-3">📥</div>
      <div className="font-medium text-lg mb-1">Drop your Instagram ad here</div>
      <div className="text-sm text-muted">
        9:16 vertical MP4, 15–60 seconds. English voiceover, static centered overlay.
      </div>
    </div>
  );
}
