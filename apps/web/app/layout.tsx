import type { Metadata } from "next";
import type { ReactNode } from "react";
import G8Workspace from "./g8-workspace";
import "./styles.css";
import "./trial-balance-review.css";

export const metadata: Metadata = {
  title: "G8 by NYXCore",
  description: "Enterprise intelligence. Evidence, context and governed decisions.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body><G8Workspace />{children}</body>
    </html>
  );
}
