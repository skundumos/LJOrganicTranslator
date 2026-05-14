"use client";

type Props = {
  src: string | null;
  label?: string;
};

export function VideoPreview({ src, label }: Props) {
  if (!src) return null;
  return (
    <div className="card p-4">
      {label && <div className="chip mb-2">{label}</div>}
      <div className="rounded-lg overflow-hidden border border-border bg-black mx-auto" style={{ maxWidth: "min(100%, 480px)" }}>
        {/* eslint-disable-next-line @next/next/no-unknown-property */}
        <video
          src={src}
          controls
          controlsList="nodownload"
          className="w-full h-auto block"
          playsInline
          preload="metadata"
        />
      </div>
    </div>
  );
}
