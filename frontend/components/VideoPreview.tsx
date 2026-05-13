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
      <div className="rounded-lg overflow-hidden border border-border bg-black aspect-[9/16] max-w-[360px] mx-auto">
        {/* eslint-disable-next-line @next/next/no-unknown-property */}
        <video src={src} controls className="w-full h-full" playsInline preload="metadata" />
      </div>
    </div>
  );
}
