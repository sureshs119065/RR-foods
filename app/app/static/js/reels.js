(() => {
  const dialog = document.getElementById('reel-dialog');
  if (!dialog) return;
  const player = dialog.querySelector('video');
  const previews = [...document.querySelectorAll('[data-reel-preview]')];
  previews.forEach(video => { video.src = video.dataset.reelPreview; });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      const video = entry.target;
      if (entry.isIntersecting && entry.intersectionRatio > .55) video.play().catch(() => {});
      else video.pause();
    }), { threshold: [.15, .55, .85] });
    previews.forEach(video => observer.observe(video));
  }
  document.querySelectorAll('[data-reel-open]').forEach(button => {
    button.addEventListener('click', () => {
      previews.forEach(video => video.pause());
      player.src = button.dataset.video;
      dialog.showModal();
      player.play().catch(() => {});
      if (player.requestFullscreen) player.requestFullscreen().catch(() => {});
    });
  });
  const close = () => {
    player.pause(); if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
    player.removeAttribute('src'); player.load(); dialog.close();
    previews.forEach(video => {
      const rect = video.getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < window.innerHeight) video.play().catch(() => {});
    });
  };
  dialog.querySelector('[data-reel-close]').addEventListener('click', close);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && dialog.open) close(); });
})();
