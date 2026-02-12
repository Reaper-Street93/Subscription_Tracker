const THEME_KEY = "subtracker-theme";
const LIGHT = "light";
const DARK = "dark";

function currentTheme() {
  return document.documentElement.classList.contains("theme-light") ? LIGHT : DARK;
}

function applyTheme(theme) {
  if (theme === LIGHT) {
    document.documentElement.classList.add("theme-light");
  } else {
    document.documentElement.classList.remove("theme-light");
  }
}

function labelForTheme(theme) {
  return theme === DARK ? "Light mode" : "Dark mode";
}

function updateToggleButtons() {
  const theme = currentTheme();
  const nextLabel = labelForTheme(theme);
  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    button.textContent = nextLabel;
    button.setAttribute("aria-label", `Switch to ${nextLabel.toLowerCase()}`);
  }
}

function persistTheme(theme) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (_error) {
    // Ignore persistence failures and keep runtime theme.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  updateToggleButtons();

  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    button.addEventListener("click", () => {
      const nextTheme = currentTheme() === DARK ? LIGHT : DARK;
      applyTheme(nextTheme);
      persistTheme(nextTheme);
      updateToggleButtons();
    });
  }
});
