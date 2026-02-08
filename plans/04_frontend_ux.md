# Plan 04 — Frontend & UX Polish

> **Agent Role:** Frontend Agent
> **Priority:** P2 (Medium)
> **Est. Effort:** 2-3 sessions
> **Dependencies:** Plan 01 (auth) — need login page after auth is implemented

## Context

Bubble has 11 template pages with functional but basic UX. The graph visualization (`transaction_flow.html`) was recently rewritten with vis.js and supports big data (100K+ nodes, clustering, edge aggregation, summary panel). Other pages need UX love. There's no login UI, no error pages, and the dashboard has TigerGraph stubs. The design uses a dark theme with Tailwind-style CSS.

## Objectives

### 1. Login & Auth UI
*Depends on Plan 01 completion*
- [ ] Create `templates/login.html` — email/password form, JWT token storage in `localStorage`
- [ ] Add JS auth interceptor in `templates/base.html`:
  - Attach `Authorization: Bearer <token>` to all `fetch()` calls
  - On 401 response, redirect to `/login`
  - On token expiry, attempt refresh before redirect
- [ ] Add logout button to navbar in `base.html`
- [ ] Add user display (email/role) in navbar
- [ ] Create `templates/admin/users.html` — user management (admin only)

### 2. Error & Loading States
- [ ] Create `templates/errors/404.html` — styled 404 page
- [ ] Create `templates/errors/500.html` — styled 500 page
- [ ] Register Flask error handlers in `app.py` for 404, 500, 401, 403
- [ ] Add loading skeletons to all pages that fetch data on load:
  - `dashboard.html` — skeleton for stat cards
  - `investigations.html` — skeleton for table rows
  - `cases.html` — skeleton for case cards
- [ ] Add empty-state illustrations (like the graph empty-state SVG) to all list pages

### 3. Dashboard Improvements
- [ ] Fix `static/js/dashboard.js` line ~162 — remove TigerGraph stats placeholder
- [ ] Add real stats to dashboard:
  - Total cases / active investigations
  - ML model accuracy + last training date
  - Recent alerts from monitor
  - Transfer volume (last 24h / 7d / 30d)
- [ ] Add mini chart (sparkline) for transfer volume trend
- [ ] Add "Quick Actions" panel: Start Investigation, Classify Wallet, View Reports

### 4. Investigation Detail UX
- [ ] `investigation_detail.html` — add progress indicator for skill execution (currently polls)
  - Convert polling to a visual stepper: Import → Trace → Expand → Classify → Assess → Report
  - Show green checkmarks for completed steps, spinner for in-progress
- [ ] Add "View Graph" button that links to `/graph?investigation_id=X`
- [ ] Add wallet role badges with colors matching graph ROLE_COLORS
- [ ] Add transfer count + volume summary per wallet in the wallet list

### 5. Graph Visualization Enhancements
- [ ] Add **timeline slider** below graph — filter edges by timestamp range
  - Use `vis.js` `DataView` with dynamic filter
  - Slider shows edge timestamp distribution as histogram
- [ ] Add **search box** — type address to highlight/focus that node
- [ ] Add **path finder** — select two nodes, highlight shortest path between them
  - Use BFS on edge list client-side
- [ ] Add **screenshot/export** button — export graph as PNG using `vis.js` `canvas.toDataURL()`
- [ ] Add **fullscreen toggle** — expand graph container to viewport

### 6. Responsive Design
- [ ] Test all pages at 1024px, 768px, 480px breakpoints
- [ ] Add responsive nav: hamburger menu on mobile
- [ ] Make graph container responsive — 100% width on mobile
- [ ] Table scroll on small screens (horizontal scroll for wide tables)
- [ ] Touch support for graph: pinch-zoom, swipe-pan

### 7. Notification System
- [ ] Upgrade `showNotification()` in `base.html`:
  - Stack multiple notifications (max 3 visible)
  - Auto-dismiss after 5s for info, persist for errors
  - Add "View Details" link for error notifications
- [ ] Add WebSocket connection for real-time alerts from monitor
  - Use Flask-SocketIO or SSE (Server-Sent Events)
  - Show toast when new alert fires

## Constraints

- Keep the dark theme consistent (`#0f172a` backgrounds, `#e2e8f0` text)
- No React/Vue — stay with Jinja2 templates + vanilla JS
- vis.js is the graph library — do not replace it
- CSS lives in `static/styles/layout.css` — keep it consolidated
- `templates/base.html` is the layout — all pages extend it
- Use `showNotification()` for user feedback (already exists globally)

## Success Criteria

- [ ] Login flow works: login page → JWT → protected pages
- [ ] 404/500 pages are styled (not white Flask error pages)
- [ ] Dashboard shows real stats (no placeholder text)
- [ ] Investigation skill progress shows visual stepper
- [ ] Graph has search, path finder, and export buttons
- [ ] Pages are usable on 768px tablet width
- [ ] Notifications stack and auto-dismiss

## Key Files

| File | Action |
|------|--------|
| `templates/login.html` | Create |
| `templates/errors/404.html` | Create |
| `templates/errors/500.html` | Create |
| `templates/base.html` | Modify — auth interceptor, logout, user display |
| `templates/dashboard.html` | Modify — real stats, sparklines |
| `templates/investigation_detail.html` | Modify — skill stepper |
| `templates/visualizations/transaction_flow.html` | Modify — timeline, search, path finder |
| `static/js/dashboard.js` | Modify — remove TG stubs, add real stats |
| `static/styles/layout.css` | Modify — responsive breakpoints |
| `app.py` | Modify — error handlers |
