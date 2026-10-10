import { redirect } from "next/navigation";

// Keep previously shared links useful without a separate comparison interface.
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ ticket?: string | string[] }>;
}) {
  const { ticket } = await searchParams;
  redirect(
    typeof ticket === "string"
      ? `/laya-ft?ticket=${encodeURIComponent(ticket)}`
      : "/laya-ft",
  );
}
