(() => {
  document.querySelectorAll('[data-bar-value]').forEach((bar) => {
    const value = Math.max(0, Math.min(100, Number.parseInt(bar.dataset.barValue || '0', 10)));
    bar.style.setProperty('--bar', `${value}%`);
  });

  document.querySelectorAll('[data-stock-stepper]').forEach((form) => {
    const input = form.querySelector('input[name="qty"]');
    form.querySelectorAll('[data-step]').forEach((button) => button.addEventListener('click', () => {
      const current = Number.parseInt(input.value || '0', 10);
      input.value = String(Math.max(0, Math.min(1000000, (Number.isFinite(current) ? current : 0) + Number(button.dataset.step))));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }));
  });

  const search = document.getElementById('faq-search');
  if (search) {
    const cards = [...document.querySelectorAll('[data-faq]')];
    const groups = [...document.querySelectorAll('.ops-faq-group')];
    const empty = document.getElementById('faq-empty');
    search.addEventListener('input', () => {
      const term = search.value.trim().toLocaleLowerCase();
      let visible = 0;
      cards.forEach((card) => {
        const match = !term || card.textContent.toLocaleLowerCase().includes(term);
        card.hidden = !match;
        if (match) visible += 1;
      });
      groups.forEach((group) => { group.hidden = !group.querySelector('[data-faq]:not([hidden])'); });
      empty.hidden = visible > 0;
    });
  }
})();
