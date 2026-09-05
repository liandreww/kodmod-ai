import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The backend URL is read at request time on the server and injected into the
  // client bundle only as NEXT_PUBLIC_API_URL, so a deploy can point at a
  // different API without a rebuild of the server code.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default config;
