/* Wellness passport charts.
 *
 * Every value was computed in Python (analytics/services.py). This file only
 * renders the trend lines the server sent — it does no maths of its own.
 */

(function () {
  "use strict";

  const dataElement = document.getElementById("wellness-charts");
  if (!dataElement) {
    return;
  }

  // If Plotly never arrives (CDN blocked, offline), say so instead of leaving
  // the chart boxes blank.
  if (typeof Plotly === "undefined") {
    document.querySelectorAll(".fl-chart").forEach(function (el) {
      el.innerHTML =
        '<p class="text-secondary small mb-0 py-4 text-center">' +
        "Charts could not be loaded. Your data is safe — try a refresh.</p>";
    });
    return;
  }

  const charts = JSON.parse(dataElement.textContent);

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

  // Dates on the x-axis, always. Without type:"date" Plotly renders a lone
  // point with millisecond ticks.
  const DATE_AXIS = {
    type: "date",
    tickformat: "%d %b",
    gridcolor: GRID,
    zerolinecolor: GRID,
    linecolor: GRID,
  };

  const CONFIG = { displayModeBar: false, responsive: true };
  const ACCENT = "#22c55e";
  const LIME = "#a3e635";
  const FILL = "rgba(34,197,94,0.12)";
  const DAY_MS = 24 * 60 * 60 * 1000;

  function renderLine(elementId, series, unit) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }

    if (!series || series.length === 0) {
      element.innerHTML =
        '<p class="text-secondary small mb-0 py-4 text-center">No data logged yet.</p>';
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
    const yaxis = { gridcolor: GRID, zerolinecolor: GRID, automargin: true };

    if (series.length === 1) {
      const stamp = new Date(series[0].date).getTime();
      xaxis.range = [stamp - 3 * DAY_MS, stamp + 3 * DAY_MS];
    }

    Plotly.newPlot(
      element,
      [trace],
      Object.assign({}, LAYOUT, { xaxis: xaxis, yaxis: yaxis }),
      CONFIG
    );
  }

  renderLine("chart-weight", charts.weight, "kg");
  renderLine("chart-body-fat", charts.body_fat, "%");
  renderLine("chart-muscle", charts.muscle_mass, "kg");
})();
