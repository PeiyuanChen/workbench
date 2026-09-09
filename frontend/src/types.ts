// 与后端 JSON 契约一一对应（见 backend/app/api/ 各路由）

export type Quadrant = "q1" | "q2" | "q3" | "q4";
export type TimeStage = "unscheduled" | "due" | "block" | "both";

export interface Todo {
  uid: string;
  summary: string;
  description: string;
  status: string;
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
  children_total: number;
  children_done: number;
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

export interface Note {
  id: string;
  title: string;
  date: string | null;
  tags: string[];
  related: string[];
  created: string | null;
  excerpt: string;
  filename: string;
  content?: string;
}

export interface TimelineResp {
  exists: boolean;
  message?: string;
  frontmatter?: Record<string, unknown>;
  body?: string;
}
