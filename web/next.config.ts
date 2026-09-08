import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The verdict card is rendered on the server; nothing below needs to grow a
  // client bundle. Keep an eye on `next build`'s First Load JS column.
  poweredByHeader: false,
  // Screenshot uploads go through a server action. The browser re-encodes big
  // images below 1 MB when JavaScript is on; this keeps the no-JS path working
  // up to the 5 MB cap the API enforces.
  experimental: {
    serverActions: { bodySizeLimit: "6mb" },
  },
};

export default nextConfig;
