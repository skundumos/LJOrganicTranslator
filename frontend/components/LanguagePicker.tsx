"use client";

import { LANGUAGES } from "@/lib/languages";

type Props = {
  value: string;
  onChange: (code: string) => void;
};

export function LanguagePicker({ value, onChange }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
      {LANGUAGES.map((l) => {
        const selected = l.code === value;
        return (
          <button
            key={l.code}
            type="button"
            onClick={() => onChange(l.code)}
            className={`card px-3 py-3 text-left transition-colors ${
              selected ? "border-accent ring-1 ring-accent" : "hover:border-muted"
            }`}
          >
            <div className="text-sm font-medium text-gray-100">{l.display_name}</div>
            <div className="text-xs text-muted mt-1">{l.native_name}</div>
          </button>
        );
      })}
    </div>
  );
}
