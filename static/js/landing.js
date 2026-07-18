/* Aurora Athletic — landing page behaviour.
 *
 * Scroll-reveals and count-ups are already handled globally by ui.js; this file
 * only adds what is specific to the landing page. Everything here is optional
 * polish — the page reads and converts perfectly with JS disabled.
 */

(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Nav: glass over the hero, solid once scrolled ----------------------
  var nav = document.getElementById("lnav");
  if (nav) {
    var setStuck = function () {
      nav.classList.toggle("is-stuck", window.scrollY > 24);
    };
    setStuck();
    window.addEventListener("scroll", setStuck, { passive: true });
  }

  // ---- Smooth anchor scrolling -------------------------------------------
  // Native CSS scroll-behaviour is avoided: it would also apply to the app's
  // form-error jumps, where an instant jump is the correct behaviour.
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      var id = link.getAttribute("href");
      if (id === "#" || id.length < 2) {
        return;
      }
      var target = document.querySelector(id);
      if (!target) {
        return;
      }
      event.preventDefault();
      target.scrollIntoView({
        behavior: reduce ? "auto" : "smooth",
        block: "start",
      });
      // Keep the URL shareable and the history sane.
      if (window.history && window.history.pushState) {
        window.history.pushState(null, "", id);
      }
      // Move keyboard focus with the viewport, or the next Tab starts from the
      // top of the page instead of the section the user just jumped to.
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
  });

  if (reduce) {
    return; // everything below is decoration
  }

  // ---- Hero parallax ------------------------------------------------------
  // Pointer-driven only, rAF-throttled, transform-only. Skipped on touch,
  // where there is no pointer to follow and the effect would just cost battery.
  var art = document.querySelector(".fl-hero-art .fl-phone");
  var hero = document.querySelector(".fl-hero-sec");
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  if (art && hero && fine) {
    var frame = null;
    var tiltX = 0;
    var tiltY = 0;

    hero.addEventListener(
      "mousemove",
      function (event) {
        var rect = hero.getBoundingClientRect();
        // -1 .. 1 from the centre of the hero.
        tiltY = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
        tiltX = ((event.clientY - rect.top) / rect.height - 0.5) * 2;

        if (frame === null) {
          frame = window.requestAnimationFrame(function () {
            frame = null;
            // The -11deg base keeps the phone's resting pose from landing.css.
            art.style.transform =
              "rotateY(" + (-11 + tiltY * 5).toFixed(2) + "deg) " +
              "rotateX(" + (4 - tiltX * 4).toFixed(2) + "deg)";
          });
        }
      },
      { passive: true }
    );

    hero.addEventListener("mouseleave", function () {
      art.style.transform = "";
    });
  }
})();
