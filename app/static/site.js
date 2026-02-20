document.addEventListener('DOMContentLoaded', function(){
  var sidebar = document.getElementById('sidebar');

  // Apply theme from cookie (server also sets cookie when saving settings)
  function getCookie(name) {
    var v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return v ? v.pop() : '';
  }
  var theme = getCookie('ldwui_theme') || 'default';
  if (theme && theme !== 'default') {
    document.body.classList.add('theme-' + theme);
  }

  // Initialize Bootstrap tooltips (for elements with title)
  try {
    var titleEls = [].slice.call(document.querySelectorAll('[title]'));
    titleEls.forEach(function(el){ if (!el.getAttribute('data-bs-toggle')) el.setAttribute('data-bs-toggle','tooltip'); });
    var tooltipElems = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipElems.forEach(function(el){ new bootstrap.Tooltip(el); });
  } catch (e) {
    console.warn('Tooltips init skipped:', e);
  }

  // Convert top alerts to toast notifications and show them
  try {
    var toastContainer = document.getElementById('toastContainer');
    var alerts = document.querySelectorAll('.alert');
    if (toastContainer && alerts.length) {
      alerts.forEach(function(alert){
        var level = alert.classList.contains('alert-success') ? 'success' : (alert.classList.contains('alert-danger') ? 'danger' : (alert.classList.contains('alert-warning') ? 'warning' : 'info'));
        var toast = document.createElement('div');
        toast.className = 'toast align-items-center text-bg-' + level + ' border-0 mb-2';
        toast.setAttribute('role','alert');
        toast.setAttribute('aria-live','assertive');
        toast.setAttribute('aria-atomic','true');
        var body = document.createElement('div');
        body.className = 'd-flex';
        body.innerHTML = '<div class="toast-body">' + alert.innerHTML + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>';
        toast.appendChild(body);
        toastContainer.appendChild(toast);
        var btoast = new bootstrap.Toast(toast, { delay: 4500 });
        btoast.show();
        // Remove original alert
        alert.remove();
      });
    }
  } catch (e) {
    console.warn('Toast conversion failed:', e);
  }

  // Show inline spinner only when the form actually SUBMITS (prevents "stuck" spinners
  // when a button click is intercepted or submission is cancelled).
  try {
    var _lastClickedSubmitButton = null;

    // track last clicked submit button to support browsers without event.submitter
    document.querySelectorAll('button[data-loading]').forEach(function(btn){
      btn.addEventListener('click', function(e){
        _lastClickedSubmitButton = btn;
        // clear after a short interval
        setTimeout(function(){ if (_lastClickedSubmitButton === btn) _lastClickedSubmitButton = null; }, 500);
      });
    });

    // Record initial disabled state for submit buttons so pageshow can restore only
    // buttons that were disabled by a previous submission (not those intentionally disabled).
    document.querySelectorAll('button[type="submit"]').forEach(function(btn){
      btn.dataset.initialDisabled = btn.disabled ? '1' : '0';
    });

    // Add spinner only after the submit event finishes and was NOT prevented.
    document.addEventListener('submit', function(e){
      try {
        var form = e.target;
        var submitBtn = e.submitter || _lastClickedSubmitButton || form.querySelector('button[type="submit"][data-loading]');

        // schedule after other submit handlers so we can detect preventDefault()
        setTimeout(function(){
          if (e.defaultPrevented) return; // another handler cancelled submission
          if (!submitBtn || !submitBtn.hasAttribute('data-loading')) return;

          // add spinner if not present
          if (!submitBtn.querySelector('.spinner-border')) {
            var spinner = document.createElement('span');
            spinner.className = 'spinner-border spinner-border-sm ms-2';
            spinner.setAttribute('role', 'status');
            spinner.setAttribute('aria-hidden', 'true');
            submitBtn.appendChild(spinner);
          }

          submitBtn.disabled = true;
          submitBtn.setAttribute('aria-busy', 'true');

          // disable sibling buttons inside the same .btn-group
          var grp = submitBtn.closest('.btn-group');
          if (grp) {
            grp.querySelectorAll('button').forEach(function(s){ if (s !== submitBtn) s.disabled = true; });
          }

          // disable other submit buttons in the same form
          form.querySelectorAll('button[type="submit"]').forEach(function(s){ if (s !== submitBtn) s.disabled = true; });

        }, 0);

      } catch (ex) {
        console.warn('Submit spinner init failed:', ex);
      }
    }, true);

    // Cleanup: on pageshow (including back-navigation), restore submit buttons that
    // were disabled by a previous submission but weren't intentionally disabled.
    window.addEventListener('pageshow', function(){
      document.querySelectorAll('button[type="submit"]').forEach(function(btn){
        var initial = btn.dataset.initialDisabled === '1';
        var hasSpinner = !!btn.querySelector('.spinner-border');
        var isBusyAttr = btn.getAttribute('aria-busy') === 'true';
        // nothing to do
        if (!btn.disabled && !hasSpinner && !isBusyAttr) return;
        // skip buttons that were initially disabled in the markup
        if (initial) return;

        btn.disabled = false;
        btn.removeAttribute('aria-busy');
        var sp = btn.querySelector('.spinner-border'); if (sp) sp.remove();
      });
    });

  } catch (e) {
    console.warn('Button loading spinner init failed:', e);
  }

});