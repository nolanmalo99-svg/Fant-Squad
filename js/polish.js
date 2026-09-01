// ============================================================
// FANT SQUAD — site-wide polish
// reveal-on-scroll, animated underlines, count-up numbers
// Vanilla, dependency-free, prefers-reduced-motion aware.
// ============================================================
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var body = document.body;
    if (!body.classList.contains('polish')) return;

    // Auto-tag common blocks as reveal targets if not already tagged
    var autoSelectors = ['.section', '.card', '.summary-card', '.award-card', '.gold-line'];
    autoSelectors.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        if (!el.classList.contains('reveal') && !el.closest('#gate-overlay')) {
          // gold-line animates itself; others reveal
          if (el.classList.contains('gold-line')) return;
          el.classList.add('reveal');
        }
      });
    });

    var revealEls = document.querySelectorAll('.polish .reveal');
    var goldLines = document.querySelectorAll('.polish .gold-line');
    var counts = document.querySelectorAll('.polish .countup[data-target]');

    if (reduce || !('IntersectionObserver' in window)) {
      revealEls.forEach(function (el) { el.classList.add('in'); });
      goldLines.forEach(function (el) { el.classList.add('in'); });
      counts.forEach(function (el) { el.textContent = el.getAttribute('data-target'); });
      return;
    }

    var ro = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); ro.unobserve(e.target); }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    revealEls.forEach(function (el) { ro.observe(el); });
    goldLines.forEach(function (el) { ro.observe(el); });

    // Count-up numbers
    if (counts.length) {
      var co = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          co.unobserve(e.target);
          var el = e.target;
          var target = parseFloat(el.getAttribute('data-target'));
          var decimals = (el.getAttribute('data-decimals') || '0') | 0;
          var suffix = el.getAttribute('data-suffix') || '';
          var dur = 900, start = null;
          function step(ts) {
            if (start === null) start = ts;
            var p = Math.min((ts - start) / dur, 1);
            var eased = 1 - Math.pow(1 - p, 3);
            el.textContent = (target * eased).toFixed(decimals) + suffix;
            if (p < 1) requestAnimationFrame(step);
            else el.textContent = target.toFixed(decimals) + suffix;
          }
          requestAnimationFrame(step);
        });
      }, { threshold: 0.6 });
      counts.forEach(function (el) { co.observe(el); });
    }
  });
})();
