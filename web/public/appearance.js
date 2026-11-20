'use strict';

{
  const appearance = document.getElementById('appearance');
  const appearanceKey = 'daf.appearance';
  const themes = new Set(['light', 'dark', 'system']);
  function applyAppearance(value) {
    const theme = themes.has(value) ? value : 'system';
    appearance.value = theme;
    document.documentElement.dataset.theme = theme;
  }
  try {
    applyAppearance(localStorage.getItem(appearanceKey));
  } catch {
    applyAppearance('system');
  }
  appearance.addEventListener('change', () => {
    applyAppearance(appearance.value);
    try {
      localStorage.setItem(appearanceKey, appearance.value);
    } catch {
      // The current tab still supports appearance changes when storage is blocked.
    }
  });
  window.addEventListener('storage', (event) => {
    if (event.key === appearanceKey || event.key === null) applyAppearance(event.newValue);
  });
}
