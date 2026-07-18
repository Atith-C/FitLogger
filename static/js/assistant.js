/* Joey — fitness assistant chat widget.
 *
 * Talks to /assistant/chat/. The conversation is stored server-side, so it
 * survives navigating between pages: when the panel opens it restores the saved
 * history from /assistant/history/. The client only sends the new message —
 * the server owns the history and clears it on logout.
 */

(function () {
  "use strict";

  const root = document.getElementById("fl-joey");
  if (!root) {
    return;
  }

  const CHAT_URL = root.dataset.chatUrl;
  const HISTORY_URL = root.dataset.historyUrl;
  const GREETING = root.dataset.greeting;

  const openBtn = document.getElementById("fl-joey-open");
  const closeBtn = document.getElementById("fl-joey-close");
  const panel = document.getElementById("fl-joey-panel");
  const hint = document.getElementById("fl-joey-hint");
  const messagesEl = document.getElementById("fl-joey-messages");
  const form = document.getElementById("fl-joey-form");
  const field = document.getElementById("fl-joey-text");

  let started = false;
  let awaiting = false;

  function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function scrollToBottom() {
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
  }

  function addMessage(role, text) {
    const row = document.createElement("div");
    row.className = "fl-joey-msg fl-joey-msg-" + role;
    const bubble = document.createElement("div");
    bubble.className = "fl-joey-bubble";
    bubble.textContent = text; // textContent — never render model output as HTML
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    scrollToBottom();
    return bubble;
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "fl-joey-msg fl-joey-msg-assistant";
    row.id = "fl-joey-typing";
    row.innerHTML =
      '<div class="fl-joey-bubble fl-joey-typing"><span></span><span></span><span></span></div>';
    messagesEl.appendChild(row);
    scrollToBottom();
  }

  function removeTyping() {
    const row = document.getElementById("fl-joey-typing");
    if (row) {
      row.remove();
    }
  }

  // Restore the saved conversation the first time the panel opens on this page.
  function loadHistory() {
    if (!HISTORY_URL) {
      return;
    }
    fetch(HISTORY_URL, { headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        return response.ok ? response.json() : { messages: [] };
      })
      .then(function (data) {
        (data.messages || []).forEach(function (m) {
          addMessage(m.role, m.content);
        });
      })
      .catch(function () {
        /* offline or a blip — the greeting still stands */
      });
  }

  function openPanel() {
    panel.hidden = false;
    openBtn.setAttribute("aria-expanded", "true");
    root.classList.add("is-open");
    if (hint) {
      hint.remove();
    }
    if (!started) {
      started = true;
      addMessage("assistant", GREETING);
      loadHistory();
    }
    setTimeout(function () {
      field.focus();
    }, 50);
  }

  function closePanel() {
    panel.hidden = true;
    openBtn.setAttribute("aria-expanded", "false");
    root.classList.remove("is-open");
  }

  openBtn.addEventListener("click", function () {
    if (panel.hidden) {
      openPanel();
    } else {
      closePanel();
    }
  });
  closeBtn.addEventListener("click", closePanel);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      closePanel();
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = field.value.trim();
    if (!text || awaiting) {
      return;
    }

    addMessage("user", text);
    field.value = "";
    awaiting = true;
    showTyping();

    fetch(CHAT_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ message: text }),
    })
      .then(function (response) {
        return response.json().catch(function () {
          return { error: "Something went wrong. Please try again." };
        });
      })
      .then(function (data) {
        removeTyping();
        addMessage("assistant", data.reply || data.error || "Sorry, please try again.");
      })
      .catch(function () {
        removeTyping();
        addMessage("assistant", "I couldn't reach the server. Please try again.");
      })
      .finally(function () {
        awaiting = false;
        field.focus();
      });
  });

  // Drop the hint bubble after a while so it isn't forever in the corner.
  if (hint) {
    setTimeout(function () {
      hint.classList.add("is-fading");
    }, 8000);
  }
})();
