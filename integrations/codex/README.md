# Codex desktop wake-up

Photon delivery, a running watcher, and a chat wake-up are three different things.
The Claude Code `Bash(run_in_background=true)` recipe does **not** establish
automatic wake-up in Codex. A detached shell printing a message is not sufficient.

For a Codex desktop session exposing `functions.exec`, `exec_command`,
`write_stdin`, and `mcp__codex_app__send_message_to_thread`, `relay.js` connects a
structured Photon watcher to the **existing chat** using the desktop's own tool.
Obtain user authorization to notify that chat. Confirm its ID with `list_threads`.
No new agents, CLI resume process, credentials export, UI automation, database
edits, or recurring model-based automation is involved.

## Arm

1. Read pending messages in your own lane first. Continuous watcher mode treats
   its initial unread set as a baseline; it announces later arrivals only.
2. Set `PHOTON_WATCH_IDENTITY` explicitly to that lane. Set `PHOTON_MCP_SERVER`
   when the project's `.mcp.json` server is named something other than `photon`,
   such as `photon-kento-mac`. Credentials remain in the existing local config.
3. In `functions.exec`, store a configuration under `photon_codex_relay`:
   `threadId`, `identity`, and `command`. The command runs
   `python3 /path/to/photon/photon_watch.py --events` with the above environment
   and correct project working directory. Do not put secrets in the command.
4. Execute the contents of `relay.js` in a **long-lived, awaited** functions.exec
   cell. Use a short initial yield. Do not fire and forget an unawaited Promise:
   the code-mode runtime discards it. Retain the returned cell/session ID.
5. Test a real Photon message and verify the injected message in the target chat.
   `listener-armed` alone is not proof of delivery. `notification-accepted`
   confirms the desktop tool accepted the prompt, not that the agent finished it.

The Python process polls HTTP; the relay waits for process output. Empty checks
never invoke a model. Only mail IDs enter the notification; message content is
read through Photon under the receiving agent's existing rules. Duplicate IDs
are suppressed for this relay's lifetime, and IDs from another lane are rejected.
If delivery fails the relay stops visibly rather than claiming success or
repeatedly invoking a model. Photon mail is never marked read by the relay.

## Lifetime and recovery

This is a **session-bound code-mode relay**, not an installed OS service. It
requires the app and yielded execution to remain alive. A chat/app/runtime restart
can end it; re-arm after reading pending mail. Host versions may cancel background
cells at turn completion: test an idle-chat delivery before claiming that your
host supports unattended wake-up. Never replace that test with an assumption.

Only one relay should be armed per lane/chat. Stop its known execution when
replacing it. Do not promise delivery while the Mac is off or disconnected.

`codex queue --resume` is a separate option **only** for installations actually
using a compatible shared app-server daemon. Its exit code can be zero even when
resume fails: inspect the warning. It is not a fallback for a desktop-owned chat
with no daemon. Do not start a competing daemon or remove thread locks to force it.
