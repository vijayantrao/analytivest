// Applies the saved theme before first paint (kept in a file so the page can forbid inline scripts).
try { var t = localStorage.getItem('stockiq-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
