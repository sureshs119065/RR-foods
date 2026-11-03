document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[enctype="multipart/form-data"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.XMLHttpRequest || !form.querySelector('input[type="file"]')?.files?.length) return;
      event.preventDefault();
      const bar = document.createElement('progress'); bar.max = 100; bar.value = 0;
      bar.setAttribute('aria-label', 'Upload progress'); bar.className = 'upload-progress';
      form.appendChild(bar);
      const xhr = new XMLHttpRequest();
      xhr.open(form.method || 'POST', form.action || location.href);
      xhr.upload.addEventListener('progress', e => { if (e.lengthComputable) bar.value = Math.round(e.loaded / e.total * 100); });
      xhr.addEventListener('load', () => { if (xhr.status >= 200 && xhr.status < 400) location.href = xhr.responseURL || location.href; else { bar.remove(); alert('Upload failed. Please check the file and try again.'); } });
      xhr.addEventListener('error', () => { bar.remove(); alert('Upload failed. Check your connection and try again.'); });
      xhr.send(new FormData(form));
    });
  });
});
