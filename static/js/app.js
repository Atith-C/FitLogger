/* App-wide progressive enhancements, loaded on every page.
 *
 * Nothing essential depends on this file.
 */

(function () {
  "use strict";

  // Stop the mouse wheel from silently changing <input type="number"> values.
  //
  // By default, scrolling the page with the cursor over a focused number field
  // increments or decrements it — so a user scrolling the profile page can
  // change their weight or training days without noticing, then save it. We
  // blur the field on wheel so the page scrolls and the value is left alone.
  document.addEventListener(
    "wheel",
    function (event) {
      const el = document.activeElement;
      if (el && el.tagName === "INPUT" && el.type === "number" && el === event.target) {
        el.blur();
      }
    },
    { passive: true }
  );
})();
