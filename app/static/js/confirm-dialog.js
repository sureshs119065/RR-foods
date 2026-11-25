/* One confirmation pop-up for every risky action in the Admin and Owner panels (delete, block, archive, reset password, sign out ...).
   - Any <button>/<form> with data-confirm="message" asks first (optional: data-confirm-title, data-confirm-ok, data-confirm-tone="warn").
   - Forms that post to a risky URL (/delete, /block, /archive, /reset-password, /logout) ask first even without data-confirm,
     so a new delete button can never skip the question.
   Cancel is focused by default, Esc cancels, and nothing is sent until the person presses the red button. */
(function () {
  'use strict';

  var RULES = [
    { re: /\/logout$/,         title: 'Sign out?',            text: 'You will need to sign in again to use this panel.', ok: 'Sign out', tone: 'warn' },
    { re: /\/delete$/,         title: 'Delete this item?',    text: 'This will remove it. This cannot be undone.', ok: 'Delete' },
    { re: /\/block$/,          title: 'Block this customer?', text: 'They will not be able to sign in or place orders until you unblock them.', ok: 'Block' },
    { re: /\/archive$/,        title: 'Archive this item?',   text: 'It will be hidden from the shop. You can restore it later.', ok: 'Archive', tone: 'warn' },
    { re: /\/reset-password$/, title: 'Reset this password?', text: 'Their current password will stop working. A temporary password will be created.', ok: 'Reset password', tone: 'warn' }
  ];

  var dlg, titleEl, textEl, okBtn, cancelBtn, pending = null, lastFocus = null;

  function build() {
    if (dlg) return;
    dlg = document.createElement('dialog');
    dlg.className = 'cd';
    dlg.setAttribute('aria-labelledby', 'cd-title');
    dlg.setAttribute('aria-describedby', 'cd-text');
    dlg.innerHTML =
      '<form method="dialog" class="cd__box">' +
      '<h2 class="cd__title" id="cd-title"></h2>' +
      '<p class="cd__text" id="cd-text"></p>' +
      '<div class="cd__btns"><button type="button" class="cd__btn cd__btn--cancel" data-cd-cancel>Cancel</button>' +
      '<button type="button" class="cd__btn cd__btn--ok" data-cd-ok></button></div></form>';
    document.body.appendChild(dlg);
    titleEl = dlg.querySelector('.cd__title'); textEl = dlg.querySelector('.cd__text');
    okBtn = dlg.querySelector('[data-cd-ok]'); cancelBtn = dlg.querySelector('[data-cd-cancel]');
    cancelBtn.addEventListener('click', function () { close(false); });
    okBtn.addEventListener('click', function () { close(true); });
    dlg.addEventListener('cancel', function (e) { e.preventDefault(); close(false); });          // Esc
    dlg.addEventListener('click', function (e) { if (e.target === dlg) close(false); });          // click on the dark backdrop
  }

  function close(yes) {
    var job = pending; pending = null;
    if (dlg.open) dlg.close();
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* ignore */ } }
    if (yes && job) job();
  }

  function ask(opts, onYes) {
    build();
    pending = onYes;
    lastFocus = document.activeElement;
    titleEl.textContent = opts.title;
    textEl.textContent = opts.text;
    okBtn.textContent = opts.ok;
    okBtn.className = 'cd__btn cd__btn--ok' + (opts.tone === 'warn' ? ' cd__btn--warn' : '');
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    cancelBtn.focus();
  }

  function pathOf(form) {
    try { return new URL(form.getAttribute('action') || location.href, location.href).pathname.replace(/\/+$/, ''); } catch (e) { return ''; }
  }

  function describe(form, submitter) {
    var src = submitter && submitter.hasAttribute('data-confirm') ? submitter : (form.hasAttribute('data-confirm') ? form : null);
    var rule = null, path = pathOf(form);
    for (var i = 0; i < RULES.length; i++) if (RULES[i].re.test(path)) { rule = RULES[i]; break; }
    if (!src && !rule) return null;
    var o = { title: rule ? rule.title : 'Are you sure?', text: rule ? rule.text : 'Please confirm to continue.', ok: rule ? rule.ok : 'Yes, continue', tone: rule && rule.tone };
    if (src) {
      o.text = src.getAttribute('data-confirm') || o.text;
      if (src.getAttribute('data-confirm-title')) o.title = src.getAttribute('data-confirm-title');
      if (src.getAttribute('data-confirm-ok')) o.ok = src.getAttribute('data-confirm-ok');
      if (src.getAttribute('data-confirm-tone')) o.tone = src.getAttribute('data-confirm-tone');
    }
    return o;
  }

  /* Forms: runs first (capture) and stops other submit handlers until the person has said yes. */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.tagName !== 'FORM' || form.hasAttribute('data-confirmed')) return;
    var submitter = e.submitter || null;
    var o = describe(form, submitter);
    if (!o) return;
    e.preventDefault(); e.stopImmediatePropagation();
    ask(o, function () {
      form.setAttribute('data-confirmed', '1');
      try { if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined); else form.submit(); }
      finally { setTimeout(function () { form.removeAttribute('data-confirmed'); }, 0); }
    });
  }, true);

  /* Links (not buttons inside forms) with data-confirm. */
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-confirm]');
    if (!a || a.hasAttribute('data-confirmed')) return;
    e.preventDefault();
    ask({ title: a.getAttribute('data-confirm-title') || 'Are you sure?', text: a.getAttribute('data-confirm'), ok: a.getAttribute('data-confirm-ok') || 'Yes, continue', tone: a.getAttribute('data-confirm-tone') }, function () { window.location.href = a.href; });
  });
})();
