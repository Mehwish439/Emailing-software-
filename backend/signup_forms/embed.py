# NEW FILE (Signup Forms feature)
"""
The public embed script (spec section #4). Deliberately plain, dependency-
free JS served as a static string from a Django view (see views.py's
embed_script) rather than a separate frontend build artifact — this app's
Vite frontend is an authenticated SPA behind /login; a script meant to run
unauthenticated on a stranger's website has nothing in common with it and
doesn't belong in that build pipeline. Serving it as one small view keeps
the whole feature inside the existing backend/frontend split instead of
inventing a third build target.

The script determines its own API origin from the <script src="..."> tag
that loaded it (via document.currentScript), so the exact same script
works from local dev, staging, or production — never a hardcoded
localhost URL (spec section #4's requirement).
"""

EMBED_SCRIPT = r"""
(function () {
  var currentScript = document.currentScript;
  if (!currentScript) return;

  var apiOrigin = new URL(currentScript.src).origin;
  var formId = currentScript.getAttribute("data-form-id");
  var targetId = currentScript.getAttribute("data-target");
  var target = formId && targetId ? document.getElementById(targetId) : null;
  if (!target) return;

  var API_BASE = apiOrigin + "/api/public/signup-forms/" + encodeURIComponent(formId) + "/";

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    for (var key in attrs || {}) node.setAttribute(key, attrs[key]);
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  target.innerHTML = "";
  var wrapper = el("div", { style: "font-family:-apple-system,system-ui,sans-serif;max-width:420px" });
  wrapper.appendChild(el("p", { style: "font-size:14px;color:#475569" }, ["Loading signup form…"]));
  target.appendChild(wrapper);

  fetch(API_BASE)
    .then(function (res) {
      if (!res.ok) throw new Error("not-found");
      return res.json();
    })
    .then(renderForm)
    .catch(function () {
      wrapper.innerHTML = "";
      wrapper.appendChild(
        el("p", { style: "font-size:14px;color:#dc2626" }, ["This signup form is unavailable."])
      );
    });

  function renderForm(form) {
    wrapper.innerHTML = "";

    var title = el("h3", { style: "margin:0 0 4px;font-size:18px;color:#0f172a" }, [form.name]);
    wrapper.appendChild(title);
    if (form.description) {
      wrapper.appendChild(
        el("p", { style: "margin:0 0 12px;font-size:13px;color:#64748b" }, [form.description])
      );
    }

    var formEl = el("form", { novalidate: "novalidate" });
    var statusEl = el("div", { style: "font-size:13px;margin-top:8px" });

    function field(name, label, type, required) {
      var group = el("div", { style: "margin-bottom:10px" });
      group.appendChild(
        el("label", { style: "display:block;font-size:12px;color:#334155;margin-bottom:4px" }, [
          label + (required ? " *" : ""),
        ])
      );
      var input = el("input", {
        name: name,
        type: type,
        style:
          "width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:14px",
      });
      if (required) input.setAttribute("required", "required");
      group.appendChild(input);
      formEl.appendChild(group);
      return input;
    }

    var firstNameInput = form.collect_first_name ? field("first_name", "First name", "text", false) : null;
    var lastNameInput = form.collect_last_name ? field("last_name", "Last name", "text", false) : null;
    var emailInput = field("email", "Email", "email", true);

    // Honeypot: hidden from real visitors via CSS (not `type=hidden`,
    // which some bots specifically skip) — any bot that blindly fills
    // every input finds and fills this one, flagging the submission as
    // spam server-side (see signup_forms/views.py). A real visitor never
    // sees or fills it.
    var honeypot = el("input", {
      type: "text",
      name: "hp_field",
      autocomplete: "off",
      tabindex: "-1",
      style: "position:absolute;left:-9999px;width:1px;height:1px;opacity:0",
    });
    formEl.appendChild(honeypot);

    var submitBtn = el(
      "button",
      {
        type: "submit",
        style:
          "width:100%;padding:10px 16px;background:#4f46e5;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer",
      },
      [form.button_text || "Subscribe"]
    );
    formEl.appendChild(submitBtn);
    formEl.appendChild(statusEl);
    wrapper.appendChild(formEl);

    formEl.addEventListener("submit", function (evt) {
      evt.preventDefault();
      statusEl.style.color = "#475569";
      statusEl.textContent = "";

      var email = emailInput.value.trim();
      if (!email || email.indexOf("@") === -1) {
        statusEl.style.color = "#dc2626";
        statusEl.textContent = "Please enter a valid email address.";
        return;
      }

      submitBtn.disabled = true;
      var originalLabel = submitBtn.textContent;
      submitBtn.textContent = "Submitting…";

      fetch(API_BASE + "submit/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email,
          first_name: firstNameInput ? firstNameInput.value.trim() : "",
          last_name: lastNameInput ? lastNameInput.value.trim() : "",
          hp_field: honeypot.value,
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalLabel;
          if (!result.ok) {
            statusEl.style.color = "#dc2626";
            statusEl.textContent = (result.data && result.data.detail) || "Something went wrong. Please try again.";
            return;
          }
          formEl.style.display = "none";
          statusEl.style.color = "#059669";
          statusEl.textContent = result.data.message;
        })
        .catch(function () {
          submitBtn.disabled = false;
          submitBtn.textContent = originalLabel;
          statusEl.style.color = "#dc2626";
          statusEl.textContent = "Network error. Please try again.";
        });
    });
  }
})();
"""
