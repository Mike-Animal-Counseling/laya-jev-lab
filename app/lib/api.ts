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
    if (body && !csrfToken) {
      const session = await fetch("/api/session", {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!session.ok)
        throw new ApiError(
          "无法建立本地安全会话，请刷新页面。",
          session.status,
        );
      const sessionData = (await session.json()) as { csrf_token?: unknown };
      if (typeof sessionData.csrf_token !== "string")
        throw new ApiError("安全会话返回格式异常，请刷新页面。", 502);
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
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken,
              },
              body: JSON.stringify({ ...body, provider }),
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
        data?.error || `服务暂时不可用（${response.status}）`,
        response.status,
      );
    }
    if (!data) throw new ApiError("服务返回格式异常，请刷新后重试。", 502);
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        body
          ? "等待超时。操作可能仍在后台执行，请先刷新查看结果，避免重复提交。"
          : "连接超时，请确认本地服务已启动。",
        408,
      );
    throw new ApiError(
      body
        ? "连接中断。请先刷新查看操作是否完成，再决定是否重试。"
        : "无法连接工单服务，请确认本地服务已启动。",
      0,
    );
  } finally {
    clearTimeout(timer);
  }
}
