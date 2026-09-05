/** @type {import('next').NextConfig} */
const nextConfig = {
  // This machine has a node_modules and a package.json at $HOME. Without an explicit
  // root, Next walks up, finds them, and resolves react from there — which produces a
  // null-context crash during prerender that looks like an application bug.
  outputFileTracingRoot: import.meta.dirname,
  turbopack: {
    root: import.meta.dirname,
  },
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8010",
  },
};

export default nextConfig;
