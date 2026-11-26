(() => {
  // Show the custom date inputs only when "Custom" is chosen.
  const range = document.getElementById('sa-range');
  const dates = document.getElementById('sa-custom-dates');
  if (range && dates) {
    const sync = () => {
      const custom = range.value === 'custom';
      dates.hidden = !custom;
      dates.querySelectorAll('input[type="date"]').forEach((input) => { input.required = custom; });
    };
    range.addEventListener('change', sync);
    sync();
  }

  // The numbers arrive as a JSON data block: inline scripts are blocked by the site's CSP.
  let data = null;
  const holder = document.getElementById('sa-data');
  if (holder) {
    try { data = JSON.parse(holder.textContent); } catch (e) { data = null; }
  }
  if (!data) return;

  const money = (value) => new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0
  }).format(Number(value || 0));
  const moneyExact = (value) => new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2
  }).format(Number(value || 0));
  const ns = 'http://www.w3.org/2000/svg';
  // One palette for every chart: forest green (brand) + warm/cool earth tones, all readable on white.
  const PALETTE = ['#245C3A', '#D9A441', '#3F7CAC', '#C0553A', '#7A5C99', '#4FA38F', '#8A8F5C', '#B07A5B', '#6B7F8E', '#A3B8A0'];
  const OTHER_COLOUR = '#B8C2BB';
  const STATUS_COLOURS = {
    placed: '#D9A441', confirmed: '#3F7CAC', packed: '#4FA38F', shipped: '#7A5C99',
    out_for_delivery: '#8A8F5C', delivered: '#245C3A', rejected: '#C0553A', cancelled: '#B07A5B',
    return_requested: '#6B7F8E', returned: '#8F9AA3', refunded: '#A3B8A0'
  };
  const PAYMENT_COLOURS = { cod: '#245C3A', online: '#3F7CAC', upi_manual: '#D9A441' };
  const BAR_COLOUR = '#2F7A4E', BAR_HOVER = '#245C3A';

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
  const empty = (el, message = 'No data for this period yet.') => {
    if (!el) return;
    const p = document.createElement('p');
    p.className = 'sa-empty';
    p.textContent = message;
    el.appendChild(p);
  };
  const compact = (value) => {
    const v = Number(value || 0);
    if (v >= 1e7) return `₹${+(v / 1e7).toFixed(1)}Cr`;
    if (v >= 1e5) return `₹${+(v / 1e5).toFixed(1)}L`;
    if (v >= 1e3) return `₹${+(v / 1e3).toFixed(1)}k`;
    return `₹${Math.round(v)}`;
  };
  const pctOf = (part, total) => (total > 0 ? `${(part / total * 100).toFixed(1)}%` : '0%');
  const niceMax = (max) => {
    if (max <= 0) return 1;
    const pow = 10 ** Math.floor(Math.log10(max));
    const n = max / pow;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
  };

  // ---- Tooltip (one shared element; built with textContent so names can never inject markup) ----
  const tip = document.getElementById('sa-tip');
  const showTip = (x, y, title, lines) => {
    if (!tip) return;
    tip.replaceChildren();
    const head = document.createElement('strong');
    head.textContent = title;
    tip.append(head);
    lines.forEach((line) => { const p = document.createElement('span'); p.textContent = line; tip.append(p); });
    tip.hidden = false;
    const pad = 12, w = tip.offsetWidth, h = tip.offsetHeight;
    let left = x + 14, top = y - h - 12;
    if (left + w + pad > window.innerWidth) left = x - w - 14;
    if (left < pad) left = pad;
    if (top < pad) top = y + 18;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hideTip = () => { if (tip) tip.hidden = true; };
  const bindTip = (node, title, lines, { onEnter, onLeave } = {}) => {
    const anchor = () => { const r = node.getBoundingClientRect(); return [r.left + r.width / 2, r.top]; };
    node.addEventListener('pointerenter', (e) => { onEnter && onEnter(); showTip(e.clientX, e.clientY, title, lines); });
    node.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, title, lines));
    node.addEventListener('pointerleave', () => { onLeave && onLeave(); hideTip(); });
    node.addEventListener('focus', () => { onEnter && onEnter(); const [x, y] = anchor(); showTip(x, y, title, lines); });
    node.addEventListener('blur', () => { onLeave && onLeave(); hideTip(); });
  };
  document.addEventListener('pointerdown', (e) => { if (!e.target.closest('.sa-chart-card')) hideTip(); });
  window.addEventListener('scroll', hideTip, { passive: true });

  // ---- Vertical bar chart (revenue per day/week/month) ----
  function renderBars(id, items) {
    const el = clear(id);
    if (!el) return;
    if (!items || !items.length || !items.some((d) => Number(d.value) > 0)) return empty(el, 'No revenue in this period yet.');
    const width = Math.max(260, Math.round(el.clientWidth || 600));
    const height = width < 480 ? 230 : 280;
    const left = width < 480 ? 46 : 56, right = 10, top = 14, bottom = 34;
    const chartW = width - left - right, chartH = height - top - bottom;
    const max = niceMax(Math.max(...items.map((d) => Number(d.value || 0))));
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'presentation' });
    for (let i = 0; i <= 4; i++) {
      const y = top + chartH * i / 4;
      svg.append(svgNode('line', { x1: left, x2: width - right, y1: y, y2: y, class: 'sa-gridline' }));
      addText(svg, left - 8, y + 3.5, compact(max * (4 - i) / 4), { class: 'sa-axis-label', 'text-anchor': 'end' });
    }
    const slot = chartW / items.length;
    const barW = Math.max(3, Math.min(40, slot * 0.64));
    const labelEvery = Math.max(1, Math.ceil(items.length / Math.max(2, Math.floor(chartW / 54))));
    items.forEach((item, index) => {
      const value = Number(item.value || 0);
      const barH = value > 0 ? Math.max(2, value / max * chartH) : 0;
      const cx = left + slot * index + slot / 2;
      const x = cx - barW / 2, y = top + chartH - barH;
      const group = svgNode('g', { class: 'sa-bar-group', tabindex: 0, 'aria-label': `${item.label}: ${money(value)}` });
      const hit = svgNode('rect', { x: left + slot * index, y: top, width: slot, height: chartH, class: 'sa-hit' });
      const bar = svgNode('rect', { x, y, width: barW, height: barH, rx: Math.min(4, barW / 2), fill: BAR_COLOUR, class: 'sa-bar' });
      group.append(hit, bar);
      svg.append(group);
      const lines = [`Revenue: ${moneyExact(value)}`];
      if (item.orders !== undefined) lines.push(`Orders: ${Number(item.orders).toLocaleString('en-IN')}`);
      bindTip(group, item.label, lines, {
        onEnter: () => bar.setAttribute('fill', BAR_HOVER),
        onLeave: () => bar.setAttribute('fill', BAR_COLOUR)
      });
      if (index % labelEvery === 0) addText(svg, cx, height - 12, item.label, { class: 'sa-x-label', 'text-anchor': 'middle' });
    });
    el.append(svg);
  }

  // ---- Horizontal bars (top products) ----
  function renderProducts(id, items) {
    const el = clear(id);
    if (!el) return;
    if (!items || !items.length) return empty(el, 'No product sales in this period yet.');
    const max = Math.max(1, ...items.map((d) => Number(d.value || 0)));
    const total = (data.categories || []).reduce((sum, c) => sum + Number(c.value || 0), 0)
      || items.reduce((sum, c) => sum + Number(c.value || 0), 0);
    const list = document.createElement('div');
    list.className = 'sa-hbars';
    items.forEach((item, index) => {
      const value = Number(item.value || 0);
      const row = document.createElement('div');
      row.className = 'sa-hbar'; row.tabIndex = 0;
      const rank = document.createElement('span'); rank.className = 'sa-hbar-rank'; rank.textContent = String(index + 1);
      const name = document.createElement('span'); name.className = 'sa-hbar-name'; name.textContent = item.label;
      const amount = document.createElement('strong'); amount.className = 'sa-hbar-value'; amount.textContent = money(value);
      const track = document.createElement('span'); track.className = 'sa-hbar-track';
      const fill = document.createElement('span'); fill.className = 'sa-hbar-fill';
      fill.style.width = `${Math.max(2, value / max * 100)}%`;
      track.append(fill);
      row.append(rank, name, amount, track);
      list.append(row);
      bindTip(row, item.label, [`Sales: ${moneyExact(value)}`, `${pctOf(value, total)} of product sales`]);
    });
    el.append(list);
  }

  // ---- Donut chart with centre total, hover/focus tooltips and a synced legend ----
  const polar = (cx, cy, r, angle) => [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  function renderDonut(id, legendId, items, opts) {
    const el = clear(id), legend = clear(legendId);
    if (!el || !legend) return;
    let rows = (items || []).filter((d) => Number(d.value) > 0);
    const total = rows.reduce((sum, d) => sum + Number(d.value), 0);
    if (!rows.length || total <= 0) return empty(el, opts.emptyText);
    if (rows.length > 8) { // keep the legend readable: fold the long tail into "Other"
      const rest = rows.slice(7);
      rows = rows.slice(0, 7).concat([{ label: 'Other', value: rest.reduce((s, d) => s + Number(d.value), 0), other: true }]);
    }
    rows = rows.map((d, i) => ({ ...d, colour: d.other ? OTHER_COLOUR : (opts.colourFor ? opts.colourFor(d, i) : PALETTE[i % PALETTE.length]) }));

    const size = 200, c = size / 2, r = 74, sw = 28;
    const svg = svgNode('svg', { viewBox: `0 0 ${size} ${size}`, role: 'presentation', class: 'sa-donut-svg' });
    svg.append(svgNode('circle', { cx: c, cy: c, r, fill: 'none', stroke: '#EDF2EE', 'stroke-width': sw }));
    const centreValue = addText(svg, c, c + 2, opts.centre(total), { class: 'sa-donut-total', 'text-anchor': 'middle' });
    const centreCaption = addText(svg, c, c + 20, opts.caption, { class: 'sa-donut-caption', 'text-anchor': 'middle' });
    const resetCentre = () => { centreValue.textContent = opts.centre(total); centreCaption.textContent = opts.caption; };

    const segs = [], legendRows = [];
    const setActive = (idx) => {
      segs.forEach((s, i) => s && s.classList.toggle('is-dim', idx !== null && i !== idx));
      legendRows.forEach((l, i) => l.classList.toggle('is-active', idx === i));
      if (idx === null) resetCentre();
      else { centreValue.textContent = pctOf(rows[idx].value, total); centreCaption.textContent = rows[idx].label.length > 16 ? `${rows[idx].label.slice(0, 15)}…` : rows[idx].label; }
    };
    const GAP = rows.length > 1 ? 0.035 : 0;
    let angle = -Math.PI / 2;
    rows.forEach((d, i) => {
      const frac = Number(d.value) / total, sweep = frac * Math.PI * 2;
      let seg;
      if (rows.length === 1) {
        seg = svgNode('circle', { cx: c, cy: c, r, fill: 'none', stroke: d.colour, 'stroke-width': sw });
      } else {
        const a0 = angle + GAP / 2, a1 = angle + sweep - GAP / 2;
        const [x0, y0] = polar(c, c, r, a0), [x1, y1] = polar(c, c, r, Math.max(a0 + 0.001, a1));
        seg = svgNode('path', { d: `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`, fill: 'none', stroke: d.colour, 'stroke-width': sw });
      }
      seg.setAttribute('class', 'sa-seg'); seg.setAttribute('tabindex', '0');
      seg.setAttribute('aria-label', `${d.label}: ${opts.fmt(d)} (${pctOf(d.value, total)})`);
      svg.append(seg); segs[i] = seg;
      angle += sweep;

      const li = document.createElement('li'); li.className = 'sa-dlegend-item'; li.tabIndex = 0;
      const swatch = document.createElement('span'); swatch.className = 'sa-dlegend-swatch'; swatch.style.background = d.colour; swatch.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span'); label.className = 'sa-dlegend-label'; label.textContent = d.label;
      const val = document.createElement('span'); val.className = 'sa-dlegend-value'; val.textContent = `${opts.fmt(d)} · ${pctOf(d.value, total)}`;
      li.append(swatch, label, val); legendRows[i] = li;

      const lines = [opts.fmt(d), `${pctOf(d.value, total)} of ${opts.of}`].concat(opts.extra ? opts.extra(d) : []);
      const handlers = { onEnter: () => setActive(i), onLeave: () => setActive(null) };
      bindTip(seg, d.label, lines, handlers);
      bindTip(li, d.label, lines, handlers);
    });
    const ul = document.createElement('ul'); ul.className = 'sa-dlegend-list';
    legendRows.forEach((li) => ul.append(li));
    legend.append(ul);
    el.append(svg);
  }

  const orderFmt = (d) => `${Number(d.value).toLocaleString('en-IN')} order${Number(d.value) === 1 ? '' : 's'}`;

  function renderAll() {
    renderBars('sa-monthly-chart', data.monthly_sales);
    renderBars('sa-daily-chart', data.daily_sales);
    renderProducts('sa-products-chart', data.top_products);
    renderDonut('sa-status-chart', 'sa-status-legend', data.status_breakdown, {
      colourFor: (d, i) => STATUS_COLOURS[d.key] || PALETTE[i % PALETTE.length],
      centre: (t) => t.toLocaleString('en-IN'), caption: 'orders', fmt: orderFmt, of: 'all orders', emptyText: 'No orders in this period yet.'
    });
    renderDonut('sa-payment-chart', 'sa-payment-legend', data.payment_methods, {
      colourFor: (d, i) => PAYMENT_COLOURS[d.key] || PALETTE[i % PALETTE.length],
      centre: (t) => t.toLocaleString('en-IN'), caption: 'orders', fmt: orderFmt, of: 'accepted orders',
      extra: (d) => (d.sales !== undefined ? [`Sales: ${moneyExact(d.sales)}`] : []), emptyText: 'No accepted orders in this period yet.'
    });
    renderDonut('sa-category-chart', 'sa-category-legend', data.categories, {
      centre: compact, caption: 'sales', fmt: (d) => moneyExact(d.value), of: 'product sales', emptyText: 'No category sales in this period yet.'
    });
  }

  // Redraw the SVG bar charts when the container width changes (rotation, window resize, sidebar toggle).
  let lastWidth = 0, resizeFrame = 0;
  const onResize = () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      const w = document.getElementById('sa-monthly-chart')?.clientWidth || 0;
      if (Math.abs(w - lastWidth) < 4) return;
      lastWidth = w; hideTip();
      renderBars('sa-monthly-chart', data.monthly_sales);
      renderBars('sa-daily-chart', data.daily_sales);
    });
  };
  window.addEventListener('resize', onResize);

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
  lastWidth = document.getElementById('sa-monthly-chart')?.clientWidth || 0;

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

  const resetButton = document.getElementById('sa-reset-range');
  if (resetButton && filterForm) resetButton.addEventListener('click', () => {
    rangeSelect.value = 'month';
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    syncCustomDateControls();
    filterForm.requestSubmit();
  });
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
