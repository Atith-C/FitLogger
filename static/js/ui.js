/* Aurora Athletic — UI micro-interactions.
 *
 * Progressive enhancement only. Every page is fully usable and fully visible
 * with this file absent, disabled, or under prefers-reduced-motion. Nothing
 * essential depends on it; it only adds polish where motion is welcome.
 */

(function () {
  "use strict";

  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Bail out entirely for reduced-motion or very old browsers. Content stays
  // visible because `.reveal` only hides once `.anim-ready` is present.
  if (reduce || !("IntersectionObserver" in window)) {
    return;
  }

  root.classList.add("anim-ready");

  // ---- Reveal on scroll ---------------------------------------------------
  // Give each revealed element a staggered delay based on its position among
  // its siblings, so groups cascade in rather than snapping together.
  document.querySelectorAll(".reveal").forEach(function (el, i) {
    if (!el.style.getPropertyValue("--fl-i")) {
      el.style.setProperty("--fl-i", (i % 6).toString());
    }
  });

  var revealObserver = new IntersectionObserver(
    function (entries, observer) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: "0px 0px -6% 0px", threshold: 0.06 }
  );
  document.querySelectorAll(".reveal").forEach(function (el) {
    revealObserver.observe(el);
  });

  // ---- Count-up for stat numbers -----------------------------------------
  // Only touches elements explicitly marked with data-count and a finite
  // numeric target. The exact server-rendered text is restored at the end, so
  // formatting, units and edge cases are never corrupted.
  function animateCount(el) {
    var target = parseFloat(el.getAttribute("data-count"));
    if (!isFinite(target)) {
      return;
    }
    var decimals = parseInt(el.getAttribute("data-decimals") || "0", 10);
    var prefix = el.getAttribute("data-prefix") || "";
    var suffix = el.getAttribute("data-suffix") || "";
    var finalText = el.textContent;
    var duration = 850;
    var startTime = null;

    function frame(now) {
      if (startTime === null) {
        startTime = now;
      }
      var progress = Math.min((now - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
      var current = target * eased;
      el.textContent = prefix + current.toFixed(decimals) + suffix;
      if (progress < 1) {
        requestAnimationFrame(frame);
      } else {
        el.textContent = finalText; // restore exact server value
      }
    }
    requestAnimationFrame(frame);
  }

  var countObserver = new IntersectionObserver(
    function (entries, observer) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCount(entry.target);
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.4 }
  );
  document.querySelectorAll("[data-count]").forEach(function (el) {
    countObserver.observe(el);
  });
})();
