/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  serverExternalPackages: ["pg", "ioredis"],
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;
