import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 生产 Docker 镜像使用 standalone 模式，大幅减小镜像体积
  output: "standalone",

  async rewrites() {
    // 容器内由 API_BASE_URL 指定后端地址；本地开发回落到 localhost:8080
    const api = process.env.API_BASE_URL ?? "http://localhost:8080";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/proxy",      destination: `${api}/proxy` },
      { source: "/health",     destination: `${api}/health` },
    ];
  },
};

export default nextConfig;
