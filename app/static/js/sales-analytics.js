(() => {
  let data = window.rrSalesAnalyticsData;
  if (!data) return;

  const money = (value) => new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0
  }).format(Number(value || 0));
  const moneyExact = (value) => new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2
  }).format(Number(value || 0));
  const ns = 'http://www.w3.org/2000/svg';
  const colors = ['#397B50', '#68A879', '#9CCBA7', '#B9D9C0', '#2E6650', '#83B99A', '#A6C9B0', '#D0E5D5'];
  const svgNode = (name, attrs = {}) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const addText = (svg, x, y, text, attrs = {}) => {
    const node = svgNode('text', { x, y, ...attrs });
    node.textContent = text;
    svg.appendChild(node);
    return node;
  };
  const clear = (id) => {
    const el = document.getElementById(id);
    if (el) el.replaceChildren();
    return el;
  };
  const empty = (el, message = 'No sales data for this period yet.') => {
    if (el) {
      const p = document.createElement('p');
      p.className = 'sa-empty';
      p.textContent = message;
      el.appendChild(p);
    }
  };

  function renderVerticalBars(id, items) {
    const el = clear(id);
    if (!el) return;
    if (!items || !items.length) return empty(el);
    const width = 760, height = 280, left = 62, right = 18, top = 18, bottom = 58;
    const chartW = width - left - right, chartH = height - top - bottom;
    const max = Math.max(1, ...items.map((d) => Number(d.value || 0)));
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'presentation', preserveAspectRatio: 'xMidYMid meet' });
    const defs = svgNode('defs');
    const gradient = svgNode('linearGradient', { id: `${id}-green`, x1: '0', y1: '0', x2: '0', y2: '1' });
    gradient.append(svgNode('stop', { offset: '0%', 'stop-color': '#72B884' }));
    gradient.append(svgNode('stop', { offset: '100%', 'stop-color': '#34764C' }));
    defs.append(gradient); svg.append(defs);
    for (let i = 0; i <= 4; i++) {
      const y = top + chartH * i / 4;
      svg.append(svgNode('line', { x1: left, x2: width - right, y1: y, y2: y, class: 'sa-gridline' }));
      addText(svg, left - 9, y + 4, money(max * (4 - i) / 4), { class: 'sa-axis-label', 'text-anchor': 'end' });
    }
    const slot = chartW / items.length;
    const barW = Math.max(5, Math.min(42, slot * .58));
    items.forEach((item, index) => {
      const value = Number(item.value || 0);
      const barH = value / max * chartH;
      const x = left + slot * index + (slot - barW) / 2;
      const y = top + chartH - barH;
      const rect = svgNode('rect', { x, y, width: barW, height: Math.max(0, barH), rx: 5, fill: `url(#${id}-green)`, class: 'sa-bar' });
      const tip = svgNode('title'); tip.textContent = `${item.label}: ${money(value)}`; rect.append(tip); svg.append(rect);
      const showLabel = items.length <= 14 || index % Math.ceil(items.length / 12) === 0;
      if (showLabel) addText(svg, x + barW / 2, height - 27, item.label, { class: 'sa-x-label', 'text-anchor': 'middle' });
    });
    el.append(svg);
  }

  function renderLine(id, items) {
    const el = clear(id);
    if (!el) return;
    if (!items || !items.length) return empty(el);
    const width = 760, height = 280, left = 62, right = 18, top = 20, bottom = 58;
    const chartW = width - left - right, chartH = height - top - bottom;
    const max = Math.max(1, ...items.map((d) => Number(d.value || 0)));
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'presentation', preserveAspectRatio: 'xMidYMid meet' });
    for (let i = 0; i <= 4; i++) {
      const y = top + chartH * i / 4;
      svg.append(svgNode('line', { x1: left, x2: width - right, y1: y, y2: y, class: 'sa-gridline' }));
      addText(svg, left - 9, y + 4, money(max * (4 - i) / 4), { class: 'sa-axis-label', 'text-anchor': 'end' });
    }
    const points = items.map((item, i) => ({
      x: items.length === 1 ? left + chartW / 2 : left + i * chartW / (items.length - 1),
      y: top + chartH - Number(item.value || 0) / max * chartH,
      item,
    }));
    const path = points.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' ');
    svg.append(svgNode('path', { d: path, class: 'sa-line' }));
    points.forEach((point, i) => {
      const circle = svgNode('circle', { cx: point.x, cy: point.y, r: items.length > 40 ? 2.8 : 4.5, class: 'sa-point' });
      const tip = svgNode('title'); tip.textContent = `${point.item.label}: ${money(point.item.value)}`; circle.append(tip); svg.append(circle);
      const step = Math.max(1, Math.ceil(items.length / 12));
      if (i % step === 0 || i === items.length - 1) {
        addText(svg, point.x, height - 27, point.item.label, { class: 'sa-x-label', 'text-anchor': 'middle' });
      }
    });
    el.append(svg);
  }

  function renderProducts(id, items) {
    const el = clear(id);
    if (!el) return;
    if (!items || !items.length) return empty(el);
    const max = Math.max(1, ...items.map((d) => Number(d.value || 0)));
    items.forEach((item, index) => {
      const row = document.createElement('div'); row.className = 'sa-product-row';
      const name = document.createElement('span'); name.className = 'sa-product-name'; name.textContent = item.label; name.title = item.label;
      const amount = document.createElement('strong'); amount.className = 'sa-product-value'; amount.textContent = money(item.value);
      const track = document.createElement('div'); track.className = 'sa-product-track';
      const bar = document.createElement('span'); bar.className = 'sa-product-fill'; bar.style.width = `${Math.max(2, Number(item.value || 0) / max * 100)}%`; bar.style.background = colors[index % colors.length];
      track.append(bar); row.append(name, amount, track); row.title = `${item.label}: ${money(item.value)}`; el.append(row);
    });
  }

  function renderDonut(id, legendId, items) {
    const el = clear(id), legend = clear(legendId);
    if (!el || !legend) return;
    const total = (items || []).reduce((sum, item) => sum + Number(item.value || 0), 0);
    if (!items || !items.length || total <= 0) { empty(el); return; }
    const size = 220, center = 110, radius = 76, circumference = 2 * Math.PI * radius;
    const svg = svgNode('svg', { viewBox: `0 0 ${size} ${size}`, role: 'presentation' });
    svg.append(svgNode('circle', { cx: center, cy: center, r: radius, fill: 'none', stroke: '#E8F0EA', 'stroke-width': 28 }));
    let offset = 0;
    items.forEach((item, index) => {
      const length = Number(item.value || 0) / total * circumference;
      const circle = svgNode('circle', {
        cx: center, cy: center, r: radius, fill: 'none', stroke: colors[index % colors.length],
        'stroke-width': 28, 'stroke-dasharray': `${length} ${circumference - length}`,
        'stroke-dashoffset': -offset, transform: `rotate(-90 ${center} ${center})`,
      });
      const tip = svgNode('title'); tip.textContent = `${item.label}: ${money(item.value)} (${(Number(item.value) / total * 100).toFixed(1)}%)`;
      circle.append(tip); svg.append(circle); offset += length;
      const row = document.createElement('div'); row.className = 'sa-legend-item';
      const swatch = document.createElement('span'); swatch.className = 'sa-legend-swatch'; swatch.style.background = colors[index % colors.length];
      const label = document.createElement('span'); label.className = 'sa-legend-label'; label.textContent = item.label;
      const value = document.createElement('strong'); value.textContent = `${(Number(item.value) / total * 100).toFixed(1)}%`;
      row.append(swatch, label, value); legend.append(row);
    });
    const centerLabel = svgNode('text', { x: center, y: center - 2, class: 'sa-donut-total', 'text-anchor': 'middle' }); centerLabel.textContent = money(total);
    const centerSub = svgNode('text', { x: center, y: center + 19, class: 'sa-donut-caption', 'text-anchor': 'middle' }); centerSub.textContent = 'Product sales';
    svg.append(centerLabel, centerSub); el.append(svg);
  }

  function renderAll() {
    renderVerticalBars('sa-monthly-chart', data.monthly_sales);
    renderLine('sa-daily-chart', data.daily_sales);
    renderProducts('sa-products-chart', data.top_products);
    renderDonut('sa-category-chart', 'sa-category-legend', data.categories);
  }

  function updateMetrics() {
    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    setText('sa-sales-label', data.sales_label);
    setText('sa-total-sales', moneyExact(data.total_sales));
    setText('sa-total-orders', Number(data.total_orders || 0).toLocaleString('en-IN'));
    setText('sa-average-order-value', moneyExact(data.average_order_value));
    setText('sa-products-sold', Number(data.products_sold || 0).toLocaleString('en-IN'));
    setText('sa-accepted-orders', Number(data.accepted_orders || 0).toLocaleString('en-IN'));
    setText('sa-range-label', `${data.range_label} · Confirmed and fulfilled orders`);
    setText('sa-daily-title', data.daily_title);
  }

  renderAll();

  // Poll the protected dashboard endpoint once a minute so new orders and
  // status changes flow into the metrics without requiring a manual reload.
  const analyticsRoot = document.querySelector('.sales-analytics[data-refresh-url]');
  if (analyticsRoot) {
    const refresh = async () => {
      if (document.visibilityState !== 'visible') return;
      const params = new URLSearchParams({ range: data.range_key || 'month' });
      if (data.range_key === 'custom') {
        params.set('start_date', data.start_date);
        params.set('end_date', data.end_date);
      }
      try {
        const response = await fetch(`${analyticsRoot.dataset.refreshUrl}?${params.toString()}`, {
          headers: { Accept: 'application/json' }, cache: 'no-store', credentials: 'same-origin'
        });
        if (!response.ok) return;
        data = await response.json();
        updateMetrics();
        renderAll();
      } catch (_) {
        // Keep the last successful chart visible if a temporary refresh fails.
      }
    };
    window.setInterval(refresh, 60000);
  }

  const rangeSelect = document.getElementById('sa-range');
  const customDates = document.getElementById('sa-custom-dates');
  const filterForm = document.getElementById('sales-range-filter');
  const startInput = filterForm?.querySelector('input[name="start_date"]');
  const endInput = filterForm?.querySelector('input[name="end_date"]');
  const applyButton = filterForm?.querySelector('button[type="submit"]');

  function syncCustomDateControls() {
    if (!rangeSelect || !customDates) return;
    const isCustom = rangeSelect.value === 'custom';
    customDates.hidden = !isCustom;
    if (startInput) startInput.required = isCustom;
    if (endInput) endInput.required = isCustom;
  }

  function showFilterFeedback(message, isError = false) {
    let status = document.getElementById('sa-filter-feedback');
    if (!status && filterForm) {
      status = document.createElement('p');
      status.id = 'sa-filter-feedback';
      status.className = 'sa-filter-feedback';
      status.setAttribute('role', 'status');
      filterForm.insertAdjacentElement('afterend', status);
    }
    if (status) {
      status.textContent = message;
      status.dataset.state = isError ? 'error' : 'success';
      status.hidden = !message;
    }
  }

  if (rangeSelect && customDates) {
    rangeSelect.addEventListener('change', syncCustomDateControls);
    syncCustomDateControls();
  }

  if (filterForm && rangeSelect && startInput && endInput) {
    const today = new Date().toISOString().slice(0, 10);
    startInput.max = today;
    endInput.max = today;
    startInput.addEventListener('change', () => {
      endInput.min = startInput.value || '';
      if (endInput.value && startInput.value && endInput.value < startInput.value) endInput.value = startInput.value;
    });
    endInput.addEventListener('change', () => { startInput.max = endInput.value || today; });

    filterForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      syncCustomDateControls();
      const params = new URLSearchParams({ range: rangeSelect.value });
      if (rangeSelect.value === 'custom') {
        if (!startInput.value || !endInput.value) {
          showFilterFeedback('Choose both a start date and an end date.', true);
          (!startInput.value ? startInput : endInput).focus();
          return;
        }
        if (endInput.value < startInput.value) {
          showFilterFeedback('The end date must be on or after the start date.', true);
          endInput.focus();
          return;
        }
        params.set('start_date', startInput.value);
        params.set('end_date', endInput.value);
      }
      const oldLabel = applyButton?.textContent;
      if (applyButton) {
        applyButton.disabled = true;
        applyButton.textContent = 'Loading…';
        applyButton.setAttribute('aria-busy', 'true');
      }
      showFilterFeedback('Updating sales analytics…');
      try {
        const endpoint = analyticsRoot?.dataset.refreshUrl;
        if (!endpoint) throw new Error('Analytics refresh endpoint is unavailable.');
        const response = await fetch(`${endpoint}?${params.toString()}`, {
          headers: { Accept: 'application/json' }, cache: 'no-store', credentials: 'same-origin'
        });
        if (!response.ok) throw new Error('Unable to load this date range. Please try again.');
        const nextData = await response.json();
        if (rangeSelect.value === 'custom' && nextData.range_key !== 'custom') {
          throw new Error('That date range could not be applied. Check the dates and try again.');
        }
        data = nextData;
        updateMetrics();
        renderAll();
        const nextUrl = new URL(window.location.href);
        nextUrl.search = params.toString();
        window.history.replaceState({}, '', nextUrl);
        showFilterFeedback('Sales analytics updated successfully.');
      } catch (error) {
        showFilterFeedback(error.message || 'Unable to update sales analytics.', true);
      } finally {
        if (applyButton) {
          applyButton.disabled = false;
          applyButton.textContent = oldLabel || 'Apply';
          applyButton.removeAttribute('aria-busy');
        }
      }
    });
  }
})();
