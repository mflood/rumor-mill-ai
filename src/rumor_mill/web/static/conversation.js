(() => {
  const room = document.querySelector(".radio-room");
  if (!room) return;
  const id = room.dataset.conversationId;
  const characterName = room.dataset.characterName || "Reply";
  const list = document.querySelector("#messages");
  const form = document.querySelector("#composer");
  const input = document.querySelector("#message");
  const submit = form.querySelector('button[type="submit"]');
  const status = document.querySelector("#line-status");
  const count = document.querySelector("#count");
  const suggestions = document.querySelector("#suggested-questions");
  let isSubmitting = false;
  let pendingSubmission = null;

  const hideSuggestions = () => { if (suggestions) suggestions.hidden = true; };
  suggestions?.querySelectorAll("[data-suggested-question]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.textContent;
      count.textContent = `${input.value.length} / 4000`;
      hideSuggestions();
      input.focus();
    });
  });

  const setSubmitting = (submitting) => {
    isSubmitting = submitting;
    input.disabled = submitting;
    submit.disabled = submitting;
    form.setAttribute("aria-busy", String(submitting));
  };

  const render = (message) => {
    const item = document.createElement("li");
    item.className = `signal-message signal-message--${message.role} signal-message--${message.kind}`;
    const label = message.kind === "action" ? "Action" : message.kind === "refusal" ? "Boundary" : message.role === "visitor" ? "You" : characterName;
    item.innerHTML = `<span>${label}</span><p></p>`;
    item.querySelector("p").textContent = message.content;
    if (message.id) {
      const report = document.createElement("a");
      report.className = "report-signal";
      report.textContent = "Flag this message";
      report.href = `/lighthouse/runs/${room.dataset.runId}/report?target_kind=message&target_id=${message.id}&conversation_id=${id}`;
      item.append(report);
    }
    list.append(item);
    return item;
  };

  const load = async () => {
    const response = await fetch(`/api/v1/conversations/${id}`, { credentials: "same-origin" });
    if (!response.ok) { status.textContent = "This private conversation is no longer available."; return; }
    const conversation = await response.json();
    list.replaceChildren();
    room.dataset.runId = conversation.run_id;
    conversation.messages.forEach(render);
    list.lastElementChild?.scrollIntoView({ block: "end" });
    if (conversation.messages.length > 0) hideSuggestions();
  };

  input.addEventListener("input", () => { count.textContent = `${input.value.length} / 4000`; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content || isSubmitting) return;
    hideSuggestions();
    if (!pendingSubmission || pendingSubmission.content !== content) {
      pendingSubmission = { content, clientMessageId: crypto.randomUUID() };
    }
    const { clientMessageId } = pendingSubmission;
    setSubmitting(true);
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
      pendingSubmission = null;
      status.textContent = "Reply received.";
      await load();
    } catch (_) {
      status.textContent = "The line went quiet. Your message was not committed; try again.";
    } finally { setSubmitting(false); input.focus(); }
  });
  load();
})();
