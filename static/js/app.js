const CURRENCY = "ج.س";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const prefersReducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const canAnimate = () => Boolean(window.gsap && !prefersReducedMotion());

// GSAP Animation utilities - adds smooth animations to UI elements
const animate = {
  staggerFadeIn: (selector, { duration = 0.5, stagger = 0.1, y = 20, ease = "power2.out" } = {}) => {
    if (!canAnimate()) return;
    gsap.from(selector, { duration, y, opacity: 0, stagger, ease });
  },
  fadeIn: (el, { duration = 0.3, y = 0, scale = 1 } = {}) => {
    if (!canAnimate()) return;
    gsap.from(el, { duration, y, scale, opacity: 0, ease: "power2.out" });
  },
  pulse: (el, { duration = 0.4, repeat = 1, scale = 1.05 } = {}) => {
    if (!canAnimate()) return;
    gsap.to(el, { scale, duration: duration / 2, yoyo: true, repeat, ease: "sine.inOut" });
  },
  slideInRight: (el, { duration = 0.4, x = 100, ease = "power3.out" } = {}) => {
    if (!canAnimate()) return;
    gsap.from(el, { x, opacity: 0, duration, ease });
  },
  scaleIn: (el, { duration = 0.3, scale = 0.9, ease = "back.out(1.7)" } = {}) => {
    if (!canAnimate()) return;
    gsap.from(el, { scale, opacity: 0, duration, ease });
  },
  flyTo: (fromEl, toEl, { duration = 0.6, scale = 0.5, opacity = 0.7 } = {}) => {
    if (!canAnimate() || !fromEl || !toEl) return;
    const fromRect = fromEl.getBoundingClientRect();
    const toRect = toEl.getBoundingClientRect();
    gsap.to(fromEl, { x: toRect.left - fromRect.left, y: toRect.top - fromRect.top, scale, opacity, duration, ease: "power2.inOut", onComplete: () => gsap.set(fromEl, { x: 0, y: 0, scale: 1, opacity: 1 }) });
  },
  flash: (el, { color = "rgba(0,180,138,0.2)", duration = 0.3 } = {}) => {
    if (!canAnimate()) return;
    gsap.to(el, { backgroundColor: color, duration: duration / 2, yoyo: true, repeat: 1, ease: "power2.inOut" });
  },

  // Chart line drawing animation
  drawChartLine: (selector, { duration = 1.2, ease = "power2.out" } = {}) => {
    if (!canAnimate()) return;
    const chart = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!chart) return;
    const polyline = chart.querySelector('polyline');
    const polygon = chart.querySelector('polygon');
    if (polyline) {
      const length = polyline.getTotalLength();
      gsap.set(polyline, { strokeDasharray: length, strokeDashoffset: length });
      gsap.to(polyline, { strokeDashoffset: 0, duration, ease });
    }
    if (polygon) {
      gsap.from(polygon, { opacity: 0, duration: duration * 0.8, ease });
    }
  },

  // Page fade transition
  fadePageIn: (selector = 'body', { duration = 0.4, ease = "power2.out" } = {}) => {
    if (!canAnimate()) return;
    gsap.from(selector, { opacity: 0, duration, ease });
  },

  // Sidebar nav stagger
  staggerNavItems: (selector = '.nav a', { duration = 0.3, stagger = 0.05, x = -10, ease = "power2.out" } = {}) => {
    if (!canAnimate()) return;
    gsap.from(selector, { x, opacity: 0, duration, stagger, ease });
  }
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (Number(n) || 0).toLocaleString("en-US", { maximumFractionDigits: 2 });
const money = (n) => `${fmt(n)} ${CURRENCY}`;

let _cachedCsrfToken = null;

async function getCsrfToken() {
  if (_cachedCsrfToken) return _cachedCsrfToken;
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content) {
    _cachedCsrfToken = meta.content;
    return _cachedCsrfToken;
  }
  try {
    const res = await fetch("/api/csrf-token");
    if (res.ok) {
      const data = await res.json();
      _cachedCsrfToken = data.token;
      return _cachedCsrfToken;
    }
  } catch (e) {
    // ignore
  }
  return null;
}

async function api(path, opts = {}) {
  // Auto-inject CSRF token for state-changing methods
  const method = (opts.method || "GET").toUpperCase();
  const headers = typeof opts.headers === "object" && opts.headers !== null
    ? { ...opts.headers }
    : { "Content-Type": "application/json" };

  if (method !== "GET" && method !== "HEAD") {
    const token = await getCsrfToken();
    if (token) {
      headers["X-CSRFToken"] = token;
      headers["X-CSRF-Token"] = token;
    }
  }

  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 && !location.pathname.endsWith("login.html")) { location.href = "login.html"; throw new Error("unauthorized"); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 403 && data.error === "LICENSE_REQUIRED" && !location.pathname.endsWith("activate.html")) {
    location.href = "activate.html";
    throw new Error(data.message || "الترخيص مطلوب أو انتهت صلاحيته");
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  if (method !== "GET" && method !== "HEAD" && !path.startsWith("/api/sync/")) {
    setTimeout(() => { if (typeof checkSyncStatus === "function") checkSyncStatus(false, false); }, 250);
  }
  return data;
}

