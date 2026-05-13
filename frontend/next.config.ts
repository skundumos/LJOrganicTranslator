import type { NextConfig } from "next";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const config: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/files/:path*", destination: `${API}/files/:path*` },
    ];
  },
};

export default config;
