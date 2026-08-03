(() => {
  const countdown = document.querySelector('[data-dispatch-status][data-state="scheduled"]');
  if (!countdown) return;

  const copy = countdown.querySelector("[data-dispatch-copy]");
  const simulationTime = Date.parse(countdown.dataset.simulationTime);
  const targetTime = Date.parse(countdown.dataset.targetTime);
  const clockRate = Number(countdown.dataset.clockRate);
  if (!copy || !Number.isFinite(simulationTime) || !Number.isFinite(targetTime) ||
      !Number.isFinite(clockRate) || clockRate <= 0) return;

  const loadedAt = performance.now();
  const update = () => {
    const elapsedSimulationMs = (performance.now() - loadedAt) * clockRate;
    const remainingSeconds = Math.ceil(
      (targetTime - simulationTime - elapsedSimulationMs) / 1_000,
    );
    if (remainingSeconds <= 0) {
      countdown.dataset.state = "overdue";
      copy.textContent = "The next town dispatch is due now; reload for the latest state.";
      return;
    }

    const hours = Math.floor(remainingSeconds / 3_600);
    const minutes = Math.floor((remainingSeconds % 3_600) / 60);
    const seconds = remainingSeconds % 60;
    const parts = [];
    if (hours) parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
    if (minutes) parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
    if (!hours) parts.push(`${seconds} ${seconds === 1 ? "second" : "seconds"}`);
    copy.textContent = `Next town dispatch in ${parts.join(" ")}`;
  };

  update();
  window.setInterval(update, 1_000);
})();
