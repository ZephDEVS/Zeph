export type User = {
  id: number;
  username: string;
  displayName: string;
  createdAt: string;
};

export type Config = {
  agentName: string;
  userName: string;
  aiProvider: string;
  aiModel: string;
  browserMode: string;
  preferredWpm: number;
  wakeWord: string;
  voiceRate: number;
  voiceLanguage: string;
  speedMode: string;
  speedMultiplier: number;
  clipboardHistoryLimit: number;
  confirm: Record<string, boolean>;
};

export type Conversation = {
  id: number;
  title: string;
  createdAt: string;
  updatedAt: string;
};

export type Message = {
  id: number;
  conversationId: number;
  role: "user" | "agent" | "system" | "error" | "plan";
  content: string;
  createdAt: string;
};

export type PromptRequest = {
  id: number;
  type: "confirm" | "plan";
  title: string;
  body: string;
  steps: string[];
};

export type Schedule = {
  id: string;
  naturalLanguage: string;
  active: boolean;
  createdAt: string;
};

export type ActivityTask = {
  task: string;
  status: string;
  detail: string;
  createdAt: string;
};

export type EventEnvelope =
  | { id: number; type: "status"; busy: boolean; label: string }
  | { id: number; type: "conversation_message"; message: Message }
  | { id: number; type: "pending_prompt"; prompt: PromptRequest }
  | { id: number; type: "conversation_refresh"; conversationId: number }
  | { id: number; type: "settings_refresh"; config: Config }
  | { id: number; type: "schedule_refresh" };
