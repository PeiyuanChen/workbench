// 与后端 JSON 契约一一对应（见 backend/app/api/ 各路由 + SPEC-M2 §2）

export type Quadrant = "q1" | "q2" | "q3" | "q4";
export type TimeStage = "unscheduled" | "due" | "block" | "both";
// VTODO STATUS（RFC 5545；放弃 = CANCELLED，UI 文案"已放弃"——SPEC-M2 决策 #1）
export type TodoStatus = "NEEDS-ACTION" | "IN-PROCESS" | "COMPLETED" | "CANCELLED";

export interface Todo {
  uid: string;
  summary: string;
  description: string;
  status: TodoStatus;
  priority: number | null;
  categories: string[];
  important: boolean;
  urgent: boolean;
  quadrant: Quadrant;
  has_time: TimeStage;
  overdue: boolean;
  dtstart: string | null;
  due: string | null;
  duration_minutes: number | null;
  all_day: boolean;
  parent_uid: string | null;
  progress: number | null;
  children_total: number; // 非 CANCELLED 子任务数（SPEC-M2 §1：放弃不计入分母）
  children_done: number;
  children_cancelled: number;
  created: string | null; // UTC ISO，用于视图排序
  children: Todo[];
}

export interface CalendarItem {
  type: "event" | "block" | "due";
  uid: string;
  summary: string;
  categories: string[];
  location: string;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  all_day: boolean;
  days_in_month: string[];
}

/** GET /api/events/{uid}：单条事件详情（编辑表单数据源；dtend 为 RFC 排他语义） */
export interface EventDetail {
  uid: string;
  dtstamp: string | null;
  summary: string;
  description: string;
  location: string;
  status: string;
  categories: string[];
  dtstart: string | null;
  dtend: string | null;
  all_day: boolean;
  alarms: { trigger: string; action: string; description: string }[];
}

export interface Note {
  id: string;
  title: string;
  date: string | null;
  tags: string[];
  related: string[];
  created: string | null;
  excerpt: string;
  filename: string;
  content?: string; // 仅详情/写响应返回
}

export interface TimelineResp {
  exists: boolean;
  message?: string;
  frontmatter?: Record<string, unknown>;
  body?: string;
}

// ---------------------------------------------------------------- 写请求 payload

/** POST /api/todos（时间为 ISO 字符串；naive 由后端按 Asia/Shanghai 解释） */
export interface TodoCreate {
  summary: string;
  description?: string;
  important?: boolean;
  urgent?: boolean;
  due?: string | null;
  dtstart?: string | null;
  duration_minutes?: number | null;
  all_day?: boolean;
  categories?: string[] | null;
  parent_uid?: string | null;
}

/** PATCH /api/todos/{uid}：没传的字段不动；显式 null = 清除；不接受 status */
export type TodoPatch = Partial<TodoCreate>;

/** POST /api/events（dtend 恒为 RFC 排他语义：全天结束日 = 用户选择日 +1 天） */
export interface EventCreate {
  summary: string;
  dtstart: string;
  dtend?: string | null;
  duration_minutes?: number | null;
  location?: string | null;
  description?: string | null;
  categories?: string[] | null;
  all_day?: boolean;
}

export type EventPatch = Partial<Omit<EventCreate, "dtstart">> & { dtstart?: string | null };

/** POST /api/notes（id/文件名服务端生成，SPEC-M2 §2.3） */
export interface NoteCreate {
  title: string;
  content?: string;
  tags?: string[];
  related?: string[];
}

/** PUT /api/notes/{id}：全文更新（tags/related 未传即重置为空） */
export interface NoteUpdate {
  title: string;
  content?: string;
  tags?: string[];
  related?: string[];
}
