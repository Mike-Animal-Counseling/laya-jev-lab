export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

let csrfToken = "";

/** Mutations are never retried automatically: a timed out request may have committed. */
export async function request<T>(
  path: string,
  provider: string,
  body?: object,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), body ? 120_000 : 12_000);
  try {
    const upload = body instanceof Blob;
    if (body && !csrfToken) {
      const session = await fetch("/api/session", {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!session.ok)
        throw new ApiError(
          "Refresh to reconnect.",
          session.status,
        );
      const sessionData = (await session.json()) as { csrf_token?: unknown };
      if (typeof sessionData.csrf_token !== "string")
        throw new ApiError("Invalid session. Refresh to reconnect.", 502);
      csrfToken = sessionData.csrf_token;
    }
    const response = await fetch(
      `/api/${path}?provider=${encodeURIComponent(provider)}`,
      {
        signal: controller.signal,
        cache: "no-store",
        ...(body
          ? {
              method: "POST",
              headers: {
                "Content-Type": upload
                  ? "name" in body && typeof body.name === "string" && /\.csv$/i.test(body.name) ? "text/csv"
                    : "name" in body && typeof body.name === "string" && /\.eml$/i.test(body.name) ? "message/rfc822"
                    : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  : "application/json",
                "X-CSRF-Token": csrfToken,
              },
              body: upload ? (body as Blob) : JSON.stringify({ ...body, provider }),
            }
          : {}),
      },
    );
    const data = (await response.json().catch(() => null)) as {
      error?: string;
    } | null;
    if (!response.ok) {
      if (response.status === 403) csrfToken = "";
      throw new ApiError(
        data?.error || `Service unavailable (${response.status})`,
        response.status,
      );
    }
    if (!data) throw new ApiError("Invalid response. Refresh and retry.", 502);
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        body
          ? "Timed out. Refresh before trying again."
          : "Connection timed out. Start the local service.",
        408,
      );
    throw new ApiError(
      body
        ? "Connection lost. Refresh before trying again."
        : "Local service unavailable.",
      0,
    );
  } finally {
    clearTimeout(timer);
  }
}