const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  cart: '<circle cx="9" cy="20" r="1.6"/><circle cx="17" cy="20" r="1.6"/><path d="M3 4h2l2.6 12h8.8L20 8H6"/>',
  pill: '<rect x="3" y="9" width="18" height="6" rx="3" transform="rotate(-45 12 12)"/><path d="M8.5 8.5 15.5 15.5"/>',
  truck: '<rect x="2" y="6" width="12" height="10" rx="1"/><path d="M14 9h4l3 3v4h-7z"/><circle cx="6" cy="18.5" r="1.6"/><circle cx="17" cy="18.5" r="1.6"/>',
  wallet: '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18"/><circle cx="17" cy="15" r="1.3"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c.6-3.4 2.8-5 5.5-5s4.9 1.6 5.5 5"/><circle cx="17" cy="9" r="2.4"/><path d="M16 15.2c2.3.2 4 1.7 4.5 4.8"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  bell: '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
  moon: '<path d="M20 13.5A8 8 0 1 1 10.5 4 6.5 6.5 0 0 0 20 13.5"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6.5 7l1 13h9l1-13"/>',
  edit: '<path d="M4 20h4L20 8l-4-4L4 16z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
  print: '<path d="M7 8V3h10v5"/><rect x="4" y="8" width="16" height="9" rx="1.5"/><path d="M7 14h10v7H7z"/>',
  barcode: '<g><rect x="2" y="6" width="1.5" height="12"/><rect x="4.5" y="6" width="1" height="12"/><rect x="6.5" y="6" width="2" height="12"/><rect x="9.5" y="6" width="1" height="12"/><rect x="11.5" y="6" width="1.5" height="12"/><rect x="14" y="6" width="1" height="12"/><rect x="16" y="6" width="2" height="12"/><rect x="19" y="6" width="1" height="12"/></g>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
  cash: '<rect x="2.5" y="6.5" width="19" height="11" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  alert: '<path d="M12 3 2.7 19.5h18.6z"/><path d="M12 9.5v4.5M12 17h.01"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  cross: '<path d="M6 6l12 12M18 6 6 18"/>',
  refresh: '<path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  lock: '<rect x="3" y="10" width="18" height="11" rx="2"/><path d="M7 10V7a5 5 0 0 1 10 0v3"/>',
  pause: '<path d="M6 4h4v16H6zm8 0h4v16h-4z"/>',
  play: '<path d="M5 3l14 9-14 9V3z"/>',
  tag: '<path d="M12 2H2v10l10 10 10-10L12 2z"/><circle cx="7" cy="7" r="2"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>',
  gift: '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.58 2.81.7A2 2 0 0 1 22 16.92z"/>',
  whatsapp: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  filter: '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  keyboard: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>',
  cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  wifiOff: '<line x1="2" y1="2" x2="22" y2="22"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 4.17-2.65"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M5 12.86a10 10 0 0 1 5.17-2.89"/><line x1="12" y1="20" x2="12.01" y2="20"/>',
  building: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/>',
  globe: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
};
const icon = (n, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ""}</svg>`;

const NAV_GROUPS = [
  {
    title: "المبيعات والعملاء",
    items: [
      ["index.html", "الرئيسية", "home"],
      ["pos.html", "نقطة البيع", "cart"],
      ["returns.html", "المرتجعات", "refresh"],
      ["customers.html", "العملاء", "users"],
      ["promotions.html", "العروض والخصومات", "tag"],
    ],
  },
  {
    title: "المخزون والمشتريات",
    items: [
      ["products.html", "الأدوية", "pill"],
      ["purchases.html", "المشتريات", "truck"],
      ["suppliers.html", "الموردون", "box"],
      ["adjustments.html", "تعديلات المخزون", "edit"],
      ["requests.html", "طلبات المنتجات", "bell"],
    ],
  },
  {
    title: "المالية والورديات",
    items: [
      ["shifts.html", "الورديات", "clock"],
      ["expenses.html", "المصروفات", "wallet"],
    ],
  },
  {
    title: "التقارير والإدارة",
    items: [
      ["reports.html", "التقارير", "chart"],
      ["admin.html", "الإعدادات", "gear"],
    ],
  },
];

const NAV = NAV_GROUPS.flatMap((g) => g.items);

function initTheme() {
  document.documentElement.dataset.theme = localStorage.getItem("theme") || "light";
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  localStorage.setItem("theme", t);
  $$(".theme-btn").forEach((b) => (b.innerHTML = icon(t === "dark" ? "sun" : "moon") + '<span>السمة</span>'));
}

function renderShell(active, user, title) {
  const initials = (user.full_name || user.username || "؟").trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("");
  const nowStr = new Date().toLocaleDateString("ar-EG", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  const appVersion = "2.0.0";

  const isAllowed = (href) => {
    if (href === "admin.html") return user.role === "admin";
    if (href === "promotions.html" && user.role === "sales") return false;
    if (href === "adjustments.html" && user.role === "sales") return false;
    return true;
  };

  const navHTML = NAV_GROUPS.map((group) => {
    const items = group.items.filter(([href]) => isAllowed(href));
    if (!items.length) return "";
    return `<div class="nav-group-label">${esc(group.title)}</div>` +
      items.map(([href, label, ic]) =>
        `<a href="${href}" class="${href === active ? "active" : ""}">${icon(ic)}<span>${esc(label)}</span></a>`
      ).join("");
  }).join("");

  if (!document.querySelector('link[rel*="icon"]')) {
    const fav = document.createElement("link");
    fav.rel = "icon";
    fav.href = "img/favicon.ico";
    fav.type = "image/x-icon";
    document.head.appendChild(fav);
  }

  document.body.insertAdjacentHTML("afterbegin", `
  <div class="shell">
    <div class="sidebar-overlay" id="sidebar-overlay"></div>
    <aside class="sidebar" id="sidebar">
      <div class="brand">
        <span class="logo" style="display:flex;align-items:center;justify-content:center"><img src="img/logo.png" alt="ترياق"></span>
        <div style="display:flex;flex-direction:column;gap:2px">
          <span style="font-weight:800;font-size:17px;color:#fff">تِــريَــاق</span>
          <span style="font-size:11px;color:#9E988E">نظام إدارة الصيدلية الذكي</span>
        </div>
      </div>
      <nav class="nav" aria-label="القائمة الرئيسية">${navHTML}</nav>
      <div class="side-foot">
        <div class="side-user"><span class="avatar">${esc(initials)}</span>
          <div style="display:flex;flex-direction:column;gap:2px;overflow:hidden">
            <span style="font-weight:600;color:#fff;text-overflow:ellipsis;overflow:hidden;white-space:nowrap">${esc(user.full_name || user.username)}</span>
            <span style="font-size:11px;color:#9E988E">${esc({ admin: "مدير", pharmacist: "صيدلي", sales: "بائع" }[user.role] || user.role)}</span>
          </div>
        </div>
        <div class="side-actions">
          <button type="button" class="theme-btn" onclick="toggleTheme()">${icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon")}<span>السمة</span></button>
          <button type="button" onclick="doLogout()">${icon("logout")}<span>خروج</span></button>
        </div>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <button type="button" class="hamburger" aria-label="فتح القائمة الجانبية" onclick="$('#sidebar').classList.toggle('open'); $('#sidebar-overlay')?.classList.toggle('active')">${icon("menu")}</button>
        <h1>${esc(title)}</h1>
        <div class="conn-bar" id="conn-bar">
          <button type="button" class="conn-badge online" id="conn-status-badge" onclick="checkSyncStatus(true, true)" title="انقر لفحص الاتصال بالسيرفر السحابي">
            <span class="conn-dot"></span>
            ${icon("cloud")}
            <span id="conn-status-text">متصل بالسيرفر السحابي</span>
          </button>
          <button type="button" class="sync-btn" id="sync-now-btn" onclick="syncNow()" style="display:none" title="مزامنة البيانات المحلية مع السيرفر السحابي">
            ${icon("refresh")}
            <span id="sync-now-text">مزامنة</span>
          </button>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;text-align:left">
            <span class="date" style="font-size:12px">${esc(nowStr)}</span>
            <span style="font-size:10px;color:var(--muted)">تِــريَــاق v${appVersion}</span>
        </div>
      </header>
      ${(() => {
        if (!user.warning_msg) return "";
        try { if (localStorage.getItem("dismissed_warning_" + user.id) === user.warning_msg) return ""; } catch {}
        return `<div id="admin-warning-banner" data-uid="${user.id}" data-msg="${esc(user.warning_msg)}" style="background:var(--danger);color:white;padding:10px 44px 10px 14px;text-align:center;font-weight:bold;border-radius:8px;margin:8px 16px;position:relative">⚠️ تنبيه إداري: ${esc(user.warning_msg)}<button type="button" onclick="dismissWarning()" aria-label="إغلاق التحذير" style="position:absolute;inset-inline-start:8px;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.22);border:0;color:#fff;border-radius:6px;width:24px;height:24px;cursor:pointer;font-size:16px;line-height:1">×</button></div>`;
      })()}
      <main class="content" id="content"></main>
      <footer class="app-footer">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px">
          <span>&copy; 2026 تِــريَــاق &mdash; نظام إدارة الصيدلية المتكامل</span>
          <span style="color:var(--muted)">v${appVersion}</span>
        </div>
      </footer>
    </div>
  </div>`);

  // GSAP Sidebar nav stagger animation (RTL-aware: positive x = from right)
  // Only animate on initial page load, not on navigation clicks
  if (canAnimate() && !sessionStorage.getItem('sidebarAnimated')) {
    sessionStorage.setItem('sidebarAnimated', 'true');
    gsap.from(".nav a", { x: 10, opacity: 0, duration: 0.3, stagger: 0.04, ease: "power2.out" });
    gsap.from(".brand", { x: 20, opacity: 0, duration: 0.4, ease: "power2.out" });
    gsap.from(".side-user", { y: 20, opacity: 0, duration: 0.4, delay: 0.25, ease: "power2.out" });
  }

  // Sidebar overlay click to close (mobile responsive)
  const overlay = document.getElementById("sidebar-overlay");
  const sidebar = document.getElementById("sidebar");
  if (overlay && sidebar) {
    overlay.addEventListener("click", () => {
      sidebar.classList.remove("open");
      overlay.classList.remove("active");
    });
  }

  // Also close sidebar when clicking nav links on mobile
  const navLinks = document.querySelectorAll(".nav a");
  navLinks.forEach(link => {
    link.addEventListener("click", () => {
      if (window.innerWidth <= 980) {
        sidebar.classList.remove("open");
        overlay?.classList.remove("active");
      }
    });
  });
}

async function doLogout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  location.href = "login.html";
}

function dismissWarning() {
  const b = document.getElementById("admin-warning-banner");
  if (!b) return;
  try { localStorage.setItem("dismissed_warning_" + b.dataset.uid, b.dataset.msg); } catch {}
  b.remove();
}

function showPopupAlert(msg, type = "warn", title = "") {
  return new Promise((resolve) => {
    const isError = type === "error" || type === "danger";
    const defaultTitle = isError ? "خطأ" : "تنبيه";
    const iconColor = isError ? "var(--danger)" : "var(--warn)";
    const iconSvg = ICONS.alert;

    const back = document.createElement("div");
    back.className = "modal-backdrop popup-alert-backdrop";
    back.style.zIndex = "1200";
    back.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true" style="max-width:440px; text-align:center; padding:24px 20px;">
        <div style="width:52px; height:52px; margin:0 auto 14px; border-radius:50%; background:color-mix(in srgb, ${iconColor} 15%, transparent); color:${iconColor}; display:grid; place-items:center;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:28px;height:28px">${iconSvg}</svg>
        </div>
        <h3 style="margin:0 0 10px; font-size:18px;">${esc(title || defaultTitle)}</h3>
        <p style="margin:0 0 20px; color:var(--text); line-height:1.6; word-break:break-word; font-size:14px;">${esc(msg)}</p>
        <div class="actions" style="justify-content:center; margin:0;">
          <button type="button" class="btn primary" id="popup-alert-btn" style="min-width:120px; justify-content:center;">حسناً</button>
        </div>
      </div>`;
    document.body.appendChild(back);

    if (canAnimate()) {
      gsap.from(back, { opacity: 0, duration: 0.2 });
      gsap.from(back.querySelector(".modal"), { scale: 0.9, opacity: 0, duration: 0.25, ease: "back.out(1.7)" });
    }

    let closed = false;
    const onKey = (e) => {
      if (e.key === "Escape" || e.key === "Enter") {
        e.preventDefault();
        closeAlert();
      }
    };
    document.addEventListener("keydown", onKey);

    const closeAlert = () => {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKey);
      if (canAnimate()) {
        gsap.to(back, { opacity: 0, duration: 0.18, onComplete: () => { back.remove(); resolve(); } });
      } else {
        back.remove();
        resolve();
      }
    };

    const btn = back.querySelector("#popup-alert-btn");
    btn.onclick = closeAlert;
    setTimeout(() => btn?.focus(), 30);
    back.addEventListener("click", (e) => { if (e.target === back) closeAlert(); });
  });
}

