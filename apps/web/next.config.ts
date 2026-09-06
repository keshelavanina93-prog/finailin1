import type { NextConfig } from "next";

// Isolate verification builds from a running packaged application in this checkout.
const buildDirectory = process.env.G8_BUILD_DIRECTORY ?? ".next";
if (!/^\.next(?:-[a-z0-9-]+)?$/.test(buildDirectory)) {
  throw new Error("G8 build directory must be a local .next directory");
}
const nextConfig: NextConfig = {
  distDir: buildDirectory,
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@finai/contracts"],
};

export default nextConfig;
