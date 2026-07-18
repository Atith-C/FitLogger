/* Manual workout-plan editor.
 *
 * Lets the user add and remove days and exercises. On submit, every field name
 * is re-indexed contiguously (day_0_name, day_0_ex_0_name, ...) so the server
 * can rebuild the plan structure cleanly regardless of what was added/removed.
 *
 * Editing existing values works without JS (names are rendered server-side);
 * this file adds the add/remove capability.
 */

(function () {
  "use strict";

  const form = document.getElementById("plan-editor");
  if (!form) {
    return;
  }

  const daysContainer = document.getElementById("days");
  const exTemplate = document.getElementById("ex-template");
  const dayTemplate = document.getElementById("day-template");

  function addExercise(dayEl) {
    const row = exTemplate.content.firstElementChild.cloneNode(true);
    dayEl.querySelector("[data-exercises]").appendChild(row);
  }

  function renumberDayLabels() {
    daysContainer.querySelectorAll("[data-day]").forEach(function (dayEl, i) {
      const label = dayEl.querySelector(".fl-day-label");
      if (label) {
        label.textContent = "Day " + (i + 1);
      }
    });
  }

  // Event delegation: one listener handles every add/remove button, including
  // those inside days added after page load.
  form.addEventListener("click", function (event) {
    const target = event.target;

    if (target.matches("[data-add-ex]")) {
      addExercise(target.closest("[data-day]"));
    } else if (target.matches("[data-remove-ex]")) {
      target.closest("[data-ex]").remove();
    } else if (target.matches("[data-remove-day]")) {
      target.closest("[data-day]").remove();
      renumberDayLabels();
    }
  });

  const addDayButton = document.getElementById("add-day");
  if (addDayButton) {
    addDayButton.addEventListener("click", function () {
      const dayEl = dayTemplate.content.firstElementChild.cloneNode(true);
      addExercise(dayEl); // start each new day with one exercise row
      daysContainer.appendChild(dayEl);
      renumberDayLabels();
    });
  }

  // Re-index every field name so indices are contiguous, whatever was
  // added/removed. This runs before the form actually submits.
  form.addEventListener("submit", function () {
    daysContainer.querySelectorAll("[data-day]").forEach(function (dayEl, di) {
      dayEl.querySelectorAll("[data-field]").forEach(function (input) {
        const field = input.dataset.field;
        if (field === "day_name" || field === "day_focus") {
          input.name = "day_" + di + "_" + field.replace("day_", "");
        }
      });

      dayEl.querySelectorAll("[data-ex]").forEach(function (exEl, ei) {
        exEl.querySelectorAll("[data-field]").forEach(function (input) {
          const field = input.dataset.field; // ex_name, ex_sets, ex_reps, ex_notes
          const suffix = field.replace("ex_", "");
          const key = suffix === "sets" ? "sets" : suffix === "reps" ? "reps" : suffix === "notes" ? "notes" : "name";
          input.name = "day_" + di + "_ex_" + ei + "_" + key;
        });
      });
    });
  });
})();
