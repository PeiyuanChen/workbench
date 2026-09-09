// 展示层格式化（只处理字符串/日期，不碰业务逻辑）

/** "2026-09-08T18:00:00+08:00" → "9/8"；全天 "2026-09-20" → "9/20" */
export function shortDate(iso: string | null): string {
  if (!iso) return "";
  const d = iso.slice(0, 10);
  const [, m, day] = d.split("-");
  return `${Number(m)}/${Number(day)}`;
}

/** 取时分 "18:00"；全天返回空 */
export function shortTime(iso: string | null): string {
  if (!iso || iso.length <= 10) return "";
  return iso.slice(11, 16);
}

/** 截止展示："截止 9/8 18:00"（全天则不带时间） */
export function dueText(iso: string | null): string {
  if (!iso) return "";
  const t = shortTime(iso);
  return t ? `截止 ${shortDate(iso)} ${t}` : `截止 ${shortDate(iso)}`;
}

/** 执行块展示："9/8 09:00 时间块"；全天按天数 */
export function blockText(iso: string | null, durationMinutes: number | null, allDay: boolean): string {
  if (!iso) return "";
  if (allDay) {
    const days = durationMinutes ? Math.round(durationMinutes / 1440) : 1;
    return `${shortDate(iso)} 起 ${days} 天（全天）`;
  }
  const t = shortTime(iso);
  return `${shortDate(iso)} ${t} 时间块`;
}

/** "2026年9月4日 周四" */
export function todayCN(now = new Date()): string {
  const weeks = ["日", "一", "二", "三", "四", "五", "六"];
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 周${weeks[now.getDay()]}`;
}
