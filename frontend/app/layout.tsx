import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ad Localizer",
  description: "Localize Instagram ad videos into Indian regional languages.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-border bg-bg/80 backdrop-blur sticky top-0 z-10">
          <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-accent text-lg font-bold">▶</span>
              <span className="font-semibold tracking-tight">Ad Localizer</span>
            </div>
            <span className="chip">Instagram ad → regional Indian languages</span>
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
