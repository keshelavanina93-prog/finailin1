import type { NextConfig } from "next";
import path from "node:path";

// Isolate verification builds from a running packaged application in this checkout.
const buildDirectory = process.env.G8_BUILD_DIRECTORY ?? ".next";
if (!/^\.next(?:-[a-z0-9-]+)?$/.test(buildDirectory)) {
  throw new Error("G8 build directory must be a local .next directory");
}
// Resolve from this materialized source, even when nested in another checkout.
const sourceRoot = path.resolve(__dirname, "../..");
const nextConfig: NextConfig = {
  outputFileTracingRoot: sourceRoot,
  turbopack: { root: sourceRoot },
  distDir: buildDirectory,
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@finai/contracts"],
};

export default nextConfig;
