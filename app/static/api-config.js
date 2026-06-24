(function () {
  const rawBase = String(window.WC_API_BASE_URL || "").trim().replace(/\/+$/, "");

  window.wcApiUrl = function wcApiUrl(path) {
    const value = String(path || "");
    if (!value || /^https?:\/\//i.test(value)) return value;
    if (!rawBase) return value;
    return `${rawBase}${value.startsWith("/") ? value : `/${value}`}`;
  };
})();
