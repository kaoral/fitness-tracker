(function () {
  'use strict';
  const appearance = window.PulseAppearance;
  if (!appearance) return;
  const cards = [...document.querySelectorAll('[data-chart-card]')];
  const figures = new Map();
  const chartNames = { ...appearance.get().chartNames };
  cards.forEach(card => { chartNames[card.dataset.chartCard] = card.dataset.chartTitle; });
  if (cards.length) appearance.set({ chartNames });
  document.querySelectorAll('.chart-config').forEach(script => {
    try { figures.set(script.dataset.chartTarget, JSON.parse(script.textContent)); } catch (_) { /* Keep other charts usable. */ }
  });
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function renderCharts() {
    if (!window.Plotly) {
      if (figures.size) cards.forEach(card => {
        const plot = card.querySelector('.plot-chart');
        if (plot) { plot.className = 'chart-empty'; plot.textContent = 'Charts could not load. Please check the local chart library.'; }
      });
      return;
    }
    figures.forEach((figure, id) => {
      const node = document.getElementById(id);
      if (!node || node.closest('[hidden]')) return;
      const layout = {
        ...figure.layout,
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        colorway: [css('--accent'), css('--teal'), css('--violet'), css('--amber'), '#db8299', '#86a7b5'],
        font: { family: '-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif', size: 10, color: css('--dim') },
        margin: { l: 52, r: 24, t: 15, b: 48, ...(figure.layout && figure.layout.margin) },
        autosize: true, height: node.clientHeight || 290,
        legend: { orientation: 'h', x: 0, y: 1.15, font: { size: 9, color: css('--ink2') }, ...(figure.layout && figure.layout.legend) },
        hoverlabel: { bgcolor: css('--surface2'), bordercolor: css('--border'), font: { color: css('--ink'), size: 11 } }
      };
      ['xaxis', 'yaxis', 'xaxis2', 'yaxis2'].forEach(axis => {
        if (axis.endsWith('2') && !(figure.layout && figure.layout[axis])) return;
        layout[axis] = { gridcolor: css('--border'), zeroline: false, linecolor: css('--border'), tickfont: { size: 9, color: css('--dim') }, automargin: true, ...(figure.layout && figure.layout[axis]) };
      });
      const data = figure.data.map(trace => {
        const copy = { ...trace };
        if (trace.name && /stress/i.test(trace.name)) {
          if (trace.type === 'bar') copy.marker = { ...trace.marker, color: css('--violet') };
          else { copy.line = { ...trace.line, color: css('--violet') }; copy.marker = { ...trace.marker, color: css('--violet') }; }
        }
        if (trace.name && /heart|bpm/i.test(trace.name)) copy.line = { ...trace.line, color: '#db8299' };
        if (trace.name && /sleep/i.test(trace.name)) {
          if (trace.type === 'bar') copy.marker = { ...trace.marker, color: css('--teal') };
          else copy.line = { ...trace.line, color: css('--teal') };
        }
        return copy;
      });
      window.Plotly.react(node, data, layout, { responsive: true, displaylogo: false, displayModeBar: 'hover', modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'], scrollZoom: false, toImageButtonOptions: { format: 'png', filename: id, scale: 2 } }).catch(() => {
        node.className = 'chart-empty'; node.textContent = 'This chart could not be displayed.';
      });
    });
  }
  function chartCheckbox(card) {
    const label = document.createElement('label'); label.className = 'chart-toggle';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    checkbox.checked = !appearance.get().hiddenCharts.includes(card.dataset.chartCard);
    checkbox.addEventListener('change', () => {
      const hidden = new Set(appearance.get().hiddenCharts);
      if (checkbox.checked) hidden.delete(card.dataset.chartCard); else hidden.add(card.dataset.chartCard);
      appearance.set({ hiddenCharts: [...hidden] });
    });
    const text = document.createElement('span'); text.textContent = card.dataset.chartTitle;
    label.append(checkbox, text); return label;
  }
  function updateControls() {
    const prefs = appearance.get();
    cards.forEach(card => { card.hidden = prefs.hiddenCharts.includes(card.dataset.chartCard); });
    document.querySelectorAll('[data-chart-toggles]').forEach(container => { container.replaceChildren(...cards.map(chartCheckbox)); });
    document.querySelectorAll('[data-accent-option]').forEach(input => { input.checked = input.value === prefs.accent; });
    document.querySelectorAll('[data-compact-toggle]').forEach(input => { input.checked = prefs.compact; });
    document.querySelectorAll('[data-hidden-chart-list]').forEach(container => {
      container.replaceChildren();
      if (!prefs.hiddenCharts.length) {
        const message = document.createElement('p'); message.className = 'muted-text'; message.textContent = 'No charts are hidden.'; container.append(message);
      }
      prefs.hiddenCharts.forEach(id => {
        const row = document.createElement('div'); row.className = 'hidden-chart-item';
        const label = document.createElement('span'); label.textContent = typeof prefs.chartNames[id] === 'string' ? prefs.chartNames[id] : id;
        const button = document.createElement('button'); button.className = 'btn btn-quiet'; button.type = 'button'; button.textContent = 'Show chart';
        button.addEventListener('click', () => appearance.set({ hiddenCharts: appearance.get().hiddenCharts.filter(item => item !== id) }));
        row.append(label, button); container.append(row);
      });
    });
  }
  let toastTimer;
  function toast(message) {
    const node = document.querySelector('[data-toast]'); if (!node) return;
    node.textContent = message; node.hidden = false; clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 3500);
  }
  document.querySelectorAll('[data-hide-chart]').forEach(button => button.addEventListener('click', () => {
    appearance.set({ hiddenCharts: [...new Set([...appearance.get().hiddenCharts, button.dataset.hideChart])] });
    toast('Chart hidden. Restore it with Customize charts or Appearance.');
  }));
  document.querySelectorAll('[data-restore-charts]').forEach(button => button.addEventListener('click', () => { appearance.set({ hiddenCharts: [] }); toast('All charts are visible.'); }));
  document.querySelectorAll('[data-accent-option]').forEach(input => input.addEventListener('change', () => { if (input.checked) appearance.set({ accent: input.value }); }));
  document.querySelectorAll('[data-compact-toggle]').forEach(input => input.addEventListener('change', () => appearance.set({ compact: input.checked })));
  document.querySelectorAll('[data-reset-appearance]').forEach(button => button.addEventListener('click', () => { appearance.reset(); toast('Default appearance restored.'); }));
  document.addEventListener('appearancechange', () => { updateControls(); requestAnimationFrame(renderCharts); });
  function closeSidebar() { document.documentElement.dataset.sidebarOpen = 'false'; document.querySelector('[data-sidebar-toggle]')?.setAttribute('aria-expanded', 'false'); }
  document.querySelector('[data-sidebar-toggle]')?.addEventListener('click', function () {
    const open = document.documentElement.dataset.sidebarOpen !== 'true';
    document.documentElement.dataset.sidebarOpen = String(open); this.setAttribute('aria-expanded', String(open));
  });
  document.querySelector('[data-sidebar-close]')?.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeSidebar(); document.querySelectorAll('.view-controls[open]').forEach(node => { node.open = false; }); } });
  updateControls(); renderCharts();
})();
