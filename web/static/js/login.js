/* Login, landing and password-reset pages. */
(function () {
  "use strict";
  const HS = window.HS;
  HS.applyI18n();
  document.getElementById("btn-lang")?.addEventListener("click", () => HS.setLang(HS.lang === "hi" ? "en" : "hi", false));

  const form = document.getElementById("login-form");
  if (form) {
    const err = document.getElementById("login-error");
    const otpField = document.getElementById("otp-field");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const d = HS.formData(form);
      if (!d.login_id || !d.password) { err.textContent = HS.t("login_id") + " / " + HS.t("password") + " ?"; return; }
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const res = await HS.api(`/api/auth/${HS.portal}/login`, {
          method: "POST", allow401: true,
          body: { login_id: d.login_id, password: d.password, otp: d.otp || null },
        });
        if (res.mfa_required) {
          otpField.classList.remove("hidden");
          document.getElementById("otp").focus();
          return;
        }
        location.href = res.redirect;
      } catch (ex) {
        err.textContent = ex.message;
        form.querySelector("#password").value = "";
      } finally {
        btn.disabled = false;
      }
    });
    document.getElementById("login_id").focus();
  }

  if (document.body.dataset.reset) {
    const token = new URLSearchParams(location.hash.slice(1)).get("token");
    const req = document.getElementById("request-form");
    const conf = document.getElementById("confirm-form");
    if (token) {
      req.classList.add("hidden");
      conf.classList.remove("hidden");
      history.replaceState(null, "", "/reset-password"); // keep the token out of history
    }
    req.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = document.getElementById("request-msg");
      try {
        const r = await HS.api("/api/auth/password-reset/request", { method: "POST", body: HS.formData(req) });
        msg.textContent = r.message;
      } catch (ex) { msg.textContent = ex.message; }
    });
    conf.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = document.getElementById("confirm-msg");
      const d = HS.formData(conf);
      if (d.new_password !== d.repeat) { msg.textContent = HS.t("passwords_differ"); return; }
      try {
        await HS.api("/api/auth/password-reset/confirm", { method: "POST", body: { token, new_password: d.new_password } });
        HS.mount(conf, HS.el("p", null, "Password updated. You can now sign in from your portal."),
          HS.el("a", { class: "btn primary", href: "/" }, HS.t("go_home")));
      } catch (ex) { msg.textContent = ex.message; }
    });
  }
})();
