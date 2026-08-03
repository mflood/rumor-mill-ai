(() => {
  const disclosure = document.querySelector("[data-reset-disclosure]");
  const cancel = document.querySelector("[data-reset-cancel]");

  cancel?.addEventListener("click", () => {
    disclosure?.removeAttribute("open");
    disclosure?.querySelector("summary")?.focus();
  });

  document.querySelectorAll("[data-reset-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const submit = form.querySelector("[data-reset-submit]");
      const status = document.querySelector("[data-reset-status]");
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Erasing visit data…";
      }
      if (cancel) cancel.disabled = true;
      if (status) status.textContent = "Erasing your private visitor ledger. Keep this page open.";
    });
  });
})();
