import type { NextConfig } from "next";

const apiOrigin = process.env.CAUSAL_API_ORIGIN?.replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    if (!apiOrigin) return [];
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/api/:path*",
        headers: [
          { key: "Cache-Control", value: "private, no-store" },
          { key: "x-vercel-enable-rewrite-caching", value: "0" },
        ],
      },
    ];
  },
};

export default nextConfig;
