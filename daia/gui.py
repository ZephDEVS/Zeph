"""Native desktop GUI for Zeph."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from daia.agent import ZephAgent
from daia.config import APP_DIR
from daia.memory import ConversationRecord, UserRecord


ASSETS_DIR = Path(__file__).parent / "assets"
TOS_VERSION = "1.0"


class PlanApprovalDialog(tk.Toplevel):
    """Modal dialog for multi-step plan approval."""

    def __init__(self, master: tk.Misc, steps: list[str]) -> None:
        super().__init__(master)
        self.result = False
        self.title("Review Plan")
        self.geometry("640x460")
        self.configure(bg="#101114")
        self.transient(master)
        self.grab_set()

        shell = ttk.Frame(self, padding=24, style="App.TFrame")
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text="Approve Plan", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Zeph will wait for your approval before continuing.", style="Muted.TLabel").pack(anchor="w", pady=(6, 16))

        text = scrolledtext.ScrolledText(
            shell,
            wrap="word",
            relief="flat",
            background="#15171c",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=18,
            pady=18,
            font=("SF Pro Text", 13),
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n".join(f"{idx}. {step}" for idx, step in enumerate(steps, start=1)))
        text.configure(state="disabled")

        actions = ttk.Frame(shell, style="App.TFrame")
        actions.pack(fill="x", pady=(16, 0))
        ttk.Button(actions, text="Cancel", command=self._cancel, style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Proceed", command=self._proceed, style="Primary.TButton").pack(side="right", padx=(0, 10))
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _proceed(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()


class TermsDialog(tk.Toplevel):
    """Mandatory TOS acceptance dialog."""

    def __init__(self, master: tk.Misc, tos_text: str) -> None:
        super().__init__(master)
        self.result = False
        self.title("Terms of Service")
        self.geometry("780x640")
        self.configure(bg="#101114")
        self.transient(master)
        self.grab_set()

        accepted = tk.BooleanVar(value=False)

        shell = ttk.Frame(self, padding=24, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(1, weight=1)
        shell.columnconfigure(0, weight=1)

        ttk.Label(shell, text="Accept Terms of Service", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            shell,
            text="You must accept the local Zeph Terms of Service before using the app.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="sw")

        text = scrolledtext.ScrolledText(
            shell,
            wrap="word",
            relief="flat",
            background="#15171c",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=18,
            pady=18,
            font=("SF Pro Text", 12),
        )
        text.grid(row=1, column=0, sticky="nsew", pady=(18, 14))
        text.insert("1.0", tos_text)
        text.configure(state="disabled")

        ttk.Checkbutton(
            shell,
            text="I have read and accept the Terms of Service.",
            variable=accepted,
        ).grid(row=2, column=0, sticky="w")

        actions = ttk.Frame(shell, style="App.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text="Decline", command=self._decline, style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="I Accept", command=lambda: self._accept(accepted.get()), style="Primary.TButton").pack(side="right", padx=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self._decline)

    def _accept(self, accepted: bool) -> None:
        if not accepted:
            messagebox.showerror("Acceptance required", "Please confirm that you accept the Terms of Service.")
            return
        self.result = True
        self.destroy()

    def _decline(self) -> None:
        self.result = False
        self.destroy()


class ZephDesktopApp:
    """Desktop shell for Zeph."""

    POLL_INTERVAL_MS = 100

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Zeph")
        self.root.geometry("1320x900")
        self.root.minsize(980, 700)
        self.root.configure(bg="#101114")

        self.agent = ZephAgent(
            event_callback=self._enqueue_agent_event,
            confirm_handler=self._confirm_from_worker,
            plan_handler=self._approve_plan_from_worker,
        )
        self.memory = self.agent.memory
        self.event_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.busy = False
        self.current_user: UserRecord | None = None
        self.message_count = 0
        self.current_conversation_id: int | None = None
        self.conversations: list[ConversationRecord] = []

        self.tos_text = (ASSETS_DIR / "tos.txt").read_text(encoding="utf-8")
        self.guide_text = (ASSETS_DIR / "user_guide.md").read_text(encoding="utf-8")

        self.status_var = tk.StringVar(value="Not signed in")
        self.subtitle_var = tk.StringVar(value="Your local desktop AI agent")
        self.chat_title_var = tk.StringVar(value="New chat")
        self.account_label_var = tk.StringVar(value="Account")
        self.auth_message_var = tk.StringVar(value="Private, local, and ready when you are.")
        self.schedule_entry_var = tk.StringVar()
        self.dry_run_var = tk.BooleanVar(value=False)

        self.login_username_var = tk.StringVar()
        self.login_password_var = tk.StringVar()

        self.signup_display_name_var = tk.StringVar()
        self.signup_username_var = tk.StringVar()
        self.signup_password_var = tk.StringVar()
        self.signup_confirm_password_var = tk.StringVar()
        self.signup_api_key_var = tk.StringVar()
        self.signup_wpm_var = tk.StringVar(value="80")
        self.signup_wake_word_var = tk.StringVar(value="Hey DAIA")
        self.signup_tos_var = tk.BooleanVar(value=False)

        self._configure_styles()
        self._build_shell()
        self._show_auth_view()
        self.root.after(self.POLL_INTERVAL_MS, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        """Start the GUI main loop."""

        self.root.mainloop()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background="#111214", foreground="#edf2f7")
        style.configure("App.TFrame", background="#111214")
        style.configure("Sidebar.TFrame", background="#17191d")
        style.configure("Surface.TFrame", background="#17191d")
        style.configure("MutedSurface.TFrame", background="#1d2026")
        style.configure("Composer.TFrame", background="#17191d")
        style.configure("ComposerBody.TFrame", background="#1d2026")
        style.configure("Title.TLabel", background="#111214", foreground="#ffffff", font=("SF Pro Display", 26, "bold"))
        style.configure("HeroTitle.TLabel", background="#111214", foreground="#ffffff", font=("SF Pro Display", 20, "bold"))
        style.configure("SidebarTitle.TLabel", background="#17191d", foreground="#ffffff", font=("SF Pro Display", 20, "bold"))
        style.configure("CardTitle.TLabel", background="#17191d", foreground="#ffffff", font=("SF Pro Display", 14, "bold"))
        style.configure("Body.TLabel", background="#111214", foreground="#dde3ea", font=("SF Pro Text", 12))
        style.configure("Muted.TLabel", background="#111214", foreground="#8f98a3", font=("SF Pro Text", 11))
        style.configure("SidebarMuted.TLabel", background="#17191d", foreground="#8f98a3", font=("SF Pro Text", 11))
        style.configure("ComposerHint.TLabel", background="#1d2026", foreground="#8f98a3", font=("SF Pro Text", 11))
        style.configure("Small.TLabel", background="#17191d", foreground="#8f98a3", font=("SF Pro Text", 10))
        style.configure("Status.TLabel", background="#111214", foreground="#9fe870", font=("SF Pro Text", 11, "bold"))
        style.configure("FieldLabel.TLabel", background="#17191d", foreground="#aeb8c2", font=("SF Pro Text", 10, "bold"))
        style.configure("Primary.TButton", background="#ece8df", foreground="#121316", padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#ffffff")], foreground=[("disabled", "#5d656f")])
        style.configure("Secondary.TButton", background="#232730", foreground="#edf1f5", padding=(14, 10), borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#2c3140")])
        style.configure("Ghost.TButton", background="#17191d", foreground="#b8c1ca", padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#20242d")], foreground=[("active", "#ffffff")])
        style.configure("SidebarTool.TButton", background="#17191d", foreground="#9ea9b4", padding=(8, 6), borderwidth=0)
        style.map("SidebarTool.TButton", background=[("active", "#20242d")], foreground=[("active", "#ffffff")])
        style.configure("TEntry", fieldbackground="#1d2026", foreground="#edf1f5", insertcolor="#edf1f5", borderwidth=0, padding=10)
        style.configure("TCombobox", fieldbackground="#1d2026", foreground="#edf1f5", borderwidth=0, padding=8)
        style.configure("TCheckbutton", background="#17191d", foreground="#dde3ea")
        style.configure("Composer.TCheckbutton", background="#1d2026", foreground="#dde3ea")
        style.configure("App.Treeview", background="#17191d", fieldbackground="#17191d", foreground="#edf1f5", rowheight=30, borderwidth=0)
        style.configure("App.Treeview.Heading", background="#20242d", foreground="#9ea9b4", font=("SF Pro Text", 11, "bold"))
        style.map("App.Treeview", background=[("selected", "#2a3140")], foreground=[("selected", "#ffffff")])

    def _build_shell(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.auth_view = ttk.Frame(self.root, padding=28, style="App.TFrame")
        self.chat_view = ttk.Frame(self.root, padding=18, style="App.TFrame")
        self.auth_view.grid(row=0, column=0, sticky="nsew")
        self.chat_view.grid(row=0, column=0, sticky="nsew")

        self._build_auth_view()
        self._build_chat_view()

    def _build_auth_view(self) -> None:
        self.auth_view.columnconfigure(0, weight=1)
        self.auth_view.rowconfigure(0, weight=1)

        container = ttk.Frame(self.auth_view, style="App.TFrame")
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        hero = ttk.Frame(container, padding=30, style="Surface.TFrame")
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        ttk.Label(hero, text="Zeph", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            text="A cleaner, Claude-style desktop workspace for local automation.",
            style="Body.TLabel",
            wraplength=480,
        ).pack(anchor="w", pady=(10, 18))
        hero_text = (
            "What changed\n\n"
            "• Chat-first interface\n"
            "• Fewer panels and less dashboard clutter\n"
            "• Local sign up and log in\n"
            "• Built-in guide and Terms of Service\n"
            "• Cleaner assistant-style conversation flow"
        )
        panel = scrolledtext.ScrolledText(
            hero,
            wrap="word",
            height=18,
            relief="flat",
            background="#1a1d23",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=18,
            pady=18,
            font=("SF Pro Text", 13),
        )
        panel.pack(fill="both", expand=True)
        panel.insert("1.0", hero_text)
        panel.configure(state="disabled")

        auth = ttk.Frame(container, padding=26, style="Surface.TFrame")
        auth.grid(row=0, column=1, sticky="nsew")
        ttk.Label(auth, text="Welcome", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(auth, textvariable=self.auth_message_var, style="Muted.TLabel", wraplength=380).pack(anchor="w", pady=(6, 16))

        notebook = ttk.Notebook(auth)
        notebook.pack(fill="both", expand=True)

        login_tab = ttk.Frame(notebook, padding=16, style="Surface.TFrame")
        signup_tab = ttk.Frame(notebook, padding=16, style="Surface.TFrame")
        notebook.add(login_tab, text="Log In")
        notebook.add(signup_tab, text="Sign Up")

        login_tab.columnconfigure(0, weight=1)
        ttk.Label(login_tab, text="Username", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(login_tab, textvariable=self.login_username_var).grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(login_tab, text="Password", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(login_tab, textvariable=self.login_password_var, show="*").grid(row=3, column=0, sticky="ew", pady=(0, 16))
        ttk.Button(login_tab, text="Log In", command=self._handle_login, style="Primary.TButton").grid(row=4, column=0, sticky="ew")

        signup_tab.columnconfigure(0, weight=1)
        signup_tab.columnconfigure(1, weight=1)
        fields = [
            ("Display name", self.signup_display_name_var, 0, 0, 2),
            ("Username", self.signup_username_var, 2, 0, 1),
            ("Preferred WPM", self.signup_wpm_var, 2, 1, 1),
            ("Password", self.signup_password_var, 4, 0, 1),
            ("Confirm password", self.signup_confirm_password_var, 4, 1, 1),
            ("API key (optional)", self.signup_api_key_var, 6, 0, 2),
            ("Wake word", self.signup_wake_word_var, 8, 0, 2),
        ]
        for label, variable, row, column, span in fields:
            ttk.Label(signup_tab, text=label, style="FieldLabel.TLabel").grid(row=row, column=column, columnspan=span, sticky="w", pady=(0, 6), padx=(0, 8))
            entry = ttk.Entry(signup_tab, textvariable=variable, show="*" if "password" in label.lower() else "")
            entry.grid(row=row + 1, column=column, columnspan=span, sticky="ew", pady=(0, 12), padx=(0, 8) if span == 1 else 0)

        ttk.Checkbutton(
            signup_tab,
            text="I accept the Terms of Service.",
            variable=self.signup_tos_var,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 10))
        footer = ttk.Frame(signup_tab, style="Surface.TFrame")
        footer.grid(row=11, column=0, columnspan=2, sticky="ew")
        ttk.Button(footer, text="Read Terms", command=lambda: self._open_text_window("Terms of Service", self.tos_text), style="Ghost.TButton").pack(side="left")
        ttk.Button(footer, text="Create Account", command=self._handle_signup, style="Primary.TButton").pack(side="right")

    def _build_chat_view(self) -> None:
        self.chat_view.columnconfigure(1, weight=1)
        self.chat_view.rowconfigure(1, weight=1)

        sidebar = ttk.Frame(self.chat_view, padding=18, style="Sidebar.TFrame")
        sidebar.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 18))
        sidebar.configure(width=290)
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(2, weight=1)
        sidebar.columnconfigure(0, weight=1)

        sidebar_head = ttk.Frame(sidebar, style="Sidebar.TFrame")
        sidebar_head.grid(row=0, column=0, sticky="ew")
        ttk.Label(sidebar_head, text="Zeph", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(sidebar_head, text="Chats", style="SidebarMuted.TLabel").pack(anchor="w", pady=(4, 12))
        ttk.Button(sidebar_head, text="New Chat", command=self._new_chat, style="Primary.TButton").pack(fill="x")

        self.conversation_list = tk.Listbox(
            sidebar,
            background="#1d2026",
            foreground="#edf1f5",
            selectbackground="#2d3443",
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("SF Pro Text", 13),
            activestyle="none",
            relief="flat",
        )
        self.conversation_list.grid(row=2, column=0, sticky="nsew", pady=(16, 12))
        self.conversation_list.bind("<<ListboxSelect>>", self._handle_conversation_select)

        sidebar_footer = ttk.Frame(sidebar, style="Sidebar.TFrame")
        sidebar_footer.grid(row=3, column=0, sticky="ew")
        ttk.Button(sidebar_footer, text="Delete", command=self._delete_current_chat, style="SidebarTool.TButton").pack(side="left")
        ttk.Button(sidebar_footer, text="Guide", command=lambda: self._open_text_window("User Guide", self.guide_text), style="SidebarTool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(sidebar_footer, text="Activity", command=self._open_activity_window, style="SidebarTool.TButton").pack(side="left", padx=(8, 0))

        header = ttk.Frame(self.chat_view, padding=(4, 4, 4, 16), style="App.TFrame")
        header.grid(row=0, column=1, sticky="ew")
        header.columnconfigure(0, weight=1)

        title_block = ttk.Frame(header, style="App.TFrame")
        title_block.grid(row=0, column=0, sticky="w")
        ttk.Label(title_block, textvariable=self.chat_title_var, style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(title_block, textvariable=self.subtitle_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(header, style="App.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        ttk.Label(actions, textvariable=self.status_var, style="Status.TLabel").pack(side="right", padx=(12, 0))
        self.account_button = ttk.Button(actions, textvariable=self.account_label_var, command=self._show_account_menu, style="Ghost.TButton")
        self.account_button.pack(side="right", padx=(10, 0))
        self.workspace_button = ttk.Button(actions, text="Workspace", command=self._show_workspace_menu, style="Ghost.TButton")
        self.workspace_button.pack(side="right")

        transcript_shell = ttk.Frame(self.chat_view, padding=18, style="Surface.TFrame")
        transcript_shell.grid(row=1, column=1, sticky="nsew")
        transcript_shell.columnconfigure(0, weight=1)
        transcript_shell.rowconfigure(0, weight=1)

        self.message_canvas = tk.Canvas(
            transcript_shell,
            background="#17191d",
            highlightthickness=0,
            borderwidth=0,
        )
        self.message_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(transcript_shell, orient="vertical", command=self.message_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.message_canvas.configure(yscrollcommand=scrollbar.set)

        self.message_frame = ttk.Frame(self.message_canvas, style="Surface.TFrame")
        self.message_window = self.message_canvas.create_window((0, 0), window=self.message_frame, anchor="nw")
        self.message_frame.bind("<Configure>", self._sync_message_scrollregion)
        self.message_canvas.bind("<Configure>", self._resize_message_frame)

        composer = ttk.Frame(self.chat_view, padding=16, style="Composer.TFrame")
        composer.grid(row=2, column=1, sticky="ew", pady=(16, 0))
        composer.columnconfigure(0, weight=1)

        composer_body = ttk.Frame(composer, padding=14, style="ComposerBody.TFrame")
        composer_body.grid(row=0, column=0, sticky="ew")
        composer_body.columnconfigure(0, weight=1)

        self.command_input = tk.Text(
            composer_body,
            height=5,
            wrap="word",
            relief="flat",
            background="#1d2026",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=18,
            pady=18,
            font=("SF Pro Text", 14),
        )
        self.command_input.grid(row=0, column=0, sticky="ew")
        self.command_input.bind("<Return>", self._handle_text_return)
        self.command_input.bind("<Shift-Return>", lambda _event: None)

        footer = ttk.Frame(composer_body, style="ComposerBody.TFrame")
        footer.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            footer,
            text="Chat naturally, or ask Zeph to act on your computer.",
            style="ComposerHint.TLabel",
        ).pack(side="left")

        controls = ttk.Frame(footer, style="ComposerBody.TFrame")
        controls.pack(side="right")
        ttk.Checkbutton(controls, text="Dry run", variable=self.dry_run_var, style="Composer.TCheckbutton").pack(side="left", padx=(0, 10))
        ttk.Button(controls, text="Voice", command=self._listen_once, style="Secondary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Send", command=self._submit_command, style="Primary.TButton").pack(side="left")

    def _handle_text_return(self, event: tk.Event[Any]) -> str | None:
        if event.state & 0x0001:
            return None
        return self._submit_command()

    def _show_auth_view(self) -> None:
        self.chat_view.grid_remove()
        self.auth_view.grid()

    def _show_chat_view(self) -> None:
        self.auth_view.grid_remove()
        self.chat_view.grid()
        self._refresh_status()
        self._refresh_activity_content()
        self._load_conversations()
        if self.current_conversation_id is None:
            self._new_chat()
        else:
            self._render_conversation(self.current_conversation_id)

    def _handle_signup(self) -> None:
        display_name = self.signup_display_name_var.get().strip()
        username = self.signup_username_var.get().strip()
        password = self.signup_password_var.get()
        confirm_password = self.signup_confirm_password_var.get()

        if not self.signup_tos_var.get():
            messagebox.showerror("Acceptance required", "You need to accept the Terms of Service to create an account.")
            return
        if password != confirm_password:
            messagebox.showerror("Password mismatch", "The passwords do not match.")
            return
        try:
            preferred_wpm = int(self.signup_wpm_var.get().strip() or "80")
        except ValueError:
            messagebox.showerror("Invalid typing speed", "Preferred WPM must be a whole number.")
            return
        try:
            user = self.memory.create_user(username, display_name, password)
            self.memory.accept_tos(user.user_id, TOS_VERSION)
        except ValueError as exc:
            messagebox.showerror("Sign up failed", str(exc))
            return

        self.agent.update_config(
            {
                "user_name": user.display_name,
                "api_key": self.signup_api_key_var.get().strip(),
                "preferred_wpm": preferred_wpm,
                "wake_word": self.signup_wake_word_var.get().strip() or "Hey DAIA",
            }
        )
        self.current_user = user
        self._post_login_setup()
        self._append_message("system", f"Welcome, {user.display_name}. Your local Zeph account is ready.")

    def _handle_login(self) -> None:
        user = self.memory.authenticate_user(self.login_username_var.get(), self.login_password_var.get())
        if user is None:
            messagebox.showerror("Login failed", "That username and password combination was not recognized.")
            return
        self.current_user = user
        if not self.memory.has_tos_acceptance(user.user_id, TOS_VERSION):
            dialog = TermsDialog(self.root, self.tos_text)
            self.root.wait_window(dialog)
            if not dialog.result:
                self.current_user = None
                return
            self.memory.accept_tos(user.user_id, TOS_VERSION)
        self.agent.update_config({"user_name": user.display_name})
        self._post_login_setup()
        self._append_message("system", f"Signed in as {user.display_name}.")

    def _post_login_setup(self) -> None:
        if self.current_user is None:
            return
        self.account_label_var.set(self.current_user.display_name)
        self.subtitle_var.set(f"{self.agent.config.ai_model} ready for chat and desktop actions")
        self._show_chat_view()

    def _sign_out(self) -> None:
        self.current_user = None
        self.current_conversation_id = None
        self.conversations = []
        self.chat_title_var.set("New chat")
        self.account_label_var.set("Account")
        self.conversation_list.delete(0, "end")
        self._clear_messages()
        self.status_var.set("Signed out")
        self.subtitle_var.set("Your local desktop AI agent")
        self._show_auth_view()

    def _submit_command(self, _event: Any | None = None) -> str | None:
        if self.busy or self.current_user is None:
            return "break"
        command = self.command_input.get("1.0", "end").strip()
        if not command:
            return "break"
        if self.current_conversation_id is None:
            self._new_chat()
        rendered = f"dry run: {command}" if self.dry_run_var.get() else command
        self._append_message("user", rendered)
        if self.current_conversation_id is not None:
            self.memory.add_conversation_message(self.current_conversation_id, "user", rendered)
            self._refresh_conversation_title_from_command(rendered)
        self.command_input.delete("1.0", "end")
        self._set_busy(True, f"Running {command[:50]}")
        threading.Thread(target=self._execute_command, args=(rendered,), daemon=True).start()
        return "break"

    def _execute_command(self, command: str) -> None:
        try:
            result = self.agent.execute(command)
            self.event_queue.put(("result", {"result": result}))
        except Exception as exc:
            self.event_queue.put(("result", {"result": f"Unhandled failure: {exc}", "error": True}))

    def _listen_once(self) -> None:
        if self.busy or self.current_user is None:
            return
        self._set_busy(True, "Listening...")
        threading.Thread(target=self._capture_voice_once, daemon=True).start()

    def _capture_voice_once(self) -> None:
        try:
            command = self.agent.voice.listen_once()
            self.event_queue.put(("voice_result", {"command": command}))
        except Exception as exc:
            self.event_queue.put(("voice_result", {"error": str(exc)}))

    def _enqueue_agent_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.event_queue.put((event_type, payload))

    def _confirm_from_worker(self, prompt: str) -> bool:
        done = threading.Event()
        holder: dict[str, Any] = {"value": False}
        self.event_queue.put(("confirm_request", {"prompt": prompt, "done": done, "holder": holder}))
        done.wait()
        return bool(holder["value"])

    def _approve_plan_from_worker(self, steps: list[str]) -> bool:
        done = threading.Event()
        holder: dict[str, Any] = {"value": False}
        self.event_queue.put(("plan_request", {"steps": steps, "done": done, "holder": holder}))
        done.wait()
        return bool(holder["value"])

    def _drain_events(self) -> None:
        while not self.event_queue.empty():
            event_type, payload = self.event_queue.get_nowait()
            self._handle_event(event_type, payload)
        self.root.after(self.POLL_INTERVAL_MS, self._drain_events)

    def _handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "announce":
            self._append_message("agent", payload["text"])
            if self.current_conversation_id is not None:
                self.memory.add_conversation_message(self.current_conversation_id, "agent", payload["text"])
            return
        if event_type == "plan":
            plan_text = "\n".join(f"{idx}. {step}" for idx, step in enumerate(payload["steps"], start=1))
            self._append_message("plan", plan_text)
            if self.current_conversation_id is not None:
                self.memory.add_conversation_message(self.current_conversation_id, "plan", plan_text)
            return
        if event_type == "confirm_request":
            approved = messagebox.askyesno("Confirm action", f"I'm about to {payload['prompt']}.\n\nProceed?")
            payload["holder"]["value"] = approved
            payload["done"].set()
            return
        if event_type == "plan_request":
            dialog = PlanApprovalDialog(self.root, payload["steps"])
            self.root.wait_window(dialog)
            payload["holder"]["value"] = dialog.result
            payload["done"].set()
            return
        if event_type == "result":
            role = "error" if payload.get("error") else "agent"
            self._append_message(role, payload["result"])
            if self.current_conversation_id is not None:
                self.memory.add_conversation_message(self.current_conversation_id, role, payload["result"])
            self._set_busy(False, "Ready")
            self._refresh_activity_content()
            self._load_conversations(preserve_selection=True)
            return
        if event_type == "voice_result":
            if "error" in payload:
                self._append_message("error", f"Voice capture failed: {payload['error']}")
                self._set_busy(False, "Ready")
                return
            command = payload.get("command", "").strip()
            if not command:
                self._append_message("system", "I did not catch a spoken command.")
                self._set_busy(False, "Ready")
                return
            self.command_input.delete("1.0", "end")
            self.command_input.insert("1.0", command)
            self._append_message("system", f"Captured voice command: {command}")
            self._set_busy(False, "Ready")

    def _append_message(self, role: str, content: str) -> None:
        self.message_count += 1
        anchor = "e" if role == "user" else "w"
        outer = ttk.Frame(self.message_frame, style="Surface.TFrame")
        outer.pack(fill="x", pady=8)

        bubble_shell = ttk.Frame(outer, style="Surface.TFrame")
        bubble_shell.pack(anchor=anchor, fill="none")

        max_width = 860
        role_map = {
            "user": ("You", "#f8f9fb", "#2d3443"),
            "agent": ("Zeph", "#edf2f7", "#1d2026"),
            "system": ("System", "#d8f7be", "#243019"),
            "error": ("Error", "#ffe7ea", "#4a2329"),
            "plan": ("Plan", "#17140a", "#ecd19a"),
        }
        label, fg, bg = role_map.get(role, ("Zeph", "#ffffff", "#1b1f26"))

        title = tk.Label(
            bubble_shell,
            text=label,
            bg="#17191d",
            fg="#8f98a3",
            font=("SF Pro Text", 10, "bold"),
            anchor=anchor,
        )
        title.pack(anchor=anchor, padx=4, pady=(0, 5))

        bubble = tk.Label(
            bubble_shell,
            text=content,
            justify="left",
            wraplength=max_width,
            bg=bg,
            fg=fg,
            padx=18,
            pady=15,
            font=("SF Pro Text", 13),
        )
        bubble.pack(anchor=anchor)
        self.root.after_idle(lambda: self.message_canvas.yview_moveto(1.0))

    def _clear_messages(self) -> None:
        self.message_count = 0
        for child in self.message_frame.winfo_children():
            child.destroy()

    def _load_conversations(self, preserve_selection: bool = False) -> None:
        if self.current_user is None:
            return
        previous = self.current_conversation_id if preserve_selection else None
        self.conversations = self.memory.list_conversations(self.current_user.user_id)
        self.conversation_list.delete(0, "end")
        selected_index: int | None = None
        for idx, conversation in enumerate(self.conversations):
            self.conversation_list.insert("end", conversation.title)
            if previous is not None and conversation.conversation_id == previous:
                selected_index = idx
        if selected_index is not None:
            self.conversation_list.selection_set(selected_index)
            self.conversation_list.activate(selected_index)
        elif self.conversations and self.current_conversation_id is None:
            self.current_conversation_id = self.conversations[0].conversation_id
            self.conversation_list.selection_set(0)
            self.conversation_list.activate(0)
        self._refresh_conversation_header()

    def _new_chat(self) -> None:
        if self.current_user is None:
            return
        conversation = self.memory.create_conversation(self.current_user.user_id, "New chat")
        self.current_conversation_id = conversation.conversation_id
        self._load_conversations(preserve_selection=True)
        self._render_conversation(conversation.conversation_id)
        opener = "What can I help you with today?"
        self._append_message("agent", opener)
        self.memory.add_conversation_message(conversation.conversation_id, "agent", opener)
        self._load_conversations(preserve_selection=True)

    def _handle_conversation_select(self, _event: Any | None = None) -> None:
        selection = self.conversation_list.curselection()
        if not selection:
            return
        conversation = self.conversations[selection[0]]
        self.current_conversation_id = conversation.conversation_id
        self._render_conversation(conversation.conversation_id)

    def _render_conversation(self, conversation_id: int) -> None:
        self._clear_messages()
        for message in self.memory.list_conversation_messages(conversation_id):
            self._append_message(message.role, message.content)
        self._refresh_conversation_header()

    def _refresh_conversation_title_from_command(self, command: str) -> None:
        if self.current_conversation_id is None:
            return
        title = command.replace("\n", " ").strip()
        if title.lower().startswith("dry run:"):
            title = title.split(":", 1)[1].strip()
        title = title[:56] or "New chat"
        current = next((item for item in self.conversations if item.conversation_id == self.current_conversation_id), None)
        if current is None or current.title != "New chat":
            return
        self.memory.update_conversation_title(self.current_conversation_id, title)
        self._load_conversations(preserve_selection=True)
        self._refresh_conversation_header()

    def _delete_current_chat(self) -> None:
        if self.current_conversation_id is None:
            return
        if not messagebox.askyesno("Delete chat", "Delete this conversation?"):
            return
        self.memory.delete_conversation(self.current_conversation_id)
        self.current_conversation_id = None
        self._clear_messages()
        self._load_conversations()
        if self.conversations:
            first = self.conversations[0]
            self.current_conversation_id = first.conversation_id
            self._render_conversation(first.conversation_id)
        elif self.current_user is not None:
            self._new_chat()

    def _sync_message_scrollregion(self, _event: tk.Event[Any]) -> None:
        self.message_canvas.configure(scrollregion=self.message_canvas.bbox("all"))

    def _resize_message_frame(self, event: tk.Event[Any]) -> None:
        self.message_canvas.itemconfigure(self.message_window, width=event.width)

    def _set_command_text(self, text: str) -> None:
        self.command_input.delete("1.0", "end")
        self.command_input.insert("1.0", text)
        self.command_input.focus_set()

    def _refresh_status(self) -> None:
        if self.current_user is None:
            self.status_var.set("Not signed in")
            return
        self.status_var.set("Ready")
        self.account_label_var.set(self.current_user.display_name)
        self.subtitle_var.set(f"{self.agent.config.ai_model} ready for chat and desktop actions")
        self._refresh_conversation_header()

    def _refresh_conversation_header(self) -> None:
        if self.current_conversation_id is None:
            self.chat_title_var.set("New chat")
            return
        current = next((item for item in self.conversations if item.conversation_id == self.current_conversation_id), None)
        self.chat_title_var.set(current.title if current is not None else "New chat")

    def _refresh_activity_content(self) -> None:
        self.activity_rows = self.agent.memory.recent_tasks(limit=14)
        self.log_rows = self.agent.logger.recent_entries(120)

    def _open_activity_window(self) -> None:
        self._refresh_activity_content()
        window = tk.Toplevel(self.root)
        window.title("Activity")
        window.geometry("980x720")
        window.configure(bg="#101114")

        shell = ttk.Frame(window, padding=18, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=3)
        shell.columnconfigure(1, weight=2)
        shell.rowconfigure(0, weight=1)

        left = ttk.Frame(shell, padding=16, style="Surface.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Recent Tasks", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        tree = ttk.Treeview(left, columns=("created_at", "status", "task"), show="headings", style="App.Treeview")
        tree.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        for column, width in (("created_at", 140), ("status", 90), ("task", 420)):
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=width, anchor="w")
        for row in self.activity_rows:
            tree.insert("", "end", values=(str(row["created_at"])[:16].replace("T", " "), str(row["status"]).upper(), str(row["task"])))

        right = ttk.Frame(shell, padding=16, style="Surface.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Logs", style="CardTitle.TLabel").pack(anchor="w")
        logs = scrolledtext.ScrolledText(
            right,
            wrap="word",
            relief="flat",
            background="#1a1d23",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=14,
            pady=14,
            font=("SF Pro Text", 12),
        )
        logs.pack(fill="both", expand=True, pady=(12, 0))
        logs.insert("1.0", "\n".join(self.log_rows) or "No log entries yet.")
        logs.configure(state="disabled")

    def _open_automations_window(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Automations")
        window.geometry("960x700")
        window.configure(bg="#101114")

        shell = ttk.Frame(window, padding=18, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        top = ttk.Frame(shell, padding=16, style="Surface.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Automations", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="Write a recurring instruction in plain English.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))
        entry = ttk.Entry(top, textvariable=self.schedule_entry_var)
        entry.grid(row=2, column=0, sticky="ew")
        ttk.Button(top, text="Create", command=lambda: [self._create_schedule(), window.lift()], style="Primary.TButton").grid(row=2, column=1, padx=(10, 0))

        body = ttk.Frame(shell, padding=16, style="Surface.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        tree = ttk.Treeview(body, columns=("task_id", "status", "command"), show="headings", style="App.Treeview")
        tree.grid(row=0, column=0, sticky="nsew")
        for column, width in (("task_id", 160), ("status", 90), ("command", 560)):
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=width, anchor="w")
        for task in self.agent.scheduler.list_tasks():
            tree.insert("", "end", values=(task.task_id, "active" if task.active else "paused", task.natural_language))

        actions = ttk.Frame(body, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Pause", command=lambda: self._mutate_schedule_from_tree(tree, "pause"), style="Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Resume", command=lambda: self._mutate_schedule_from_tree(tree, "resume"), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Delete", command=lambda: self._mutate_schedule_from_tree(tree, "delete"), style="Primary.TButton").pack(side="left", padx=(8, 0))

    def _mutate_schedule_from_tree(self, tree: ttk.Treeview, action: str) -> None:
        selection = tree.selection()
        if not selection:
            return
        task_id = tree.item(selection[0], "values")[0]
        if action == "pause":
            self.agent.scheduler.pause_task(task_id)
            self._append_message("system", f"Paused schedule {task_id}.")
        elif action == "resume":
            self.agent.scheduler.resume_task(task_id)
            self._append_message("system", f"Resumed schedule {task_id}.")
        elif action == "delete":
            if not messagebox.askyesno("Delete schedule", f"Delete scheduled task {task_id}?"):
                return
            self.agent.scheduler.delete_task(task_id)
            self._append_message("system", f"Deleted schedule {task_id}.")
        self._refresh_activity_content()

    def _open_settings_window(self) -> None:
        config = self.agent.config
        vars_map = {
            "user_name": tk.StringVar(value=config.user_name),
            "ai_provider": tk.StringVar(value=config.ai_provider),
            "ai_model": tk.StringVar(value=config.ai_model),
            "browser_mode": tk.StringVar(value=config.browser_mode),
            "api_key": tk.StringVar(value=config.api_key),
            "preferred_wpm": tk.StringVar(value=str(config.preferred_wpm)),
            "wake_word": tk.StringVar(value=config.wake_word),
            "voice_rate": tk.StringVar(value=str(config.voice_rate)),
            "voice_language": tk.StringVar(value=config.voice_language),
            "speed_mode": tk.StringVar(value=config.speed_mode),
            "clipboard_history_limit": tk.StringVar(value=str(config.clipboard_history_limit)),
        }
        confirm_vars = {
            "delete_file": tk.BooleanVar(value=config.confirm.delete_file),
            "kill_process": tk.BooleanVar(value=config.confirm.kill_process),
            "submit_form": tk.BooleanVar(value=config.confirm.submit_form),
            "close_window": tk.BooleanVar(value=config.confirm.close_window),
            "browser_navigation": tk.BooleanVar(value=config.confirm.browser_navigation),
            "script_execution": tk.BooleanVar(value=config.confirm.script_execution),
        }

        window = tk.Toplevel(self.root)
        window.title("Settings")
        window.geometry("760x760")
        window.configure(bg="#101114")

        shell = ttk.Frame(window, padding=18, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)

        fields = [
            ("Display name", "user_name"),
            ("Provider", "ai_provider"),
            ("Model", "ai_model"),
            ("Browser mode", "browser_mode"),
            ("API key", "api_key"),
            ("Typing WPM", "preferred_wpm"),
            ("Wake word", "wake_word"),
            ("Voice rate", "voice_rate"),
            ("Voice language", "voice_language"),
            ("Speed mode", "speed_mode"),
            ("Clipboard limit", "clipboard_history_limit"),
        ]
        ttk.Label(shell, text="Settings", style="HeroTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        for idx, (label, key) in enumerate(fields, start=1):
            ttk.Label(shell, text=label, style="FieldLabel.TLabel").grid(row=idx, column=0, sticky="w", padx=(0, 16), pady=8)
            if key == "speed_mode":
                widget = ttk.Combobox(shell, textvariable=vars_map[key], values=list(ZephAgent.SPEED_MAP.keys()), state="readonly")
            elif key == "browser_mode":
                widget = ttk.Combobox(shell, textvariable=vars_map[key], values=["default", "playwright"], state="readonly")
            elif key == "ai_provider":
                widget = ttk.Combobox(shell, textvariable=vars_map[key], values=["anthropic", "openai"], state="readonly")
            else:
                widget = ttk.Entry(shell, textvariable=vars_map[key], show="*" if key == "api_key" else "")
            widget.grid(row=idx, column=1, sticky="ew", pady=8)

        confirm_shell = ttk.Frame(shell, padding=14, style="Surface.TFrame")
        confirm_shell.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(confirm_shell, text="Safety confirmations", style="CardTitle.TLabel").pack(anchor="w")
        for key, var in confirm_vars.items():
            ttk.Checkbutton(confirm_shell, text=key.replace("_", " ").title(), variable=var).pack(anchor="w", pady=4)

        def save() -> None:
            try:
                updates = {
                    "user_name": vars_map["user_name"].get().strip(),
                    "ai_provider": vars_map["ai_provider"].get().strip() or "anthropic",
                    "ai_model": vars_map["ai_model"].get().strip() or "claude-sonnet-4-20250514",
                    "browser_mode": vars_map["browser_mode"].get().strip() or "default",
                    "api_key": vars_map["api_key"].get().strip(),
                    "preferred_wpm": int(vars_map["preferred_wpm"].get().strip() or "80"),
                    "wake_word": vars_map["wake_word"].get().strip() or "Hey DAIA",
                    "voice_rate": int(vars_map["voice_rate"].get().strip() or "180"),
                    "voice_language": vars_map["voice_language"].get().strip() or "en-US",
                    "clipboard_history_limit": int(vars_map["clipboard_history_limit"].get().strip() or "20"),
                    "speed_mode": vars_map["speed_mode"].get().strip() or "normal",
                    "confirm": {name: var.get() for name, var in confirm_vars.items()},
                }
            except ValueError as exc:
                messagebox.showerror("Invalid settings", str(exc))
                return
            updates["speed_multiplier"] = ZephAgent.SPEED_MAP.get(updates["speed_mode"], 1.0)
            self.agent.update_config(updates)
            if self.current_user is not None and updates["user_name"]:
                self.subtitle_var.set(f"Signed in as {updates['user_name']} · {self.agent.config.ai_model}")
            self._append_message("system", "Settings saved.")
            window.destroy()

        actions = ttk.Frame(shell, style="App.TFrame")
        actions.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text="Close", command=window.destroy, style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Save", command=save, style="Primary.TButton").pack(side="right", padx=(0, 10))

    def _open_text_window(self, title: str, content: str) -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("800x680")
        window.configure(bg="#101114")

        shell = ttk.Frame(window, padding=18, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        text = scrolledtext.ScrolledText(
            shell,
            wrap="word",
            relief="flat",
            background="#15171c",
            foreground="#edf1f5",
            insertbackground="#edf1f5",
            padx=18,
            pady=18,
            font=("SF Pro Text", 12),
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")

    def _create_schedule(self) -> None:
        command = self.schedule_entry_var.get().strip()
        if not command:
            return
        self._set_command_text(command)
        self._submit_command()
        self.schedule_entry_var.set("")

    def _set_busy(self, busy: bool, label: str) -> None:
        self.busy = busy
        self.status_var.set(label)

    def _show_workspace_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False, bg="#1d2026", fg="#edf2f7", activebackground="#2d3443", activeforeground="#ffffff")
        menu.add_command(label="User Guide", command=lambda: self._open_text_window("User Guide", self.guide_text))
        menu.add_command(label="Terms of Service", command=lambda: self._open_text_window("Terms of Service", self.tos_text))
        menu.add_command(label="Automations", command=self._open_automations_window)
        menu.add_command(label="Activity", command=self._open_activity_window)
        menu.add_command(label="Settings", command=self._open_settings_window)
        menu.add_separator()
        menu.add_command(label="Open Data Folder", command=self._open_data_folder)
        x = self.workspace_button.winfo_rootx()
        y = self.workspace_button.winfo_rooty() + self.workspace_button.winfo_height()
        menu.tk_popup(x, y)
        menu.grab_release()

    def _show_account_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False, bg="#1d2026", fg="#edf2f7", activebackground="#2d3443", activeforeground="#ffffff")
        menu.add_command(label="Settings", command=self._open_settings_window)
        menu.add_separator()
        menu.add_command(label="Sign Out", command=self._sign_out)
        x = self.account_button.winfo_rootx()
        y = self.account_button.winfo_rooty() + self.account_button.winfo_height()
        menu.tk_popup(x, y)
        menu.grab_release()

    def _open_data_folder(self) -> None:
        self.agent.files.open_default(APP_DIR)

    def _on_close(self) -> None:
        try:
            self.agent.browser.close()
        except Exception:
            pass
        try:
            self.agent.scheduler.stop()
        except Exception:
            pass
        self.root.destroy()


def launch_gui() -> int:
    """Launch the React-powered Zeph desktop app."""

    from daia.webui import launch_gui as launch_web_ui

    return launch_web_ui()
