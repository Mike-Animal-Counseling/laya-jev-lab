import type { Metadata } from "next";
import "./globals.css";
import "./inbox.css";
import "./workspace.css";
import AuthGate from "./components/AuthGate";
export const metadata: Metadata = {
  title: "Model Lab · Inbox",
  description: "A focused inbox for smarter ticket triage.",
  robots: { index: false, follow: false },
  icons: { icon: "/favicon.svg" },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body><AuthGate>{children}</AuthGate></body>
    </html>
  );
}
