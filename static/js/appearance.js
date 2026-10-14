/* Browser-local preferences. Broken or blocked storage falls back to defaults. */
(function () {
  'use strict';
  const key = 'fitness-tracker:appearance:v1';
  const defaults = { accent: 'blue', compact: false, hiddenCharts: [], chartNames: {} };
  let preferences = { ...defaults };
  try {
    const stored = JSON.parse(localStorage.getItem(key) || 'null');
    if (stored && typeof stored === 'object') {
      preferences.accent = ['blue', 'lavender', 'teal'].includes(stored.accent) ? stored.accent : 'blue';
      preferences.compact = stored.compact === true;
      preferences.hiddenCharts = Array.isArray(stored.hiddenCharts) ? stored.hiddenCharts.filter(id => typeof id === 'string').slice(0, 100) : [];
      preferences.chartNames = stored.chartNames && typeof stored.chartNames === 'object' && !Array.isArray(stored.chartNames) ? stored.chartNames : {};
    }
  } catch (_) { /* Private browsing or invalid saved preferences. */ }
  function apply() {
    document.documentElement.dataset.accent = preferences.accent;
    document.documentElement.dataset.compact = String(preferences.compact);
  }
  function save() {
    apply();
    try { localStorage.setItem(key, JSON.stringify(preferences)); } catch (_) { /* Preferences still work for this page. */ }
    document.dispatchEvent(new CustomEvent('appearancechange'));
  }
  window.PulseAppearance = {
    get: () => preferences,
    set: (changes) => { preferences = { ...preferences, ...changes }; save(); },
    reset: () => { preferences = { ...defaults, hiddenCharts: [], chartNames: {} }; save(); }
  };
  apply();
})();
