import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { ActivityTask, Config, Conversation, EventEnvelope, Message, PromptRequest, Schedule, User } from "./types";

type WorkspaceTab = "activity" | "automations" | "guide" | "terms" | "settings";
type AuthMode = "login" | "signup";

const TOKEN_KEY = "zeph.session.token";

const relativeTime = (value: string) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
};

function App() {
  const [boot, setBoot] = useState<{ appName: string; guide: string; tos: string; tosVersion: string } | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [token, setToken] = useState<string | null>(() => window.localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [tosAccepted, setTosAccepted] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Record<number, Message[]>>({});
  const [composer, setComposer] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("Ready");
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("activity");
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [activity, setActivity] = useState<ActivityTask[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [scheduleDraft, setScheduleDraft] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState<PromptRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authDocument, setAuthDocument] = useState<"terms" | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<Partial<Config>>({});
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [signupForm, setSignupForm] = useState({
    displayName: "",
    username: "",
    password: "",
    confirmPassword: "",
    apiKey: "",
    preferredWpm: "80",
    wakeWord: "Hey DAIA",
    acceptTos: false,
  });
  const [cursor, setCursor] = useState(0);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const cursorRef = useRef(0);

  const activeMessages = useMemo(
    () => (activeConversationId ? messages[activeConversationId] ?? [] : []),
    [activeConversationId, messages],
  );

  useEffect(() => {
    api.bootstrap().then(setBoot).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!token) return;
    api.me(token)
      .then(async (payload) => {
        setUser(payload.user);
        setConfig(payload.config);
        setSettingsDraft(payload.config);
        setTosAccepted(payload.tosAccepted);
        await loadWorkspace(token);
        await loadConversations(token);
      })
      .catch(() => {
        window.localStorage.removeItem(TOKEN_KEY);
        setToken(null);
      });
  }, [token]);

  useEffect(() => {
    if (!token || !user) return;
    const interval = window.setInterval(async () => {
      try {
        const payload = await api.pollEvents(token, cursorRef.current);
        cursorRef.current = payload.cursor;
        setCursor(payload.cursor);
        setBusy(payload.busy);
        setBusyLabel(payload.busyLabel);
        handleEvents(payload.events);
      } catch {
        // Ignore transient polling errors.
      }
    }, 700);
    return () => window.clearInterval(interval);
  }, [token, user]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [activeMessages]);

  const handleEvents = (events: EventEnvelope[]) => {
    events.forEach((event) => {
      if (event.type === "status") {
        setBusy(event.busy);
        setBusyLabel(event.label);
        return;
      }
      if (event.type === "conversation_message") {
        setMessages((current) => {
          const next = { ...current };
          const existing = next[event.message.conversationId] ?? [];
          if (!existing.some((item) => item.id === event.message.id)) {
            next[event.message.conversationId] = [...existing, event.message];
          }
          return next;
        });
        return;
      }
      if (event.type === "pending_prompt") {
        setPendingPrompt(event.prompt);
        return;
      }
      if (event.type === "conversation_refresh") {
        if (token) {
          loadConversations(token);
        }
        return;
      }
      if (event.type === "settings_refresh") {
        setConfig(event.config);
        setSettingsDraft(event.config);
        return;
      }
      if (event.type === "schedule_refresh" && token) {
        loadSchedules(token);
      }
    });
  };

  const loadConversations = async (sessionToken: string) => {
    const payload = await api.conversations(sessionToken);
    setConversations(payload.conversations);
    if (payload.conversations.length === 0) {
      const created = await api.createConversation(sessionToken);
      setConversations([created.conversation]);
      setMessages((current) => ({ ...current, [created.conversation.id]: created.messages }));
      setActiveConversationId(created.conversation.id);
      return;
    }
    const nextConversationId = activeConversationId ?? payload.conversations[0]?.id ?? null;
    if (nextConversationId) {
      setActiveConversationId(nextConversationId);
      if (!messages[nextConversationId]) {
        const messagePayload = await api.messages(sessionToken, nextConversationId);
        setMessages((current) => ({ ...current, [nextConversationId]: messagePayload.messages }));
      }
    }
  };

  const loadWorkspace = async (sessionToken: string) => {
    const [activityPayload, schedulePayload] = await Promise.all([
      api.activity(sessionToken),
      api.schedules(sessionToken),
    ]);
    setActivity(activityPayload.tasks);
    setLogs(activityPayload.logs);
    setSchedules(schedulePayload.schedules);
  };

  const loadSchedules = async (sessionToken: string) => {
    const payload = await api.schedules(sessionToken);
    setSchedules(payload.schedules);
  };

  const beginSession = async (promise: Promise<{ token: string; user: User; config: Config; tosAccepted: boolean }>) => {
    setError(null);
    const payload = await promise;
    cursorRef.current = 0;
    window.localStorage.setItem(TOKEN_KEY, payload.token);
    setToken(payload.token);
    setUser(payload.user);
    setConfig(payload.config);
    setSettingsDraft(payload.config);
    setTosAccepted(payload.tosAccepted);
  };

  const handleLogin = async () => {
    try {
      await beginSession(api.login(loginForm));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleSignup = async () => {
    if (signupForm.password !== signupForm.confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    try {
      await beginSession(
        api.signup({
          ...signupForm,
          preferredWpm: Number(signupForm.preferredWpm || 80),
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const createConversation = async () => {
    if (!token) return;
    const payload = await api.createConversation(token);
    setConversations((current) => [payload.conversation, ...current]);
    setMessages((current) => ({ ...current, [payload.conversation.id]: payload.messages }));
    setActiveConversationId(payload.conversation.id);
  };

  const openConversation = async (conversationId: number) => {
    if (!token) return;
    setActiveConversationId(conversationId);
    if (!messages[conversationId]) {
      const payload = await api.messages(token, conversationId);
      setMessages((current) => ({ ...current, [conversationId]: payload.messages }));
    }
  };

  const submitCommand = async () => {
    if (!token || !activeConversationId || !composer.trim() || busy) return;
    const text = composer.trim();
    setComposer("");
    try {
      const payload = await api.submitCommand(token, activeConversationId, { command: text, dryRun });
      setMessages((current) => ({
        ...current,
        [activeConversationId]: [...(current[activeConversationId] ?? []), payload.message],
      }));
      await loadConversations(token);
    } catch (err) {
      setError((err as Error).message);
      setComposer(text);
    }
  };

  const logout = async () => {
    if (token) {
      await api.logout(token);
    }
    window.localStorage.removeItem(TOKEN_KEY);
    cursorRef.current = 0;
    setCursor(0);
    setToken(null);
    setUser(null);
    setConfig(null);
    setConversations([]);
    setMessages({});
    setActiveConversationId(null);
    setAccountMenuOpen(false);
  };

  const removeConversation = async () => {
    if (!token || !activeConversationId) return;
    await api.deleteConversation(token, activeConversationId);
    const next = conversations.filter((conversation) => conversation.id !== activeConversationId);
    setConversations(next);
    const fallback = next[0]?.id ?? null;
    setActiveConversationId(fallback);
    if (fallback) {
      await openConversation(fallback);
    } else {
      await createConversation();
    }
  };

  const saveSettings = async () => {
    if (!token) return;
    try {
      const payload = await api.updateSettings(token, settingsDraft);
      setConfig(payload.config);
      setSettingsDraft(payload.config);
      setWorkspaceOpen(false);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const submitPromptDecision = async (approved: boolean) => {
    if (!token || !pendingPrompt) return;
    await api.respondPrompt(token, pendingPrompt.id, approved);
    setPendingPrompt(null);
  };

  const saveTos = async () => {
    if (!token) return;
    await api.acceptTos(token);
    setTosAccepted(true);
  };

  const addSchedule = async () => {
    if (!token || !scheduleDraft.trim()) return;
    await api.createSchedule(token, scheduleDraft.trim());
    setScheduleDraft("");
    await loadSchedules(token);
  };

  const mutateSchedule = async (scheduleId: string, action: "pause" | "resume" | "delete") => {
    if (!token) return;
    await api.mutateSchedule(token, scheduleId, action);
    await loadSchedules(token);
  };

  const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId) ?? null;

  if (!boot) {
    return <div className="app-shell loading-shell">Loading Zeph...</div>;
  }

  if (!token || !user || !config) {
    return (
      <div className="app-shell auth-shell">
        <div className="ambient ambient-left" />
        <div className="ambient ambient-right" />
        <section className="auth-hero">
          <div className="eyebrow">Desktop AI Agent</div>
          <h1>{boot.appName}</h1>
          <p>
            A local assistant that chats cleanly, plans clearly, and can still open windows,
            type into apps, manage files, and automate your desktop.
          </p>
          <div className="hero-card">
            <span>React + TypeScript workspace</span>
            <span>Local Python agent backend</span>
            <span>Private by default</span>
          </div>
        </section>
        <section className="auth-panel">
          <div className="auth-tabs">
            <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>Log in</button>
            <button className={authMode === "signup" ? "active" : ""} onClick={() => setAuthMode("signup")}>Sign up</button>
          </div>
          {error && <div className="error-banner">{error}</div>}
          {authMode === "login" ? (
            <div className="form-grid">
              <label>
                Username
                <input value={loginForm.username} onChange={(event) => setLoginForm({ ...loginForm, username: event.target.value })} />
              </label>
              <label>
                Password
                <input type="password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} />
              </label>
              <button className="primary" onClick={handleLogin}>Continue</button>
            </div>
          ) : (
            <div className="form-grid">
              <label>
                Display name
                <input value={signupForm.displayName} onChange={(event) => setSignupForm({ ...signupForm, displayName: event.target.value })} />
              </label>
              <label>
                Username
                <input value={signupForm.username} onChange={(event) => setSignupForm({ ...signupForm, username: event.target.value })} />
              </label>
              <label>
                Password
                <input type="password" value={signupForm.password} onChange={(event) => setSignupForm({ ...signupForm, password: event.target.value })} />
              </label>
              <label>
                Confirm password
                <input type="password" value={signupForm.confirmPassword} onChange={(event) => setSignupForm({ ...signupForm, confirmPassword: event.target.value })} />
              </label>
              <label>
                Preferred WPM
                <input value={signupForm.preferredWpm} onChange={(event) => setSignupForm({ ...signupForm, preferredWpm: event.target.value })} />
              </label>
              <label>
                Wake word
                <input value={signupForm.wakeWord} onChange={(event) => setSignupForm({ ...signupForm, wakeWord: event.target.value })} />
              </label>
              <label className="full-width">
                API key
                <input value={signupForm.apiKey} onChange={(event) => setSignupForm({ ...signupForm, apiKey: event.target.value })} />
              </label>
              <label className="checkbox-row full-width">
                <input
                  type="checkbox"
                  checked={signupForm.acceptTos}
                  onChange={(event) => setSignupForm({ ...signupForm, acceptTos: event.target.checked })}
                />
                <span>I accept the Terms of Service.</span>
              </label>
              <button className="secondary full-width" onClick={() => setAuthDocument("terms")}>Preview Terms</button>
              <button className="primary full-width" onClick={handleSignup}>Create account</button>
            </div>
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="eyebrow">Local workspace</div>
          <h1>Zeph</h1>
          <button className="primary sidebar-button" onClick={createConversation}>New chat</button>
        </div>
        <div className="chat-list">
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              className={`chat-item ${conversation.id === activeConversationId ? "active" : ""}`}
              onClick={() => void openConversation(conversation.id)}
            >
              <span>{conversation.title}</span>
              <small>{relativeTime(conversation.updatedAt)}</small>
            </button>
          ))}
        </div>
        <div className="sidebar-bottom">
          <button className="ghost" onClick={removeConversation}>Delete chat</button>
          <button className="ghost" onClick={() => { setWorkspaceTab("activity"); setWorkspaceOpen(true); }}>Workspace</button>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <div className="eyebrow">Conversation</div>
            <h2>{activeConversation?.title ?? "New chat"}</h2>
            <p>{config.aiModel} ready for chat and desktop actions</p>
          </div>
          <div className="topbar-actions">
            <span className={`status-pill ${busy ? "busy" : ""}`}>{busyLabel}</span>
            <button className="ghost" onClick={() => { setWorkspaceTab("activity"); setWorkspaceOpen(true); }}>Workspace</button>
            <div className="account-menu-shell">
              <button className="ghost" onClick={() => setAccountMenuOpen((current) => !current)}>{user.displayName}</button>
              {accountMenuOpen && (
                <div className="account-menu">
                  <button onClick={() => { setWorkspaceTab("settings"); setWorkspaceOpen(true); setAccountMenuOpen(false); }}>Settings</button>
                  <button onClick={() => void logout()}>Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>

        <section className="transcript" ref={transcriptRef}>
          {activeMessages.map((message) => (
            <article key={message.id} className={`message-row ${message.role}`}>
              <div className="message-meta">{message.role === "user" ? "You" : message.role === "agent" ? "Zeph" : message.role}</div>
              <div className={`bubble ${message.role}`}>
                {message.content.split("\n").map((line, index) => (
                  <p key={`${message.id}-${index}`}>{line}</p>
                ))}
              </div>
            </article>
          ))}
        </section>

        <footer className="composer-shell">
          <div className="composer">
            <textarea
              value={composer}
              placeholder="Message Zeph"
              onChange={(event) => setComposer(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitCommand();
                }
              }}
            />
            <div className="composer-footer">
              <label className="checkbox-row">
                <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
                <span>Dry run</span>
              </label>
              <div className="composer-actions">
                <button className="ghost" onClick={() => setComposer("take a screenshot of my screen and tell me what you see")}>Vision</button>
                <button className="ghost" onClick={() => setComposer("what windows do I have open right now?")}>Windows</button>
                <button className="primary" onClick={() => void submitCommand()} disabled={busy}>Send</button>
              </div>
            </div>
          </div>
        </footer>
      </main>

      {workspaceOpen && (
        <div className="overlay" onClick={() => setWorkspaceOpen(false)}>
          <aside className="workspace-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-head">
              <h3>Workspace</h3>
              <button className="ghost" onClick={() => setWorkspaceOpen(false)}>Close</button>
            </div>
            <div className="drawer-tabs">
              {(["activity", "automations", "guide", "terms", "settings"] as WorkspaceTab[]).map((tab) => (
                <button key={tab} className={workspaceTab === tab ? "active" : ""} onClick={() => setWorkspaceTab(tab)}>
                  {tab}
                </button>
              ))}
            </div>
            <div className="drawer-body">
              {workspaceTab === "activity" && (
                <div className="stack">
                  <section className="panel-block">
                    <h4>Recent tasks</h4>
                    {activity.map((item, index) => (
                      <div className="list-card" key={`${item.createdAt}-${index}`}>
                        <strong>{item.task}</strong>
                        <span>{item.status}</span>
                        <small>{relativeTime(item.createdAt)}</small>
                      </div>
                    ))}
                  </section>
                  <section className="panel-block">
                    <h4>Recent logs</h4>
                    <pre className="code-panel">{logs.join("\n")}</pre>
                  </section>
                </div>
              )}
              {workspaceTab === "automations" && (
                <div className="stack">
                  <section className="panel-block">
                    <h4>Create automation</h4>
                    <div className="inline-form">
                      <input value={scheduleDraft} onChange={(event) => setScheduleDraft(event.target.value)} placeholder="Every day at 8am, open my calendar app" />
                      <button className="primary" onClick={() => void addSchedule()}>Create</button>
                    </div>
                  </section>
                  <section className="panel-block">
                    <h4>Saved automations</h4>
                    {schedules.map((schedule) => (
                      <div className="list-card" key={schedule.id}>
                        <strong>{schedule.naturalLanguage}</strong>
                        <span>{schedule.active ? "Active" : "Paused"}</span>
                        <div className="inline-actions">
                          <button className="ghost" onClick={() => void mutateSchedule(schedule.id, schedule.active ? "pause" : "resume")}>
                            {schedule.active ? "Pause" : "Resume"}
                          </button>
                          <button className="ghost danger" onClick={() => void mutateSchedule(schedule.id, "delete")}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </section>
                </div>
              )}
              {workspaceTab === "guide" && <pre className="code-panel prose">{boot.guide}</pre>}
              {workspaceTab === "terms" && <pre className="code-panel prose">{boot.tos}</pre>}
              {workspaceTab === "settings" && (
                <div className="form-grid">
                  <label>
                    Display name
                    <input value={String(settingsDraft.userName ?? "")} onChange={(event) => setSettingsDraft({ ...settingsDraft, userName: event.target.value })} />
                  </label>
                  <label>
                    Model
                    <input value={String(settingsDraft.aiModel ?? "")} onChange={(event) => setSettingsDraft({ ...settingsDraft, aiModel: event.target.value })} />
                  </label>
                  <label>
                    Browser mode
                    <select value={String(settingsDraft.browserMode ?? "default")} onChange={(event) => setSettingsDraft({ ...settingsDraft, browserMode: event.target.value })}>
                      <option value="default">default</option>
                      <option value="playwright">playwright</option>
                    </select>
                  </label>
                  <label>
                    Typing WPM
                    <input value={String(settingsDraft.preferredWpm ?? 80)} onChange={(event) => setSettingsDraft({ ...settingsDraft, preferredWpm: Number(event.target.value) })} />
                  </label>
                  <label>
                    Wake word
                    <input value={String(settingsDraft.wakeWord ?? "")} onChange={(event) => setSettingsDraft({ ...settingsDraft, wakeWord: event.target.value })} />
                  </label>
                  <label>
                    Speed mode
                    <select value={String(settingsDraft.speedMode ?? "normal")} onChange={(event) => setSettingsDraft({ ...settingsDraft, speedMode: event.target.value })}>
                      <option value="slow">slow</option>
                      <option value="normal">normal</option>
                      <option value="fast">fast</option>
                      <option value="stealth">stealth</option>
                    </select>
                  </label>
                  <button className="primary full-width" onClick={() => void saveSettings()}>Save settings</button>
                </div>
              )}
            </div>
          </aside>
        </div>
      )}

      {pendingPrompt && (
        <div className="overlay">
          <div className="modal">
            <h3>{pendingPrompt.title}</h3>
            <p>{pendingPrompt.body}</p>
            {pendingPrompt.steps.length > 0 && (
              <ol className="plan-list">
                {pendingPrompt.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}
            <div className="modal-actions">
              <button className="ghost" onClick={() => void submitPromptDecision(false)}>Cancel</button>
              <button className="primary" onClick={() => void submitPromptDecision(true)}>
                {pendingPrompt.type === "plan" ? "Proceed" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}

      {!tosAccepted && (
        <div className="overlay">
          <div className="modal wide">
            <h3>Accept Terms of Service</h3>
            <pre className="code-panel prose">{boot.tos}</pre>
            <div className="modal-actions">
              <button className="primary" onClick={() => void saveTos()}>I accept</button>
            </div>
          </div>
        </div>
      )}

      {error && token && (
        <div className="toast" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {authDocument === "terms" && (
        <div className="overlay" onClick={() => setAuthDocument(null)}>
          <div className="modal wide" onClick={(event) => event.stopPropagation()}>
            <h3>Terms of Service</h3>
            <pre className="code-panel prose">{boot.tos}</pre>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setAuthDocument(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