function showPopupConfirm(msg, title = "تأكيد") {
  return new Promise((resolve) => {
    const back = document.createElement("div");
    back.className = "modal-backdrop popup-confirm-backdrop";
    back.style.zIndex = "1200";
    back.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="max-width:440px; text-align:center; padding:24px 20px;">
        <div style="width:52px; height:52px; margin:0 auto 14px; border-radius:50%; background:color-mix(in srgb, var(--warn) 15%, transparent); color:var(--warn); display:grid; place-items:center;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:28px;height:28px">${ICONS.alert}</svg>
        </div>
        <h3 style="margin:0 0 10px; font-size:18px;">${esc(title)}</h3>
        <p style="margin:0 0 20px; color:var(--text); line-height:1.6; word-break:break-word; font-size:14px;">${esc(msg)}</p>
        <div class="actions" style="justify-content:center; gap:12px; margin:0;">
          <button type="button" class="btn primary" id="popup-confirm-yes" style="min-width:100px; justify-content:center;">تأكيد</button>
          <button type="button" class="btn" id="popup-confirm-no" style="min-width:100px; justify-content:center;">إلغاء</button>
        </div>
      </div>`;
    document.body.appendChild(back);

    if (canAnimate()) {
      gsap.from(back, { opacity: 0, duration: 0.2 });
      gsap.from(back.querySelector(".modal"), { scale: 0.9, opacity: 0, duration: 0.25, ease: "back.out(1.7)" });
    }

    let closed = false;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    };
    document.addEventListener("keydown", onKey);

    const finish = (result) => {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKey);
      if (canAnimate()) {
        gsap.to(back, { opacity: 0, duration: 0.18, onComplete: () => { back.remove(); resolve(result); } });
      } else {
        back.remove();
        resolve(result);
      }
    };

    const yesBtn = back.querySelector("#popup-confirm-yes");
    yesBtn.onclick = () => finish(true);
    back.querySelector("#popup-confirm-no").onclick = () => finish(false);
    setTimeout(() => yesBtn?.focus(), 30);
    back.addEventListener("click", (e) => { if (e.target === back) finish(false); });
  });
}

function showProgressRing({
  title = "معالجة العملية",
  subtitle = "",
  stages = [],
  initialPercent = 0,
  iconType = "database"
} = {}) {
  const back = document.createElement("div");
  back.className = "modal-backdrop progress-ring-backdrop";
  back.style.zIndex = "1500";

  const radius = 56;
  const circumference = +(2 * Math.PI * radius).toFixed(2); // 351.86

  const stagesHtml = stages.length > 0 ? `
    <div class="progress-ring-stages-list">
      ${stages.map((st, idx) => `
        <div class="progress-ring-stage-item ${idx === 0 ? 'active' : ''}" id="ring-stage-${idx}">
          <span class="stage-bullet"><span class="bullet-inner"></span></span>
          <span class="stage-label">${esc(typeof st === 'string' ? st : (st.label || st.text))}</span>
        </div>
      `).join("")}
    </div>
  ` : "";

  back.innerHTML = `
    <div class="modal progress-ring-modal" role="dialog" aria-modal="true">
      <div class="progress-ring-header">
        <h3 class="progress-ring-title">${esc(title)}</h3>
        ${subtitle ? `<p class="progress-ring-sub">${esc(subtitle)}</p>` : ""}
      </div>

      <div class="determinate-progress-ring-box">
        <svg class="progress-ring-svg" width="140" height="140" viewBox="0 0 140 140">
          <circle
            class="progress-ring-track"
            cx="70"
            cy="70"
            r="${radius}"
            fill="transparent"
            stroke-width="10"
          />
          <circle
            class="progress-ring-fill"
            id="ring-circle-fill"
            cx="70"
            cy="70"
            r="${radius}"
            fill="transparent"
            stroke-width="10"
            stroke-linecap="round"
            stroke-dasharray="${circumference}"
            stroke-dashoffset="${(circumference * (1 - initialPercent / 100)).toFixed(2)}"
            transform="rotate(-90 70 70)"
          />
        </svg>
        <div class="progress-ring-center">
          <span class="progress-ring-percent" id="ring-pct-text">${Math.round(initialPercent)}%</span>
          <span class="progress-ring-state-badge" id="ring-badge-text">جاري المعالجة</span>
        </div>
      </div>

      <div class="progress-ring-status-box">
        <div class="progress-ring-step-desc" id="ring-step-desc">${esc(stages[0]?.label || stages[0]?.text || stages[0] || "جاري البدء...")}</div>
        <div class="progress-ring-warning">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>يرجى عدم إغلاق الصفحة أثناء المعالجة لحماية البيانات</span>
        </div>
      </div>

      ${stagesHtml}

      <div class="progress-ring-actions" id="ring-actions" style="display:none;">
        <button type="button" class="btn primary" id="ring-close-btn" style="min-width:110px;">إغلاق</button>
      </div>
    </div>
  `;

  document.body.appendChild(back);

  if (canAnimate()) {
    gsap.from(back, { opacity: 0, duration: 0.2 });
    gsap.from(back.querySelector(".modal"), { scale: 0.9, opacity: 0, duration: 0.25, ease: "back.out(1.7)" });
  }

  const fillCircle = back.querySelector("#ring-circle-fill");
  const pctText = back.querySelector("#ring-pct-text");
  const badgeText = back.querySelector("#ring-badge-text");
  const stepDesc = back.querySelector("#ring-step-desc");
  const actionsBox = back.querySelector("#ring-actions");
  const closeBtn = back.querySelector("#ring-close-btn");

  let currentPercent = initialPercent;
  let isClosed = false;

  function updateCircle(pct) {
    pct = Math.max(0, Math.min(100, pct));
    currentPercent = pct;
    const offset = circumference * (1 - pct / 100);
    fillCircle.style.strokeDashoffset = offset.toFixed(2);
    pctText.textContent = `${Math.round(pct)}%`;
  }

  function setProgress(pct, statusMessage, stageIndex) {
    if (isClosed) return;
    updateCircle(pct);
    if (statusMessage) {
      stepDesc.textContent = statusMessage;
    }
    if (typeof stageIndex === "number" && stages.length > 0) {
      stages.forEach((_, idx) => {
        const item = back.querySelector(`#ring-stage-${idx}`);
        if (!item) return;
        if (idx < stageIndex) {
          item.className = "progress-ring-stage-item done";
        } else if (idx === stageIndex) {
          item.className = "progress-ring-stage-item active";
        } else {
          item.className = "progress-ring-stage-item";
        }
      });
    }
  }

  function setSuccess(message) {
    if (isClosed) return;
    updateCircle(100);
    fillCircle.classList.add("success");
    pctText.classList.add("success");
    badgeText.textContent = "اكتمل بنجاح";
    badgeText.classList.add("success");
    stepDesc.innerHTML = `<span style="color:var(--ok);font-weight:700;">✓ ${esc(message || "اكتملت العملية بنجاح!")}</span>`;
    if (stages.length > 0) {
      stages.forEach((_, idx) => {
        const item = back.querySelector(`#ring-stage-${idx}`);
        if (item) item.className = "progress-ring-stage-item done";
      });
    }
  }

  function setError(errorMessage) {
    if (isClosed) return;
    fillCircle.classList.add("error");
    pctText.classList.add("error");
    badgeText.textContent = "فشلت العملية";
    badgeText.classList.add("error");
    stepDesc.innerHTML = `<span style="color:var(--danger);font-weight:700;">⛔ ${esc(errorMessage || "حدث خطأ أثناء تنفيذ العملية")}</span>`;
    actionsBox.style.display = "flex";
  }

  function close(immediate = false) {
    if (isClosed) return Promise.resolve();
    isClosed = true;
    return new Promise((resolve) => {
      if (!immediate && canAnimate()) {
        gsap.to(back, {
          opacity: 0,
          duration: 0.2,
          onComplete: () => {
            back.remove();
            resolve();
          }
        });
      } else {
        back.remove();
        resolve();
      }
    });
  }

  closeBtn.onclick = () => close();

  return {
    setProgress,
    setSuccess,
    setError,
    close,
    element: back
  };
}

