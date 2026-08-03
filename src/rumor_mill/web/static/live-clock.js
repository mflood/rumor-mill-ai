(() => {
  const clock = document.querySelector("[data-live-clock]");
  if (!clock) return;

  const parseState = (source) => {
    const state = {
      simulationTime: Date.parse(source.simulationTime),
      wallTimeAnchor: Date.parse(source.wallTimeAnchor),
      serverTime: Date.parse(source.serverTime),
      startDate: Date.parse(`${source.startDate}T00:00:00Z`),
      clockRate: Number(source.clockRate),
      tickSeconds: Number(source.tickSeconds),
      maxCatchUpTicks: Number(source.maxCatchUpTicks),
      clockRuns: source.runStatus === "running" && source.clockMode === "wall",
      loadedAt: performance.now(),
    };
    return Object.values(state).every((value) =>
      typeof value === "boolean" || Number.isFinite(value),
    ) && state.clockRate > 0 && state.tickSeconds > 0 && state.maxCatchUpTicks > 0
      ? state
      : null;
  };

  let state = parseState(clock.dataset);
  if (!state) return;

  const update = () => {
    let ticks = 0;
    if (state.clockRuns) {
      const elapsedWallSeconds = Math.max(
        0,
        (state.serverTime - state.wallTimeAnchor + performance.now() - state.loadedAt) / 1_000,
      );
      ticks = Math.min(
        Math.floor((elapsedWallSeconds * state.clockRate) / state.tickSeconds),
        state.maxCatchUpTicks,
      );
    }

    const current = new Date(state.simulationTime + ticks * state.tickSeconds * 1_000);
    const currentDate = Date.UTC(
      current.getUTCFullYear(),
      current.getUTCMonth(),
      current.getUTCDate(),
    );
    const day = Math.max(
      1,
      Math.min(14, Math.floor((currentDate - state.startDate) / 86_400_000) + 1),
    );
    const hours = String(current.getUTCHours()).padStart(2, "0");
    const minutes = String(current.getUTCMinutes()).padStart(2, "0");
    const label = `Day ${day} · ${hours}:${minutes}`;
    if (clock.textContent !== label) clock.textContent = label;
  };

  update();
  window.setInterval(update, 1_000);
  window.setInterval(async () => {
    try {
      const response = await fetch(clock.dataset.clockUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const refreshed = parseState(await response.json());
      if (refreshed) {
        state = refreshed;
        update();
      }
    } catch (_) {
      // Keep projecting the last valid state during a transient network failure.
    }
  }, 15_000);
})();
