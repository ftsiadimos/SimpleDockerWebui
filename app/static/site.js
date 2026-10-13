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
        // Clone the alert content but strip the close button to avoid double X
        var content = alert.innerHTML.replace(/<button[^>]*btn-close[^>]*>.*?<\/button>/gi, '').trim();
        body.innerHTML = '<div class="toast-body">' + content + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>';
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

  // Initialize drag-and-drop for Quick Actions
  try {
    var quickActionsContainer = document.getElementById('quickActionsContainer');
    var draggedElement = null;
    var isDragging = false;

    // Load saved order from localStorage
    function loadActionsOrder() {
      var savedOrder = localStorage.getItem('quickActionsOrder');
      if (savedOrder) {
        try {
          var order = JSON.parse(savedOrder);
          var buttons = Array.from(quickActionsContainer.querySelectorAll('.quick-action-btn'));
          
          // Sort buttons according to saved order
          buttons.sort(function(a, b) {
            var indexA = order.indexOf(a.dataset.action);
            var indexB = order.indexOf(b.dataset.action);
            // If action not in saved order, keep original position
            if (indexA === -1) indexA = buttons.indexOf(a);
            if (indexB === -1) indexB = buttons.indexOf(b);
            return indexA - indexB;
          });
          
          // Reorder elements in the DOM
          buttons.forEach(function(btn) {
            quickActionsContainer.appendChild(btn);
          });
        } catch (e) {
          console.warn('Failed to load quick actions order:', e);
        }
      }
    }

    // Save current order to localStorage
    function saveActionsOrder() {
      var order = Array.from(quickActionsContainer.querySelectorAll('.quick-action-btn'))
        .map(function(btn) { return btn.dataset.action; });
      localStorage.setItem('quickActionsOrder', JSON.stringify(order));
    }

    // Get all drag handles and attach listeners
    function attachDragListeners() {
      var dragHandles = quickActionsContainer.querySelectorAll('.drag-handle-icon');
      
      dragHandles.forEach(function(handle) {
        handle.addEventListener('dragstart', function(e) {
          isDragging = true;
          draggedElement = this.closest('.quick-action-btn');
          draggedElement.classList.add('dragging');
          quickActionsContainer.classList.add('dragging-active');
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/html', draggedElement.innerHTML);
        });

        handle.addEventListener('dragend', function(e) {
          isDragging = false;
          if (draggedElement) {
            draggedElement.classList.remove('dragging');
          }
          quickActionsContainer.classList.remove('dragging-active');
          
          // Remove all drag-over classes
          var allBtns = quickActionsContainer.querySelectorAll('.quick-action-btn');
          allBtns.forEach(function(b) {
            b.classList.remove('drag-over', 'drag-over-bottom');
          });

          draggedElement = null;
        });
      });
    }

    // Attach listeners to buttons for dragover and drop
    function attachButtonListeners() {
      var quickActionBtns = quickActionsContainer.querySelectorAll('.quick-action-btn');
      
      quickActionBtns.forEach(function(btn) {
        btn.addEventListener('dragover', function(e) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';

          if (this === draggedElement) return;

          var rect = this.getBoundingClientRect();
          var midpoint = rect.top + rect.height / 2;

          // Remove all drag-over classes first
          quickActionBtns.forEach(function(b) {
            b.classList.remove('drag-over', 'drag-over-bottom');
          });

          // Add class based on mouse position
          if (e.clientY < midpoint) {
            this.classList.add('drag-over');
          } else {
            this.classList.add('drag-over-bottom');
          }
        });

        btn.addEventListener('dragleave', function(e) {
          this.classList.remove('drag-over', 'drag-over-bottom');
        });

        btn.addEventListener('drop', function(e) {
          e.preventDefault();
          e.stopPropagation();

          if (this === draggedElement) return;

          var rect = this.getBoundingClientRect();
          var midpoint = rect.top + rect.height / 2;
          
          var allBtns = Array.from(quickActionsContainer.querySelectorAll('.quick-action-btn'));
          var thisIndex = allBtns.indexOf(this);
          var draggedIdx = allBtns.indexOf(draggedElement);

          if (draggedIdx < thisIndex) {
            // Dragging down
            if (e.clientY < midpoint) {
              this.parentNode.insertBefore(draggedElement, this);
            } else {
              this.parentNode.insertBefore(draggedElement, this.nextSibling);
            }
          } else {
            // Dragging up
            if (e.clientY < midpoint) {
              this.parentNode.insertBefore(draggedElement, this);
            } else {
              this.parentNode.insertBefore(draggedElement, this.nextSibling);
            }
          }

          // Save the new order
          saveActionsOrder();
          
          // Re-attach listeners as DOM has changed
          attachDragListeners();
          attachButtonListeners();
        });

        // Prevent navigation if we're dragging
        btn.addEventListener('click', function(e) {
          if (isDragging) {
            e.preventDefault();
            e.stopPropagation();
          }
        });
      });
    }

    // Load the saved order on page load
    loadActionsOrder();
    attachDragListeners();
    attachButtonListeners();

  } catch (e) {
    console.warn('Quick actions drag-and-drop init failed:', e);
  }


});