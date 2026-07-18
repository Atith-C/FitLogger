/* Live nav badges.
 *
 * The bell and message counts are rendered server-side on every page load;
 * this file only keeps them fresh while a page sits open, so an admin sees a
 * trainee's change land without pressing refresh.
 *
 * Progressive enhancement: with this file absent the badges still render, they
 * just update on the next navigation instead.
 */

(function () {
  "use strict";

  var root = document.getElementById("badge-poll");
  if (!root || !window.fetch) {
    return;
  }

  var URL = root.dataset.pollUrl;

  // 30s, not the 4s the chat thread uses: a nav badge is ambient, and this
  // fires on every open tab for the whole session.
  var INTERVAL = 30000;

  function paint(link, count) {
    if (!link) {
      return;
    }
    var badge = link.querySelector(".fl-bell-badge");

    if (!count) {
      // Zero is shown as no badge at all, matching the template.
      if (badge) {
        badge.remove();
      }
      return;
    }

    if (!badge) {
      badge = document.createElement("span");
      badge.className = "fl-bell-badge";
      link.appendChild(badge);
    }
    badge.textContent = count;
  }

  function poll() {
    // A tab in the background costs the server nothing until it is looked at.
    if (document.hidden) {
      return;
    }

    fetch(URL, { headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data) {
          return;
        }
        paint(document.querySelector('[data-badge="notifications"]'), data.notifications);
        paint(document.querySelector('[data-badge="messages"]'), data.messages);
      })
      .catch(function () {
        // Offline or a blip: leave the server-rendered counts alone and try
        // again on the next tick.
      });
  }

  window.setInterval(poll, INTERVAL);

  // Coming back to the tab is exactly when a stale badge is most visible.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      poll();
    }
  });
})();
