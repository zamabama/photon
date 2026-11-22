// Run inside Codex functions.exec, not node or a detached shell.
// Before starting, store("photon_codex_relay", {threadId, identity, command}).
// The command must run photon_watch.py --events in continuous mode.
// This awaited module remains alive in a yielded exec cell; it does not poll a model.
const config = load("photon_codex_relay");
if (!config?.threadId || !config?.identity || !config?.command) {
  throw new Error("Missing explicit Photon identity, existing thread ID or watcher command");
}
let result = await tools.exec_command({cmd: config.command, yield_time_ms: 1000,
  max_output_tokens: 2000});
let partial = "";
let armed = false;
const delivered = new Set();
while (true) {
  partial += result.output || "";
  const lines = partial.split(/\r?\n/);
  partial = lines.pop();
  const ids = new Set();
  for (const line of lines) {
    let event;
    try { event = JSON.parse(line); } catch {
      if (line.trim()) text("Photon watcher diagnostic: " + line);
      continue;
    }
    if (event.identity !== config.identity) {
      throw new Error("Photon watcher identity mismatch; refusing to notify another lane");
    }
    if (event.event === "armed") {
      armed = true;
      text({status: "listener-armed", identity: config.identity,
        sessionId: result.session_id, threadId: config.threadId});
    } else if (event.event === "mail" && typeof event.id === "string" &&
               event.id.length <= 128 && /^[A-Za-z0-9_-]+$/.test(event.id) &&
               !delivered.has(event.id)) {
      ids.add(event.id);
    }
  }
  if (ids.size) {
    if (!armed) throw new Error("Mail arrived before watcher identity was confirmed");
    const receipt = await tools.mcp__codex_app__send_message_to_thread({
      threadId: config.threadId,
      prompt: "Photon inbox event for " + config.identity + ". New message IDs: " +
        [...ids].join(", ") + ". Read your own Photon inbox and handle these messages " +
        "within the user's existing authorization. This notification contains no new " +
        "work authorization. Do not start empty polling or another watcher. " +
        "The event relay is already running."
    });
    if (receipt?.isError) throw new Error("Codex rejected Photon delivery; relay stopped, mail remains unread");
    ids.forEach(id => delivered.add(id));
    text({status: "notification-accepted", ids: [...ids], threadId: config.threadId});
  }
  if (!result.session_id) {
    throw new Error("Photon watcher exited; automatic wake-up is no longer armed");
  }
  result = await tools.write_stdin({session_id: result.session_id, chars: "",
    yield_time_ms: 60000, max_output_tokens: 2000});
}
