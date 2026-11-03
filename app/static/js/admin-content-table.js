document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('content-table');
  if (!table) return;
  const body = table.querySelector('tbody');
  const rows = [...body.querySelectorAll('tr')].filter(row => row.querySelector('td'));
  const search = document.getElementById('content-search');
  const status = document.getElementById('content-status');
  const sort = document.getElementById('content-sort');
  const size = document.getElementById('content-page-size');
  const prev = document.getElementById('content-prev');
  const next = document.getElementById('content-next');
  const label = document.getElementById('content-page-label');
  let page = 0, filtered = rows;
  const value = (row, index) => row.cells[index]?.textContent.trim().toLowerCase() || '';
  const render = () => {
    const q = search.value.trim().toLowerCase();
    const state = status.value;
    filtered = rows.filter(row => {
      const text = row.textContent.toLowerCase();
      const isActive = /active|published/i.test(value(row, 2));
      return text.includes(q) && (!state || (state === 'active' ? isActive : !isActive));
    });
    const key = sort.value;
    const col = key === 'status' ? 2 : key === 'order' ? 3 : 0;
    filtered.sort((a,b) => value(a,col).localeCompare(value(b,col), undefined, {numeric:true}));
    const perPage = Number(size.value) || 10;
    const pages = Math.max(1, Math.ceil(filtered.length / perPage));
    page = Math.min(page, pages - 1);
    rows.forEach(row => { row.hidden = true; });
    filtered.slice(page * perPage, (page + 1) * perPage).forEach(row => { row.hidden = false; body.appendChild(row); });
    label.textContent = filtered.length ? `Page ${page + 1} of ${pages} · ${filtered.length} items` : 'No matching items';
    prev.disabled = page === 0; next.disabled = page >= pages - 1;
  };
  [search,status,sort,size].forEach(el => el.addEventListener(el === search ? 'input' : 'change', () => { page = 0; render(); }));
  prev.addEventListener('click', () => { page--; render(); });
  next.addEventListener('click', () => { page++; render(); });
  render();
});
