// 统一 API 客户端：相对路径 /api（dev 走 Vite 代理，生产同源）
//
// M2 契约（SPEC-M2 §2）：
// - GET 响应 = M1 各接口原形状（{count,items} 等）；
// - 写响应 = {"ok":true,"data":...} 信封，sendJson 统一解包直接返回 data；
// - 错误 = HTTP 4xx/5xx + {"detail":"中文"}，抛 ApiError（message=后端中文 detail），
//   调用方（视图层）原样展示，不做乐观更新。

type Params = Record<string, string | number | undefined | null>;

/** 后端返回的业务错误：message 即中文 detail，可直接展示给用户 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildUrl(path: string, params: Params): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return `/api/${path}${qs.toString() ? `?${qs}` : ""}`;
}

/** 非 2xx：尽力解析 {"detail":"中文"}，失败退回状态码文案 */
async function parseError(res: Response, url: string): Promise<never> {
  let detail = `接口 ${url} 返回 ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    /* 响应体不是 JSON：保留默认文案 */
  }
  throw new ApiError(res.status, detail);
}

export async function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const url = buildUrl(path, params);
  const res = await fetch(url);
  if (!res.ok) await parseError(res, url);
  return (await res.json()) as T;
}

/** 写请求通用：解 {"ok","data"} 信封，直接返回 data（受影响的最新对象） */
async function sendJson<T>(method: string, path: string, body: unknown, params: Params): Promise<T> {
  const url = buildUrl(path, params);
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) await parseError(res, url);
  const envelope = (await res.json()) as { ok?: boolean; data?: T };
  if (!envelope.ok) throw new ApiError(res.status, `接口 ${url} 未返回成功信封`);
  return envelope.data as T;
}

export function postJson<T>(path: string, body: unknown, params: Params = {}): Promise<T> {
  return sendJson<T>("POST", path, body, params);
}

export function patchJson<T>(path: string, body: unknown, params: Params = {}): Promise<T> {
  return sendJson<T>("PATCH", path, body, params);
}

export function putJson<T>(path: string, body: unknown, params: Params = {}): Promise<T> {
  return sendJson<T>("PUT", path, body, params);
}

export function delJson<T>(path: string, params: Params = {}): Promise<T> {
  return sendJson<T>("DELETE", path, undefined, params);
}
