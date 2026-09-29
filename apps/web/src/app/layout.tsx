import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Causal — Examine what shaped a thought or feeling",
  description:
    "A guided reflection workspace for examining possible causes, context, and boundaries.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
