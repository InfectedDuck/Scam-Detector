import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The verdict card is rendered on the server; nothing below needs to grow a
  // client bundle. Keep an eye on `next build`'s First Load JS column.
  poweredByHeader: false,
};

export default nextConfig;
