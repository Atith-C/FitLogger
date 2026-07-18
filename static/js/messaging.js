/* Conversation chat — send + poll.
 *
 * Sends via AJAX and appends instantly; polls every few seconds for messages
 * from the other party, so trainee and admin stay in sync without a reload.
 */

(function () {
  "use strict";

  const root = document.getElementById("fl-chat");
  if (!root) {
    return;
  }

  const SEND_URL = root.dataset.sendUrl;
  const POLL_URL = root.dataset.pollUrl;
  let lastId = parseInt(root.dataset.lastId, 10) || 0;

  const body = document.getElementById("fl-chat-body");
  const form = document.getElementById("fl-chat-form");
  const field = document.getElementById("fl-chat-text");
  const errorEl = document.getElementById("fl-chat-error");
  const todayBlock = document.getElementById("fl-chat-today");

  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function scrollDown() {
    body.scrollTo({ top: body.scrollHeight, behavior: "smooth" });
  }

  function appendMessage(msg) {
    const row = document.createElement("div");
    row.className = "fl-chat-msg" + (msg.is_mine ? " is-mine" : "");
    row.dataset.id = msg.id;

    const bubble = document.createElement("div");
    bubble.className = "fl-chat-bubble";
    bubble.textContent = msg.body; // textContent — never render as HTML

    const time = document.createElement("span");
    time.className = "fl-chat-time";
    time.textContent = msg.time;

    row.appendChild(bubble);
    row.appendChild(time);
    todayBlock.appendChild(row);

    if (msg.id > lastId) {
      lastId = msg.id;
    }
  }

  // Start at the bottom of the history.
  scrollDown();

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = field.value.trim();
    if (!text) {
      return;
    }
    field.value = "";
    hideError();

    fetch(SEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ body: text }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.message) {
          appendMessage(data.message);
          scrollDown();
        } else if (data.error) {
          // e.g. the admin has turned messaging off. Show why and give the
          // typed text back so it is not lost.
          showError(data.error);
          field.value = text;
        }
      })
      .catch(function () {
        /* keep the typed text recoverable next time */
        field.value = text;
      });
  });

  function showError(text) {
    if (errorEl) {
      errorEl.textContent = text;
      errorEl.classList.remove("d-none");
    }
  }

  function hideError() {
    if (errorEl) {
      errorEl.classList.add("d-none");
    }
  }

  // Poll for new messages from the other party.
  function poll() {
    fetch(POLL_URL + "?after=" + lastId, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.messages && data.messages.length) {
          const nearBottom =
            body.scrollHeight - body.scrollTop - body.clientHeight < 80;
          data.messages.forEach(appendMessage);
          if (nearBottom) {
            scrollDown();
          }
        }
      })
      .catch(function () {
        /* transient — the next tick will retry */
      });
  }

  setInterval(poll, 4000);
})();
