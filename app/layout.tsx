import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Model Lab · 工单对照",
  description: "同一张工单，对照 Laya 与 Jev 的分类结果。",
  robots: { index: false, follow: false },
  icons: { icon: "/favicon.svg" },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
