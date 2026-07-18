/* Progress charts.
 *
 * Every number here was calculated in Python (analytics/services.py). This file
 * only renders what the server sent — it does no maths of its own.
 */

(function () {
  "use strict";

  const dataElement = document.getElementById("chart-data");
  if (!dataElement) {
    return;
  }

  // If Plotly never arrives (CDN blocked, offline), the chart containers would
  // stay empty. Say what happened instead of leaving blank boxes.
  if (typeof Plotly === "undefined") {
    document.querySelectorAll(".fl-chart").forEach(function (el) {
      el.innerHTML =
        '<p class="text-secondary small mb-0 py-4 text-center">' +
        "Charts could not be loaded. Your data is safe — try a refresh.</p>";
    });
    return;
  }

  const charts = JSON.parse(dataElement.textContent);
  const exerciseNameEl = document.getElementById("exercise-name");
  const exerciseName = exerciseNameEl ? JSON.parse(exerciseNameEl.textContent) : "";

  // Match the app's "Aurora Athletic" dark theme.
  const GRID = "rgba(190,242,172,0.10)";
  const LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Sora, ui-sans-serif, system-ui, sans-serif", color: "#9db0a8", size: 12 },
    margin: { l: 52, r: 16, t: 8, b: 36 },
    showlegend: false,
    height: 240,
    hoverlabel: {
      bgcolor: "#0b110f",
      bordercolor: "rgba(190,242,172,0.25)",
      font: { family: "Sora, sans-serif", color: "#ecf5f0" },
    },
  };

  // Dates on the x-axis, always. Without type:"date" Plotly treats a lone point
  // as a bare number and invents millisecond ticks (23:59:59.999).
  const DATE_AXIS = {
    type: "date",
    tickformat: "%d %b",
    gridcolor: GRID,
    zerolinecolor: GRID,
    linecolor: GRID,
  };

  const VALUE_AXIS = {
    gridcolor: GRID,
    zerolinecolor: GRID,
    automargin: true,
  };

  const CONFIG = { displayModeBar: false, responsive: true };
  const ACCENT = "#22c55e";
  const LIME = "#a3e635";
  const FILL = "rgba(34,197,94,0.12)";
  const DAY_MS = 24 * 60 * 60 * 1000;

  function emptyMessage(element, text) {
    element.innerHTML =
      '<p class="text-secondary small mb-0 py-4 text-center">' + text + "</p>";
  }

  function renderLine(elementId, series, unit) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }

    // Never draw an empty or broken chart — say so in words instead.
    if (!series || series.length === 0) {
      emptyMessage(element, "Not enough data yet.");
      return;
    }

    const values = series.map((point) => point.value);

    const trace = {
      x: series.map((point) => point.date),
      y: values,
      type: "scatter",
      mode: "lines+markers",
      line: { color: ACCENT, width: 2.5, shape: "spline", smoothing: 0.6 },
      marker: { color: LIME, size: 8, line: { color: "#04120b", width: 1.5 } },
      fill: "tozeroy",
      fillcolor: FILL,
      hovertemplate: "%{x|%d %b %Y}<br><b>%{y}</b> " + unit + "<extra></extra>",
    };

    const xaxis = Object.assign({}, DATE_AXIS);
    const yaxis = Object.assign({}, VALUE_AXIS);

    if (series.length === 1) {
      // One session: give the point room to breathe instead of letting Plotly
      // zoom into a zero-width range.
      const stamp = new Date(series[0].date).getTime();
      xaxis.range = [stamp - 3 * DAY_MS, stamp + 3 * DAY_MS];
      yaxis.range = [0, values[0] * 1.4];
    } else {
      yaxis.rangemode = "tozero"; // a strength chart that starts at 55 exaggerates
    }

    const layout = Object.assign({}, LAYOUT, { xaxis: xaxis, yaxis: yaxis });
    Plotly.newPlot(element, [trace], layout, CONFIG);
  }

  function renderWeeklyBars(elementId, series) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }

    if (!series || series.length === 0) {
      element.classList.add("d-none");
      const empty = document.getElementById("empty-weekly");
      if (empty) {
        empty.classList.remove("d-none");
      }
      return;
    }

    const counts = series.map((week) => week.workouts);

    const trace = {
      x: series.map((week) => week.week_start),
      y: counts,
      type: "bar",
      marker: { color: ACCENT, cornerradius: 6, line: { color: LIME, width: 0 } },
      hovertemplate:
        "Week of %{x|%d %b}<br><b>%{y}</b> workout(s)<extra></extra>",
    };

    const xaxis = Object.assign({}, DATE_AXIS);
    const yaxis = Object.assign({}, VALUE_AXIS, {
      dtick: 1, // whole workouts only — "1.5 workouts" is meaningless
      rangemode: "tozero",
    });

    if (series.length === 1) {
      const stamp = new Date(series[0].week_start).getTime();
      xaxis.range = [stamp - 10 * DAY_MS, stamp + 10 * DAY_MS];
      yaxis.range = [0, Math.max(counts[0], 1) + 1];
    }

    const layout = Object.assign({}, LAYOUT, { xaxis: xaxis, yaxis: yaxis });
    Plotly.newPlot(element, [trace], layout, CONFIG);
  }

  renderWeeklyBars("chart-weekly", charts.weekly_workouts);

  if (exerciseName) {
    renderLine("chart-max-weight", charts.max_weight, "kg");
    renderLine("chart-1rm", charts.estimated_1rm, "kg est. 1RM");
    // Volume load is weight x reps summed across sets — it is NOT a weight you
    // lifted in one go, so it must never be labelled plainly as "kg".
    renderLine("chart-volume", charts.volume, "kg volume load");
  }

  // Selecting an exercise reloads the dashboard for it.
  const picker = document.getElementById("exercise-picker");
  const select = document.getElementById("exercise-select");
  const goButton = document.getElementById("exercise-go");

  if (picker && select) {
    select.addEventListener("change", function () {
      // requestSubmit(), not submit(): submit() fires no submit event, so
      // nav.js would never show its progress bar for the reload.
      if (typeof picker.requestSubmit === "function") {
        picker.requestSubmit();
      } else {
        picker.submit();
      }
    });
    if (goButton) {
      goButton.hidden = true; // redundant when JS is available
    }
  }
})();
