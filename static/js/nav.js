/* Aurora Athletic — navigation feedback.
 *
 * Django renders every page on the server, so a click never blanks the screen:
 * the current page simply sits there until the next one arrives. The gap that
 * needs covering is therefore *acknowledgement*, not empty layout. This file
 * shows a top progress bar the moment a navigation starts, and puts submit
 * buttons into a pending state so a slow POST cannot be double-submitted.
 *
 * Progressive enhancement only — with this file absent every page still works.
 */

(function () {
  "use strict";

  var bar = document.getElementById("nav-progress");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var timer = null;

  function startBar() {
    if (!bar || bar.classList.contains("is-active")) {
      return;
    }
    bar.classList.add("is-active");

    // Paint a visible sliver immediately. Waiting for the interval's first tick
    // would mean the bar is 0px wide for its first 180ms — long enough that a
    // fast navigation completes before it ever appears, which defeats the
    // entire point of having it.
    var progress = 8;
    bar.style.setProperty("--fl-progress", progress + "%");

    // Then creep toward — but never reach — 90%. It can only truly complete when
    // the new document replaces this one, so claiming 100% would be a lie.
    timer = window.setInterval(function () {
      progress += (90 - progress) * 0.12;
      bar.style.setProperty("--fl-progress", progress.toFixed(1) + "%");
    }, 180);
  }

  function stopBar() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    if (bar) {
      bar.classList.remove("is-active");
      bar.style.setProperty("--fl-progress", "0%");
    }
  }

  // A plain left-click on a same-origin link that is about to navigate.
  function isPlainNavigation(event, link) {
    return (
      event.button === 0 &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey &&
      !event.defaultPrevented &&
      link.target !== "_blank" &&
      link.origin === window.location.origin &&
      // In-page anchors and downloads never leave the document.
      !link.hasAttribute("download") &&
      link.getAttribute("href") !== null &&
      link.getAttribute("href").charAt(0) !== "#" &&
      !(
        link.pathname === window.location.pathname &&
        link.search === window.location.search &&
        link.hash !== ""
      )
    );
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[href]") : null;
    if (link && isPlainNavigation(event, link)) {
      startBar();
    }
  });

  // Forms: show the bar and mark the submitter busy. The button is NOT disabled
  // — a disabled submitter is omitted from the POST body, which would break the
  // finish-vs-save-note formaction split on the active workout screen.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) {
      return;
    }
    startBar();

    var submitter = event.submitter;
    if (submitter && !submitter.hasAttribute("data-no-busy")) {
      submitter.classList.add("is-busy");
      submitter.setAttribute("aria-busy", "true");
    }
  });

  // Coming back via the bfcache restores this document exactly as it was left —
  // which means frozen mid-navigation, with the bar creeping and the button the
  // user clicked still spinning. Reset both, or Back looks like a hung page.
  window.addEventListener("pageshow", function () {
    stopBar();
    document.querySelectorAll(".is-busy").forEach(function (el) {
      el.classList.remove("is-busy");
      el.removeAttribute("aria-busy");
    });
  });

  // NOTE: deliberately no "beforeunload" cleanup. beforeunload fires at
  // navigation *start*, not when the response arrives — clearing the interval
  // there would kill the bar milliseconds after starting it, so it would never
  // advance at all. The interval dies with the document anyway; the only case
  // that needs handling is bfcache restore, which "pageshow" above covers.

  if (reduce && bar) {
    // Keep the acknowledgement, drop the creep animation.
    bar.setAttribute("data-reduced", "true");
  }
})();
