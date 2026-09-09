// Ctrl+K / Cmd+K focuses the search field (Material opens the results
// dropdown as soon as you type). The old handler only worked when the
// field was already visible and did nothing on narrow viewports.
document.addEventListener("keydown", function (e) {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    var input = document.querySelector(".md-search__input");
    if (input) {
      input.focus();
      input.select();
    }
  }
});
