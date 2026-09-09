// 统一 API 客户端：相对路径 /api（dev 走 Vite 代理，生产同源）

type Params = Record<string, string | number | undefined | null>;

export async function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = `/api/${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`接口 ${url} 返回 ${res.status}`);
  }
  return (await res.json()) as T;
}
