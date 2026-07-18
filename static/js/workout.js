/* Active workout screen.
 *
 * Progressive enhancement only: every action here also works without
 * JavaScript via a normal form submit. Nothing essential depends on this file.
 */

(function () {
  "use strict";

  // Selecting an exercise loads its previous performance immediately, instead
  // of making the user press Go.
  const picker = document.getElementById("exercise-picker");
  const select = document.getElementById("exercise-select");
  const goButton = document.getElementById("exercise-go");

  if (picker && select) {
    select.addEventListener("change", function () {
      // requestSubmit(), not submit(): submit() deliberately fires no submit
      // event, so nav.js would never show its progress bar and changing
      // exercise would look like nothing happened until the page swapped.
      if (typeof picker.requestSubmit === "function") {
        picker.requestSubmit();
      } else {
        picker.submit();
      }
    });

    // The Go button is the no-JS fallback; with JS on it is redundant.
    if (goButton) {
      goButton.hidden = true;
    }
  }

  // Weight and rep steppers. Tapping +/- beats typing on a phone mid-set.
  document.querySelectorAll(".fl-step-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      const input = document.getElementById(button.dataset.stepTarget);
      if (!input) {
        return;
      }

      const step = parseFloat(button.dataset.step);
      const min = button.dataset.min !== undefined ? parseFloat(button.dataset.min) : 0;

      const current = parseFloat(input.value);
      const base = isNaN(current) ? 0 : current;

      let next = base + step;
      if (next < min) {
        next = min;
      }

      // Avoid 62.50000000000001 from floating-point drift.
      input.value = Number.isInteger(next) ? next : parseFloat(next.toFixed(2));
    });
  });

  // Prevent a double-tap on Save from logging the same set twice.
  const setForm = document.getElementById("set-form");
  if (setForm) {
    const saveButton = setForm.querySelector('button[type="submit"]');
    const saveLabel = saveButton ? saveButton.textContent : "";

    setForm.addEventListener("submit", function () {
      if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "Saving…";
      }
    });

    // Pressing Back restores this page from the bfcache exactly as it was left:
    // Save greyed out and still reading "Saving…", with no way to log another
    // set short of a manual reload. Put it back.
    window.addEventListener("pageshow", function () {
      if (saveButton) {
        saveButton.disabled = false;
        saveButton.textContent = saveLabel;
      }
    });
  }
})();
