import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/chat",
        destination: "http://localhost:8000/api/chat",
      },
      {
        source: "/api/health",
        destination: "http://localhost:8000/api/health",
      },
    ];
  },
};

export default nextConfig;
