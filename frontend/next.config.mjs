/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Backend routing (/api -> API, /stream -> Stream Gateway) lives in
  // middleware.ts so it works the same in dev and production, behind a
  // tunnel or on a plain LAN port.
};

export default nextConfig;