async function runWithDeterminateRing({
  title,
  subtitle,
  iconType,
  stages = [],
  action,
  successMessage,
  holdSuccessMs = 1200
}) {
  const initialPct = stages[0]?.pct || 15;
  const ring = showProgressRing({
    title,
    subtitle,
    stages,
    iconType,
    initialPercent: initialPct
  });

  let currentStageIdx = 0;
  let simulatedPct = initialPct;
  let isDone = false;

  const timer = setInterval(() => {
    if (isDone) return;
    if (currentStageIdx < stages.length - 1) {
      const nextStage = stages[currentStageIdx + 1];
      const maxForStage = (nextStage.pct || 90) - 2;
      if (simulatedPct < maxForStage && simulatedPct < 90) {
        simulatedPct += Math.random() * 3.5 + 1.8;
        if (simulatedPct >= (nextStage.pct || 90) - 4) {
          currentStageIdx++;
          simulatedPct = stages[currentStageIdx]?.pct || simulatedPct;
        }
        ring.setProgress(
          simulatedPct,
          stages[currentStageIdx]?.label || stages[currentStageIdx]?.text || stages[currentStageIdx],
          currentStageIdx
        );
      }
    }
  }, 190);

  try {
    const result = await action((pct, msg) => {
      simulatedPct = pct;
      ring.setProgress(pct, msg);
    });

    isDone = true;
    clearInterval(timer);

    ring.setSuccess(successMessage || "تمت العملية بنجاح!");
    await new Promise(r => setTimeout(r, holdSuccessMs));
    await ring.close();
    return result;
  } catch (err) {
    isDone = true;
    clearInterval(timer);
    ring.setError(err.message || String(err));
    throw err;
  }
}

