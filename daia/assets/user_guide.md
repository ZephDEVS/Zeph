# Zeph User Guide

## What Zeph Is
Zeph is a local desktop AI agent that can read the screen, control apps, automate routine tasks, and help you work from a chat-style interface.

## The Main Chat
- Type a command in the composer at the bottom and press `Run`.
- Use `Dry Run` to preview what Zeph would do without taking action.
- Zeph will announce important actions before it performs them.

## Good Starter Commands
- `what windows do I have open right now?`
- `take a screenshot of my screen and tell me what you see`
- `clipboard history`
- `list processes`
- `open Calendar`
- `every Monday at 9am, open Calendar`

## Plans And Safety
- For complex requests, Zeph can show a step-by-step plan before proceeding.
- Destructive actions may require confirmation depending on your safety settings.
- You can tune confirmations in the Settings panel.

## Voice
- Use `Listen Once` to capture a single spoken command.
- Voice mode depends on microphone permissions and local speech libraries.

## Schedules
- Use natural language schedules such as `every day at 8am, open Calendar`.
- Manage active schedules from the Automations panel.

## Logs
- Zeph records activity in `~/.daia/activity.log`.
- Export a readable report from the Logs panel.

## Local Accounts
- Sign up and log in locally on this device.
- Accounts are stored in Zeph's local SQLite database.
- Passwords are hashed before storage.

## Permissions You May Need
- Accessibility
- Screen Recording
- Microphone
- Input Monitoring

If a feature fails, check macOS Privacy & Security settings first.
