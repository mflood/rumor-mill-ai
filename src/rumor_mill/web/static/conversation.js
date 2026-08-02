(() => {
  const room = document.querySelector(".radio-room");
  if (!room) return;
  const id = room.dataset.conversationId;
  const list = document.querySelector("#messages");
  const form = document.querySelector("#composer");
  const input = document.querySelector("#message");
  const status = document.querySelector("#line-status");
  const count = document.querySelector("#count");

  const render = (message) => {
    const item = document.createElement("li");
    item.className = `signal-message signal-message--${message.role} signal-message--${message.kind}`;
    const label = message.kind === "action" ? "Action" : message.kind === "refusal" ? "Boundary" : message.kind === "hesitation" ? "Hesitation" : message.role === "visitor" ? "You" : "Reply";
    item.innerHTML = `<span>${label}</span><p></p>`;
    item.querySelector("p").textContent = message.content;
    list.append(item);
    return item;
  };

  const load = async () => {
    const response = await fetch(`/api/v1/conversations/${id}`, { credentials: "same-origin" });
    if (!response.ok) { status.textContent = "This private line is no longer available."; return; }
    const conversation = await response.json();
    list.replaceChildren();
    conversation.messages.forEach(render);
    list.lastElementChild?.scrollIntoView({ block: "end" });
  };

  input.addEventListener("input", () => { count.textContent = `${input.value.length} / 4000`; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    const clientMessageId = crypto.randomUUID();
    input.disabled = true;
    status.textContent = "The signal is carrying your words…";
    try {
      const response = await fetch(`/api/v1/conversations/${id}/messages/stream`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, client_message_id: clientMessageId })
      });
      if (!response.ok) {
        const detail = (await response.json()).detail;
        status.textContent = detail || "The line went quiet. Your message was not committed; try again.";
        return;
      }
      render({ role: "visitor", kind: "speech", content });
      let reply = null;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop();
        frames.forEach((frame) => {
          const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine) return;
          const data = JSON.parse(dataLine.slice(6));
          if (data.event === "action") render({ role: "character", kind: "action", content: data.content });
          if (data.event === "reply_delta") {
            reply ||= render({ role: "character", kind: "hesitation", content: "" });
            reply.querySelector("p").textContent += data.delta;
          }
          if (data.event === "completed" && reply) reply.className = `signal-message signal-message--character signal-message--${data.stance === "refuse" ? "refusal" : data.stance === "uncertain" ? "hesitation" : "speech"}`;
        });
      }
      input.value = ""; count.textContent = "0 / 4000";
      status.textContent = "Reply received.";
      await load();
    } catch (_) {
      status.textContent = "The line went quiet. Your message was not committed; try again.";
    } finally { input.disabled = false; input.focus(); }
  });
  load();
})();