window.showProgressRing = showProgressRing;
window.runWithDeterminateRing = runWithDeterminateRing;

// Override standard alert
window.alert = function(msg) {
  showPopupAlert(msg, "warn");
};

function toast(msg, type = "ok") {
  if (type === "error" || type === "danger") {
    showPopupAlert(msg, type);
    return;
  }
  const normalizedType = type === "warning" ? "warn" : type;
  let wrap = $(".toast-wrap");
  if (!wrap) { wrap = document.createElement("div"); wrap.className = "toast-wrap"; document.body.appendChild(wrap); }
  const el = document.createElement("div");
  el.className = `toast ${normalizedType === "ok" ? "" : normalizedType}`;
  el.textContent = msg;
  wrap.appendChild(el);
  if (canAnimate()) {
    gsap.from(el, { x: 100, opacity: 0, duration: 0.35, ease: "power3.out" });
    gsap.to(el, { opacity: 0, duration: 0.3, delay: 3.2, onComplete: () => el.remove() });
  } else {
    setTimeout(() => el.remove(), 3500);
  }
}

function modal(title, bodyHTML, onSubmit, okLabel = "حفظ") {
  const hasSubmit = typeof onSubmit === "function";
  const back = document.createElement("div");
  back.className = "modal-backdrop";
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><h3>${esc(title)}</h3><form id="modal-form">${bodyHTML}
    <div class="actions"><button type="submit" class="btn primary" id="modal-ok">${esc(okLabel)}</button>
    <button type="button" class="btn" id="modal-cancel" style="${hasSubmit ? "" : "display:none"}">إلغاء</button></div></form></div>`;
  document.body.appendChild(back);
  if (canAnimate()) {
    gsap.from(back, { opacity: 0, duration: 0.2 });
    gsap.from(back.querySelector(".modal"), { scale: 0.92, opacity: 0, duration: 0.25, ease: "back.out(1.5)" });
  }
  let closed = false;
  const onKey = (e) => {
    if (e.key === "Escape") {
      const backdrops = $$(".modal-backdrop");
      if (backdrops[backdrops.length - 1] === back) {
        e.preventDefault();
        close();
      }
    }
  };
  document.addEventListener("keydown", onKey);
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    if (canAnimate()) {
      gsap.to(back, { opacity: 0, duration: 0.18, onComplete: () => back.remove() });
    } else {
      back.remove();
    }
  };
  back.closeModal = close;
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  $("#modal-cancel", back).onclick = close;
  $("#modal-form", back).onsubmit = async (e) => {
    e.preventDefault();
    if (hasSubmit) {
      const okBtn = $("#modal-ok", back);
      const fd = Object.fromEntries(new FormData(e.target).entries());
      if (okBtn) okBtn.disabled = true;
      try {
        await onSubmit(fd);
        close();
      } catch (err) {
        if (okBtn) okBtn.disabled = false;
        toast(err.message, "error");
      }
    } else {
      close();
    }
  };
  return back;
}

function tableHTML(cols, rows, emptyMsg = "لا توجد بيانات") {
  if (!rows.length) return `<div class="empty">${esc(emptyMsg)}</div>`;
  return `<div class="table-wrap"><table><thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
  <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// Skeleton helpers for loading states
function tableSkeletonHTML(cols = 5, rows = 5) {
  const colCount = typeof cols === "number" ? cols : (cols.length || 5);
  const widths = ["65%", "45%", "80%", "55%", "70%", "35%", "90%"];
  const headers = Array.from({ length: colCount }, (_, i) => `<th><span class="skeleton-bone skeleton-shimmer" style="width:${widths[i % widths.length]}; height:14px"></span></th>`).join("");
  const bodyRows = Array.from({ length: rows }, (_, r) => `<tr>${Array.from({ length: colCount }, (_, c) => `<td><span class="skeleton-bone skeleton-shimmer" style="width:${widths[(r + c) % widths.length]}; height:14px"></span></td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${headers}</tr></thead><tbody>${bodyRows}</tbody></table></div>`;
}

function cardSkeletonHTML(count = 4) {
  return Array.from({ length: count }, () => `
    <div class="card kpi" style="pointer-events:none">
      <span class="ico skeleton-bone circle skeleton-shimmer" style="width:44px; height:44px"></span>
      <div style="flex:1">
        <span class="skeleton-bone skeleton-shimmer" style="width:50%; height:12px; margin-bottom:8px; display:block"></span>
        <span class="skeleton-bone skeleton-shimmer" style="width:75%; height:24px; display:block"></span>
      </div>
    </div>
  `).join("");
}

function posTilesSkeletonHTML(count = 8) {
  return Array.from({ length: count }, () => `
    <div class="prod-tile" style="pointer-events:none">
      <span class="skeleton-bone skeleton-shimmer" style="width:80%; height:16px; margin-bottom:8px; display:block"></span>
      <span class="skeleton-bone skeleton-shimmer" style="width:45%; height:18px; margin-bottom:6px; display:block"></span>
      <span class="skeleton-bone skeleton-shimmer" style="width:60%; height:13px; margin-bottom:8px; display:block"></span>
      <span class="skeleton-bone skeleton-shimmer" style="width:100%; height:26px; border-radius:8px; margin-top:auto; display:block"></span>
    </div>
  `).join("");
}


function lineChart(el, pts) {
  const w = 560, h = 230, p = 34;
  const max = Math.max(...pts.map((d) => d.value), 1);
  const xs = (i) => p + (i * (w - 2 * p)) / Math.max(pts.length - 1, 1);
  const ys = (v) => h - p - (v / max) * (h - 2 * p);
  const line = pts.map((d, i) => `${xs(i)},${ys(d.value)}`).join(" ");
  el.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${w} ${h}" dir="ltr">
    <polygon points="${p},${h - p} ${line} ${xs(pts.length - 1)},${h - p}" fill="var(--primary)" opacity=".12"/>
    <polyline points="${line}" fill="none" stroke="var(--primary)" stroke-width="2.5"/>
    ${pts.map((d, i) => `<circle cx="${xs(i)}" cy="${ys(d.value)}" r="3.5" fill="var(--primary)"/>`).join("")}
    ${pts.map((d, i) => `<text x="${xs(i)}" y="${h - 10}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(d.label)}</text>`).join("")}
    ${[0.25, 0.5, 0.75, 1].map((f) => `<line x1="${p}" x2="${w - p}" y1="${ys(max * f)}" y2="${ys(max * f)}" stroke="var(--border)" stroke-dasharray="3 4"/>
      <text x="${p - 6}" y="${ys(max * f) + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(max * f)}</text>`).join("")}
  </svg>`;

  // GSAP chart drawing animation
  if (canAnimate()) {
    const polyline = el.querySelector('polyline');
    const polygon = el.querySelector('polygon');
    const circles = el.querySelectorAll('circle');

    if (polyline) {
      const length = polyline.getTotalLength();
      gsap.set(polyline, { strokeDasharray: length, strokeDashoffset: length });
      gsap.to(polyline, { strokeDashoffset: 0, duration: 1.2, ease: "power2.out" });
    }
    if (polygon) {
      gsap.from(polygon, { opacity: 0, duration: 1 });
    }
    circles.forEach((circle, i) => {
      gsap.from(circle, { scale: 0, duration: 0.3, delay: 1 + i * 0.05, ease: "back.out(1.7)" });
    });
  }
}

function updateSyncUI(st) {
  const badge = document.getElementById("conn-status-badge");
  const syncBtn = document.getElementById("sync-now-btn");
  if (!badge || !syncBtn) return;

  const browserOnline = typeof navigator !== "undefined" ? navigator.onLine !== false : true;
  const supaOnline = Boolean(st && st.supabase_online && browserOnline);
  const offlineMode = Boolean(st && st.offline_mode) || !supaOnline;
  const dirty = Boolean(st && st.dirty);

  badge.classList.remove("online", "offline", "pending-sync");

  if (!supaOnline) {
    badge.classList.add("offline");
    badge.innerHTML = `<span class="conn-dot"></span>${icon("wifiOff")}<span id="conn-status-text">أوفلاين — عمل محلي</span>`;
    badge.title = "لا يوجد اتصال بالسيرفر حالياً — يعمل النظام محلياً بدون توقف";
    syncBtn.style.display = "inline-flex";
    const t = document.getElementById("sync-now-text");
    if (t) t.textContent = "مزامنة";
  } else if (offlineMode || dirty) {
    badge.classList.add("pending-sync");
    badge.innerHTML = `<span class="conn-dot"></span>${icon("cloud")}<span id="conn-status-text">عاد الاتصال — بانتظار المزامنة</span>`;
    badge.title = "السيرفر متصل وتوجد بيانات محلية جاهزة للمزامنة";
    syncBtn.style.display = "inline-flex";
    const t = document.getElementById("sync-now-text");
    if (t) t.textContent = "مزامنة الآن";
  } else {
    badge.classList.add("online");
    badge.innerHTML = `<span class="conn-dot"></span>${icon("cloud")}<span id="conn-status-text">متصل بالسيرفر السحابي</span>`;
    badge.title = st && st.last_sync ? `متصل بالسيرفر السحابي — آخر مزامنة: ${st.last_sync}` : "متصل بالسيرفر السحابي";
    syncBtn.style.display = "none";
  }
}

async function checkSyncStatus(force = false, notify = false) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    updateSyncUI({ supabase_online: false, offline_mode: true, dirty: true });
    if (notify) toast("لا يوجد اتصال بالإنترنت — النظام يعمل محلياً", "warn");
    return;
  }
  try {
    const st = await api(`/api/sync/status${force ? "?force=1" : ""}`);
    updateSyncUI(st);
    if (notify) {
      if (st.supabase_online && !st.offline_mode && !st.dirty) {
        toast("متصل بالسيرفر السحابي بنجاح");
      } else if (st.supabase_online && (st.offline_mode || st.dirty)) {
        toast("السيرفر متصل — اضغط زر مزامنة لرفع البيانات المحلية", "warn");
      } else {
        toast("السيرفر غير متصل — النظام يعمل محلياً", "warn");
      }
    }
    return st;
  } catch (e) {
    updateSyncUI({ supabase_online: false, offline_mode: true, dirty: false });
  }
}

async function syncNow() {
  const syncBtn = document.getElementById("sync-now-btn");
  if (syncBtn) {
    syncBtn.disabled = true;
    syncBtn.classList.add("spinning");
  }

  try {
    const res = await runWithDeterminateRing({
      title: "المزامنة السحابية الفورية",
      subtitle: "مزامنة البيانات المحلية مع السيرفر السحابي المركزي",
      iconType: "database",
      stages: [
        { pct: 20, label: "فحص الاتصال وتجميع السجلات غير المزامنة" },
        { pct: 50, label: "تشفير ونقل فواتير المبيعات وحركات المخزون" },
        { pct: 80, label: "سحب أحدث الأسعار وبيانات الأدوية من السيرفر" },
        { pct: 100, label: "اكتملت المزامنة وتحديث البيانات بنجاح" }
      ],
      successMessage: "تمت المزامنة مع السيرفر بنجاح!",
      holdSuccessMs: 1400,
      action: async () => {
        return await api("/api/sync/now", { method: "POST" });
      }
    });

    toast(res.message || "تمت المزامنة مع السيرفر بنجاح");
    await checkSyncStatus(true, false);
    if (res.direction === "push" || res.direction === "pull") {
      setTimeout(() => location.reload(), 600);
    }
  } catch (err) {
    toast(err.message || "تعذرت المزامنة — تأكد من الاتصال بالإنترنت", "error");
    await checkSyncStatus(true, false);
  } finally {
    if (syncBtn) {
      syncBtn.disabled = false;
      syncBtn.classList.remove("spinning");
    }
  }
}

// Universal iframe printing (never blocked by popup blockers)
window.printHtml = (html) => {
  let iframe = document.getElementById("print-iframe");
  if (!iframe) {
    iframe = document.createElement("iframe");
    iframe.id = "print-iframe";
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.style.visibility = "hidden";
    document.body.appendChild(iframe);
  }
  const doc = iframe.contentWindow.document;
  doc.open();
  doc.write(html);
  doc.close();
  setTimeout(() => {
    try {
      iframe.contentWindow.focus();
      iframe.contentWindow.print();
    } catch (e) {
      console.error("Print error:", e);
    }
  }, 350);
};

async function boot(title, fn) {
  initTheme();
  let user;
  try { user = (await api("/api/me")).user; } catch { return; }
  renderShell(location.pathname.split("/").pop() || "index.html", user, title);
  checkSyncStatus(false, false);
  setInterval(() => checkSyncStatus(false, false), 20000);
  window.addEventListener("online", () => checkSyncStatus(true, true));
  window.addEventListener("offline", () => {
    updateSyncUI({ supabase_online: false, offline_mode: true, dirty: false });
    toast("انقطع الاتصال بالإنترنت — يستمر النظام بالعمل محلياً", "warn");
  });
  try { await fn(user, $("#content")); } catch (e) { toast(e.message, "error"); }

  // If there is an active admin warning for this user, show it as a pop-up modal
  if (user && user.warning_msg) {
    try {
      if (sessionStorage.getItem("seen_warning_" + user.id) !== user.warning_msg) {
        sessionStorage.setItem("seen_warning_" + user.id, user.warning_msg);
        showPopupAlert(user.warning_msg, "error", "⚠️ تنبيه إداري");
      }
    } catch {}
  }

  // Page fade-in animation
  if (canAnimate()) {
    gsap.from($("body"), { opacity: 0, duration: 0.3, ease: "power2.out" });
  }
}

// ==========================================================================
// Camera Barcode & QR Code Scanner
// ==========================================================================
function playScanBeep() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(1200, ctx.currentTime);
    gain.gain.setValueAtTime(0.18, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.12);
  } catch (e) {}
}

async function loadScriptAsync(src) {
  if (window.Html5Qrcode) return;
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[src*="html5-qrcode"]');
    if (existing) {
      if (window.Html5Qrcode) return resolve();
      existing.addEventListener("load", resolve);
      existing.addEventListener("error", reject);
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("فشل تحميل مكتبة قارئ الكاميرا"));
    document.head.appendChild(script);
  });
}

window.openCameraScanner = async function openCameraScanner(callback, options = {}) {
  const title = options.title || "مسح الباركود / QR بالكاميرا";
  const readerId = "camera-scanner-box-" + Date.now();
  
  const back = document.createElement("div");
  back.className = "modal-backdrop";
  back.style.zIndex = "10001";
  back.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" style="max-width:440px; width:95%; text-align:center; padding:18px 20px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <h3 style="margin:0; font-size:16px; display:inline-flex; align-items:center; gap:8px;">
          ${icon("camera")} <span>${esc(title)}</span>
        </h3>
        <button type="button" class="btn ghost sm" id="scanner-close-x" style="padding:4px 8px; font-size:16px;" title="إغلاق">${icon("cross")}</button>
      </div>

      <div class="scanner-viewport-box" id="scanner-viewport">
        <div id="${readerId}" style="width:100%; height:100%;"></div>
        <div class="scanner-laser" id="scanner-laser"></div>
        <div class="scanner-guide-box"></div>
        <div id="scanner-loading" style="position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:#fff; background:#0b0f19;">
          <svg class="spin" style="width:28px; height:28px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          <span style="font-size:13px;">جاري تشغيل الكاميرا...</span>
        </div>
      </div>

      <div id="scanner-error" style="display:none; font-size:12px; color:var(--danger); background:color-mix(in srgb, var(--danger) 10%, transparent); border:1px solid var(--danger); border-radius:8px; padding:10px; margin-bottom:12px; text-align:start;"></div>

      <div style="display:flex; justify-content:center; gap:8px; margin-bottom:14px; flex-wrap:wrap;">
        <button type="button" class="btn sm" id="btn-camera-flip" style="display:none;">${icon("refresh")} <span>تبديل الكاميرا</span></button>
        <button type="button" class="btn sm" id="btn-camera-torch" style="display:none;">${icon("sun")} <span>الفلاش</span></button>
        <button type="button" class="btn sm" id="btn-camera-file">${icon("upload")} <span>مسح من صورة</span></button>
        <input type="file" id="camera-file-input" accept="image/*" style="display:none;">
      </div>

      <div style="display:flex; gap:8px;">
        <button type="button" class="btn primary" id="btn-camera-close" style="flex:1;">إلغاء</button>
      </div>
    </div>
  `;
  document.body.appendChild(back);

  let html5QrCode = null;
  let isStopped = false;
  let availableCameras = [];
  let currentCamIdx = 0;
  let isTorchOn = false;

  const stopAndClean = async () => {
    if (isStopped) return;
    isStopped = true;
    if (html5QrCode) {
      try {
        if (html5QrCode.isScanning) {
          await html5QrCode.stop();
        }
        html5QrCode.clear();
      } catch (e) {}
    }
    back.remove();
  };

  $("#scanner-close-x", back).onclick = stopAndClean;
  $("#btn-camera-close", back).onclick = stopAndClean;
  back.addEventListener("click", (e) => { if (e.target === back) stopAndClean(); });

  const onKey = (e) => {
    if (e.key === "Escape") {
      stopAndClean();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);

  // File upload scan option
  const fileInp = $("#camera-file-input", back);
  const btnFile = $("#btn-camera-file", back);
  btnFile.onclick = () => fileInp.click();
  fileInp.onchange = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      if (!html5QrCode) {
        await loadScriptAsync("/js/html5-qrcode.min.js");
        html5QrCode = new Html5Qrcode(readerId);
      }
      const res = await html5QrCode.scanFile(file, true);
      if (res) {
        playScanBeep();
        await stopAndClean();
        callback(res);
        toast(`تم المسح من الصورة: ${res}`, "ok");
      }
    } catch (err) {
      toast("لم يتم العثور على باركود أو رمز QR في هذه الصورة", "error");
    }
  };

  // Start live camera
  try {
    await loadScriptAsync("/js/html5-qrcode.min.js");
    if (!window.Html5Qrcode) throw new Error("تعذر تحميل مكونات قارئ الكاميرا");

    html5QrCode = new Html5Qrcode(readerId);

    const onScanSuccess = async (decodedText) => {
      if (isStopped) return;
      playScanBeep();
      await stopAndClean();
      callback(decodedText);
    };

    const config = {
      fps: 15,
      qrbox: (viewfinderWidth, viewfinderHeight) => {
        const minEdge = Math.min(viewfinderWidth, viewfinderHeight);
        const edge = Math.floor(minEdge * 0.75);
        return { width: edge, height: edge };
      },
      aspectRatio: 1.0,
    };

    try {
      availableCameras = await Html5Qrcode.getCameras();
    } catch (e) {}

    const flipBtn = $("#btn-camera-flip", back);
    if (availableCameras && availableCameras.length > 1) {
      flipBtn.style.display = "inline-flex";
      flipBtn.onclick = async () => {
        if (isStopped) return;
        try {
          if (html5QrCode.isScanning) await html5QrCode.stop();
          currentCamIdx = (currentCamIdx + 1) % availableCameras.length;
          $("#scanner-loading", back).style.display = "flex";
          await html5QrCode.start(availableCameras[currentCamIdx].id, config, onScanSuccess, () => {});
          $("#scanner-loading", back).style.display = "none";
        } catch (err) {
          console.error("Camera switch error:", err);
        }
      };
    }

    try {
      await html5QrCode.start({ facingMode: "environment" }, config, onScanSuccess, () => {});
    } catch (envErr) {
      try {
        if (availableCameras && availableCameras.length > 0) {
          await html5QrCode.start(availableCameras[0].id, config, onScanSuccess, () => {});
        } else {
          await html5QrCode.start({ facingMode: "user" }, config, onScanSuccess, () => {});
        }
      } catch (camErr) {
        throw camErr;
      }
    }

    $("#scanner-loading", back).style.display = "none";

    const torchBtn = $("#btn-camera-torch", back);
    try {
      const caps = html5QrCode.getRunningTrackCapabilities();
      if (caps && caps.torch) {
        torchBtn.style.display = "inline-flex";
        torchBtn.onclick = async () => {
          try {
            isTorchOn = !isTorchOn;
            await html5QrCode.applyVideoConstraints({ advanced: [{ torch: isTorchOn }] });
            torchBtn.classList.toggle("primary", isTorchOn);
          } catch (e) {}
        };
      }
    } catch (e) {}

  } catch (err) {
    console.error("Camera scanner init failed:", err);
    $("#scanner-loading", back).style.display = "none";
    $("#scanner-laser", back).style.display = "none";
    const errBox = $("#scanner-error", back);
    errBox.style.display = "block";

    const isSecure = location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1";
    if (!isSecure) {
      errBox.innerHTML = `
        <strong>⚠️ قيود أمان المتصفح:</strong><br>
        يتطلب تشغيل الكاميرا المباشرة اتصالاً مشفراً (HTTPS) أو فتح النظام عبر localhost.<br>
        يمكنك استخدام زر <b>"مسح من صورة"</b> أدناه لالتقاط صورة أو اختيارها من جهازك مباشرة.
      `;
    } else if (err.name === "NotAllowedError" || String(err).includes("Permission")) {
      errBox.innerHTML = `
        <strong>⚠️ لم يتم السماح للكاميرا:</strong><br>
        يرجى إعطاء الإذن للمتصفح لاستخدام الكاميرا ثم إعادة المحاولة، أو استخدم زر <b>"مسح من صورة"</b>.
      `;
    } else {
      errBox.innerHTML = `
        <strong>⚠️ تعذر تشغيل الكاميرا:</strong> ${esc(err.message || String(err))}<br>
        يمكنك مسح الباركود عبر زر <b>"مسح من صورة"</b>.
      `;
    }
  }
};
