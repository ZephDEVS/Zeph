import type { ActivityTask, Config, Conversation, EventEnvelope, Message, Schedule, User } from "./types";

const authHeaders = (token?: string): HeadersInit =>
  token ? { Authorization: `Bearer ${token}` } : {};

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
      ...(init.headers ?? {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error ?? "Request failed.");
  }
  return payload as T;
}

export const api = {
  bootstrap: () => request<{ appName: string; guide: string; tos: string; tosVersion: string }>("/api/bootstrap"),
  signup: (payload: Record<string, unknown>) =>
    request<{ token: string; user: User; config: Config; tosAccepted: boolean }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload: Record<string, unknown>) =>
    request<{ token: string; user: User; config: Config; tosAccepted: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: (token: string) => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }, token),
  me: (token: string) =>
    request<{ user: User; config: Config; tosAccepted: boolean }>("/api/me", { method: "GET" }, token),
  acceptTos: (token: string) => request<{ ok: boolean }>("/api/auth/accept-tos", { method: "POST" }, token),
  conversations: (token: string) =>
    request<{ conversations: Conversation[] }>("/api/conversations", { method: "GET" }, token),
  createConversation: (token: string) =>
    request<{ conversation: Conversation; messages: Message[] }>("/api/conversations", { method: "POST" }, token),
  deleteConversation: (token: string, id: number) =>
    request<{ ok: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }, token),
  messages: (token: string, id: number) =>
    request<{ messages: Message[] }>(`/api/conversations/${id}/messages`, { method: "GET" }, token),
  submitCommand: (token: string, id: number, payload: { command: string; dryRun: boolean }) =>
    request<{ accepted: boolean; message: Message }>(`/api/conversations/${id}/command`, {
      method: "POST",
      body: JSON.stringify(payload),
    }, token),
  pollEvents: (token: string, cursor: number) =>
    request<{ events: EventEnvelope[]; cursor: number; busy: boolean; busyLabel: string }>(`/api/events?cursor=${cursor}`, { method: "GET" }, token),
  respondPrompt: (token: string, promptId: number, approved: boolean) =>
    request<{ ok: boolean }>(`/api/prompts/${promptId}/respond`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }, token),
  activity: (token: string) =>
    request<{ tasks: ActivityTask[]; logs: string[] }>("/api/activity", { method: "GET" }, token),
  schedules: (token: string) =>
    request<{ schedules: Schedule[] }>("/api/schedules", { method: "GET" }, token),
  createSchedule: (token: string, command: string) =>
    request<{ schedule: Schedule }>("/api/schedules", { method: "POST", body: JSON.stringify({ command }) }, token),
  mutateSchedule: (token: string, taskId: string, action: "pause" | "resume" | "delete") =>
    request<{ ok: boolean }>(`/api/schedules/${taskId}/${action}`, { method: "POST" }, token),
  settings: (token: string) => request<{ config: Config }>("/api/settings", { method: "GET" }, token),
  updateSettings: (token: string, payload: Partial<Config>) =>
    request<{ config: Config }>("/api/settings", { method: "PUT", body: JSON.stringify(payload) }, token),
};
