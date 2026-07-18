/* Admin platform analytics.
 *
 * Every number here was aggregated in Python (adminportal/services.py). This
 * file only renders what the server sent — it does no maths of its own, and it
 * never receives a trainee's gated profile data: the goal, experience and
 * weekday charts arrive as plain counts.
 *
 * Theme constants mirror charts.js so the two look identical.
 */

(function () {
  "use strict";

  const dataElement = document.getElementById("analytics-data");
  if (!dataElement) {
    return;
  }

  if (typeof Plotly === "undefined") {
    document.querySelectorAll(".fl-chart").forEach(function (el) {
      el.innerHTML =
        '<p class="text-secondary small mb-0 py-4 text-center">' +
        "Charts could not be loaded. Try a refresh.</p>";
    });
    return;
  }

  const data = JSON.parse(dataElement.textContent);

  const GRID = "rgba(190,242,172,0.10)";
  const ACCENT = "#22c55e";
  const LIME = "#a3e635";
  const FILL = "rgba(34,197,94,0.12)";
  const DAY_MS = 24 * 60 * 60 * 1000;

  const LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Sora, ui-sans-serif, system-ui, sans-serif", color: "#9db0a8", size: 12 },
    margin: { l: 44, r: 16, t: 8, b: 40 },
    showlegend: false,
    height: 260,
    hoverlabel: {
      bgcolor: "#0b110f",
      bordercolor: "rgba(190,242,172,0.25)",
      font: { family: "Sora, sans-serif", color: "#ecf5f0" },
      align: "left",
    },
  };
  const CONFIG = { displayModeBar: false, responsive: true };

  const VALUE_AXIS = { gridcolor: GRID, zerolinecolor: GRID, automargin: true };
  const CATEGORY_AXIS = { gridcolor: "rgba(0,0,0,0)", zerolinecolor: GRID, linecolor: GRID };

  function empty(id) {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML =
        '<p class="text-secondary small mb-0 py-4 text-center">No data yet.</p>';
    }
  }

  function countAxis() {
    // Integer ticks, but auto-spaced: forcing a gridline at every unit crowds
    // the axis the moment counts climb (the weekday chart passes 100). "d"
    // keeps the labels whole, Plotly picks a sensible gap.
    return Object.assign({}, VALUE_AXIS, { rangemode: "tozero", tickformat: "d" });
  }

  // Per-value / per-point gaps for the growth chart, so labels never crowd. The
  // plot is sized to fit them and the .fl-chart-scroll wrapper scrolls.
  const GROWTH_Y_GAP = 22;
  const GROWTH_X_GAP = 64;

  // --- 1. user growth (line, dot = a trainee, hover = name + join date) ---
  function renderGrowth(series) {
    const el = document.getElementById("chart-growth");
    if (!el) {
      return;
    }
    if (!series || series.length === 0) {
      empty("chart-growth");
      return;
    }

    const trace = {
      x: series.map((p) => p.date),
      y: series.map((p) => p.count),
      customdata: series.map((p) => [p.name, p.joined]),
      type: "scatter",
      mode: "lines+markers",
      line: { color: ACCENT, width: 2.5, shape: "hv" },
      marker: { color: LIME, size: 9, line: { color: "#04120b", width: 1.5 } },
      fill: "tozeroy",
      fillcolor: FILL,
      hovertemplate: "<b>%{customdata[0]}</b><br>joined %{customdata[1]}<br>total users: %{y}<extra></extra>",
    };

    // Cumulative series, so the last point is the tallest. Size the plot to
    // give every user a spaced gridline and every dot room on the time axis;
    // the wrapper scrolls when that outgrows the card.
    const maxCount = series[series.length - 1].count;
    const wrapper = el.parentElement;
    const height = Math.max(300, (maxCount + 1) * GROWTH_Y_GAP);
    const width = Math.max(
      wrapper ? wrapper.clientWidth : 560, series.length * GROWTH_X_GAP
    );

    const xaxis = { type: "date", tickformat: "%d %b", gridcolor: GRID, zerolinecolor: GRID, linecolor: GRID };
    // A gridline per user (dtick 1) is legible now that each has 22px of room.
    const yaxis = { gridcolor: GRID, zerolinecolor: GRID, rangemode: "tozero", dtick: 1, tickformat: "d" };
    if (series.length === 1) {
      const stamp = new Date(series[0].date).getTime();
      xaxis.range = [stamp - 3 * DAY_MS, stamp + 3 * DAY_MS];
    }

    const layout = Object.assign({}, LAYOUT, {
      xaxis: xaxis, yaxis: yaxis, height: height, width: width,
      margin: { l: 44, r: 24, t: 8, b: 40 },
    });
    // responsive:false so the fixed, scrollable size is not shrunk back to the
    // card width on the next resize.
    Plotly.newPlot(el, [trace], layout, { displayModeBar: false, responsive: false });

    // Start scrolled to the bottom: the x-axis and the low counts show first,
    // and you scroll up toward the higher values.
    if (wrapper) {
      wrapper.scrollTop = wrapper.scrollHeight;
    }
  }

  // --- 2. active users DAU/WAU/MAU (bar, hover = the names) ---
  function renderActive(bars) {
    const el = document.getElementById("chart-active");
    if (!el) {
      return;
    }

    const trace = {
      x: bars.map((b) => b.label),
      y: bars.map((b) => b.count),
      customdata: bars.map((b) => (b.names.length ? b.names.join("<br>") : "nobody yet")),
      type: "bar",
      marker: { color: ACCENT, cornerradius: 6 },
      hovertemplate: "<b>%{x} active</b>: %{y}<br>%{customdata}<extra></extra>",
    };

    Plotly.newPlot(
      el, [trace],
      Object.assign({}, LAYOUT, { xaxis: CATEGORY_AXIS, yaxis: countAxis() }),
      CONFIG
    );
  }

  // --- shared: a plain count bar chart (weekday, goals, experience, sex) ---
  function renderCountBars(id, bars, unit) {
    const el = document.getElementById(id);
    if (!el) {
      return;
    }
    if (!bars || bars.length === 0) {
      empty(id);
      return;
    }

    const trace = {
      x: bars.map((b) => b.label),
      y: bars.map((b) => b.count),
      type: "bar",
      marker: { color: ACCENT, cornerradius: 6 },
      hovertemplate: "%{x}<br><b>%{y}</b> " + unit + "<extra></extra>",
    };

    Plotly.newPlot(
      el, [trace],
      Object.assign({}, LAYOUT, { xaxis: CATEGORY_AXIS, yaxis: countAxis() }),
      CONFIG
    );
  }

  renderGrowth(data.growth);
  renderActive(data.active);
  renderCountBars("chart-weekday", data.weekday, "workout(s)");
  if (data.goals) {
    renderCountBars("chart-goals", data.goals, "trainee(s)");
  }
  if (data.experience) {
    renderCountBars("chart-experience", data.experience, "trainee(s)");
  }
  renderCountBars("chart-sex", data.sex, "trainee(s)");
})();
