(() => {
  const room = document.querySelector(".report-room");
  if (!room) return;
  const form = document.querySelector("#report-form");
  const status = document.querySelector("#report-status");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const category = new FormData(form).get("category");
    if (!category) return;
    const button = form.querySelector("button");
    button.disabled = true;
    status.textContent = "Sending your signal…";
    const payload = {
      target_kind: room.dataset.targetKind,
      target_id: room.dataset.targetId,
      category,
      note: document.querySelector("#note").value.trim() || null,
      conversation_id: room.dataset.conversationId || null,
      artifact_id: room.dataset.artifactId || null
    };
    try {
      const response = await fetch(`/api/v1/runs/${room.dataset.runId}/reports`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error();
      const report = await response.json();
      document.querySelector("#report-id").textContent = report.id;
      form.hidden = true;
      document.querySelector("#report-receipt").hidden = false;
      status.textContent = "";
    } catch (_) {
      status.textContent = "The signal did not leave the tower. Please try again.";
      button.disabled = false;
    }
  });
})();
