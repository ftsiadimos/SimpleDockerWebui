document.addEventListener('DOMContentLoaded', function(){
  var sidebar = document.getElementById('sidebar');

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

});