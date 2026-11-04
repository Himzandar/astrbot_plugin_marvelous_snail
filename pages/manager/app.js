const bridge = window.AstrBotPluginPage;
const THEME_STORAGE_KEY = "snail-manager-theme";

const state = {
  bootstrap: null,
  users: [],
  pending: [],
  filter: "all",
  query: "",
  activeService: "signin",
  loading: false,
  syncing: false,
  activeQQ: "",
  detailToken: 0,
  clockOffset: 0,
  themePreference: "auto",
  drawerCloseTimer: null,
  lastFocusedElement: null,
  mutating: false,
  editor: { mode: "create", qq: "", index: 0 },
  dialogCloseTimer: null,
  lastDialogFocus: null,
  strategyEditor: { mode: "create", kind: "author", name: "", target: "" },
  strategyDialogCloseTimer: null,
  lastStrategyDialogFocus: null,
  signinPushEditor: { mode: "create", original: "" },
  signinPushDialogCloseTimer: null,
  lastSigninPushFocus: null,
  articlesToken: 0,
  articlesCloseTimer: null,
  lastArticlesFocus: null,
  confirmResolver: null,
  confirmCloseTimer: null,
  lastConfirmFocus: null,
};

const els = {
  versionBadge: document.getElementById("versionBadge"),
  lastUpdated: document.getElementById("lastUpdated"),
  serviceTabs: document.getElementById("serviceTabs"),
  signinTab: document.getElementById("signinTab"),
  strategyTab: document.getElementById("strategyTab"),
  signinView: document.getElementById("signinView"),
  strategyView: document.getElementById("strategyView"),
  signinTabCount: document.getElementById("signinTabCount"),
  strategyTabCount: document.getElementById("strategyTabCount"),
  themeBtn: document.getElementById("themeBtn"),
  themeLabel: document.getElementById("themeLabel"),
  refreshBtn: document.getElementById("refreshBtn"),
  syncBtn: document.getElementById("syncBtn"),
  statusBanner: document.getElementById("statusBanner"),
  statusBannerText: document.getElementById("statusBannerText"),
  dismissBannerBtn: document.getElementById("dismissBannerBtn"),
  statUsers: document.getElementById("statUsers"),
  statUsersHint: document.getElementById("statUsersHint"),
  statAccounts: document.getElementById("statAccounts"),
  statRoles: document.getElementById("statRoles"),
  statRolesHint: document.getElementById("statRolesHint"),
  statRate: document.getElementById("statRate"),
  statRateHint: document.getElementById("statRateHint"),
  rateBar: document.getElementById("rateBar"),
  statAttention: document.getElementById("statAttention"),
  statAttentionHint: document.getElementById("statAttentionHint"),
  statPending: document.getElementById("statPending"),
  statPendingHint: document.getElementById("statPendingHint"),
  userSummary: document.getElementById("userSummary"),
  searchInput: document.getElementById("searchInput"),
  filterPills: document.getElementById("filterPills"),
  countAll: document.getElementById("countAll"),
  countHealthy: document.getElementById("countHealthy"),
  countAttention: document.getElementById("countAttention"),
  countPending: document.getElementById("countPending"),
  countUnknown: document.getElementById("countUnknown"),
  userList: document.getElementById("userList"),
  pendingSummary: document.getElementById("pendingSummary"),
  pendingCount: document.getElementById("pendingCount"),
  pendingList: document.getElementById("pendingList"),
  pendingRoles: document.getElementById("pendingRoles"),
  pendingDue: document.getElementById("pendingDue"),
  pendingExpired: document.getElementById("pendingExpired"),
  schedulerPill: document.getElementById("schedulerPill"),
  runtimeChecks: document.getElementById("runtimeChecks"),
  jobCount: document.getElementById("jobCount"),
  jobList: document.getElementById("jobList"),
  autoSignProgress: document.getElementById("autoSignProgress"),
  strategyStatAuthors: document.getElementById("strategyStatAuthors"),
  strategyStatAuthorsHint: document.getElementById("strategyStatAuthorsHint"),
  strategyStatArticles: document.getElementById("strategyStatArticles"),
  strategyStatArticlesHint: document.getElementById("strategyStatArticlesHint"),
  strategyStatTargets: document.getElementById("strategyStatTargets"),
  strategyStatTargetsHint: document.getElementById("strategyStatTargetsHint"),
  strategyStatJob: document.getElementById("strategyStatJob"),
  strategyStatJobHint: document.getElementById("strategyStatJobHint"),
  strategyAuthorSummary: document.getElementById("strategyAuthorSummary"),
  strategyAuthorCount: document.getElementById("strategyAuthorCount"),
  strategyAuthorList: document.getElementById("strategyAuthorList"),
  strategyHealthPill: document.getElementById("strategyHealthPill"),
  strategyChecks: document.getElementById("strategyChecks"),
  strategyJobCount: document.getElementById("strategyJobCount"),
  strategyJobList: document.getElementById("strategyJobList"),
  strategyPushSummary: document.getElementById("strategyPushSummary"),
  strategyPushCount: document.getElementById("strategyPushCount"),
  strategyPushList: document.getElementById("strategyPushList"),
  drawerBackdrop: document.getElementById("drawerBackdrop"),
  userDrawer: document.getElementById("userDrawer"),
  drawerTitle: document.getElementById("drawerTitle"),
  drawerSubtitle: document.getElementById("drawerSubtitle"),
  drawerCloseBtn: document.getElementById("drawerCloseBtn"),
  drawerBody: document.getElementById("drawerBody"),
  mutationPill: document.getElementById("mutationPill"),
  addBindingBtn: document.getElementById("addBindingBtn"),
  addStrategyAuthorBtn: document.getElementById("addStrategyAuthorBtn"),
  addStrategyPushBtn: document.getElementById("addStrategyPushBtn"),
  bindingBackdrop: document.getElementById("bindingBackdrop"),
  bindingDialog: document.getElementById("bindingDialog"),
  bindingDialogTitle: document.getElementById("bindingDialogTitle"),
  bindingDialogSubtitle: document.getElementById("bindingDialogSubtitle"),
  bindingCloseBtn: document.getElementById("bindingCloseBtn"),
  bindingForm: document.getElementById("bindingForm"),
  bindingQQ: document.getElementById("bindingQQ"),
  bindingGame: document.getElementById("bindingGame"),
  bindingAccount: document.getElementById("bindingAccount"),
  bindingRole: document.getElementById("bindingRole"),
  bindingInfo: document.getElementById("bindingInfo"),
  bindingInfoHint: document.getElementById("bindingInfoHint"),
  bindingAccountRequired: document.getElementById("bindingAccountRequired"),
  bindingRoleRequired: document.getElementById("bindingRoleRequired"),
  bindingAccountHint: document.getElementById("bindingAccountHint"),
  bindingFormHint: document.getElementById("bindingFormHint"),
  bindingCancelBtn: document.getElementById("bindingCancelBtn"),
  bindingSubmitBtn: document.getElementById("bindingSubmitBtn"),
  strategyBackdrop: document.getElementById("strategyBackdrop"),
  strategyDialog: document.getElementById("strategyDialog"),
  strategyDialogTitle: document.getElementById("strategyDialogTitle"),
  strategyDialogSubtitle: document.getElementById("strategyDialogSubtitle"),
  strategyCloseBtn: document.getElementById("strategyCloseBtn"),
  strategyForm: document.getElementById("strategyForm"),
  strategyAuthorFields: document.getElementById("strategyAuthorFields"),
  strategyPushFields: document.getElementById("strategyPushFields"),
  strategyAuthorName: document.getElementById("strategyAuthorName"),
  strategyAuthorFakeid: document.getElementById("strategyAuthorFakeid"),
  strategyFakeidRequired: document.getElementById("strategyFakeidRequired"),
  strategyFakeidHint: document.getElementById("strategyFakeidHint"),
  strategyPushPlatform: document.getElementById("strategyPushPlatform"),
  strategyPushKind: document.getElementById("strategyPushKind"),
  strategyPushTarget: document.getElementById("strategyPushTarget"),
  strategyFormHint: document.getElementById("strategyFormHint"),
  strategyCancelBtn: document.getElementById("strategyCancelBtn"),
  strategySubmitBtn: document.getElementById("strategySubmitBtn"),
  signinGiftForm: document.getElementById("signinGiftForm"),
  signinGiftMode: document.getElementById("signinGiftMode"),
  signinGiftPill: document.getElementById("signinGiftPill"),
  signinGiftHint: document.getElementById("signinGiftHint"),
  saveSigninGiftBtn: document.getElementById("saveSigninGiftBtn"),
  signinNotificationForm: document.getElementById("signinNotificationForm"),
  signinNotifyEnabled: document.getElementById("signinNotifyEnabled"),
  signinNotifyImage: document.getElementById("signinNotifyImage"),
  signinDetailMode: document.getElementById("signinDetailMode"),
  signinNotificationHint: document.getElementById("signinNotificationHint"),
  saveSigninNotificationBtn: document.getElementById("saveSigninNotificationBtn"),
  signinTargetCount: document.getElementById("signinTargetCount"),
  signinTargetList: document.getElementById("signinTargetList"),
  addSigninTargetBtn: document.getElementById("addSigninTargetBtn"),
  signinPushBackdrop: document.getElementById("signinPushBackdrop"),
  signinPushDialog: document.getElementById("signinPushDialog"),
  signinPushDialogTitle: document.getElementById("signinPushDialogTitle"),
  signinPushDialogSubtitle: document.getElementById("signinPushDialogSubtitle"),
  signinPushCloseBtn: document.getElementById("signinPushCloseBtn"),
  signinPushForm: document.getElementById("signinPushForm"),
  signinPushPlatform: document.getElementById("signinPushPlatform"),
  signinPushKind: document.getElementById("signinPushKind"),
  signinPushTarget: document.getElementById("signinPushTarget"),
  signinPushHint: document.getElementById("signinPushHint"),
  signinPushCancelBtn: document.getElementById("signinPushCancelBtn"),
  signinPushSubmitBtn: document.getElementById("signinPushSubmitBtn"),
  articlesBackdrop: document.getElementById("articlesBackdrop"),
  articlesDialog: document.getElementById("articlesDialog"),
  articlesDialogTitle: document.getElementById("articlesDialogTitle"),
  articlesDialogSubtitle: document.getElementById("articlesDialogSubtitle"),
  articlesCloseBtn: document.getElementById("articlesCloseBtn"),
  articlesCloseFooterBtn: document.getElementById("articlesCloseFooterBtn"),
  articlesMeta: document.getElementById("articlesMeta"),
  articlesList: document.getElementById("articlesList"),
  confirmBackdrop: document.getElementById("confirmBackdrop"),
  confirmDialog: document.getElementById("confirmDialog"),
  confirmTitle: document.getElementById("confirmTitle"),
  confirmMessage: document.getElementById("confirmMessage"),
  confirmCancelBtn: document.getElementById("confirmCancelBtn"),
  confirmOkBtn: document.getElementById("confirmOkBtn"),
  toastLayer: document.getElementById("toastLayer"),
};

const QQ_PATTERN = /^\d{5,12}$/;
const ACCOUNT_PATTERN = /^\d{6,20}$/;
const AUTHOR_NAME_PATTERN = /^[^\x00-\x1f\x7f/\\:*?"<>|]{1,40}$/;
const FAKEID_PATTERN = /^\S{1,128}$/;
const PUSH_PLATFORM_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;
const PUSH_TARGET_PATTERN = /^[^\s:]{1,128}$/;

const STATUS_META = {
  healthy: { label: "正常", className: "status-healthy" },
  attention: { label: "需关注", className: "status-attention" },
  pending: { label: "处理中", className: "status-pending" },
  unknown: { label: "未签到", className: "status-unknown" },
  empty: { label: "无角色", className: "status-empty" },
  success: { label: "成功", className: "status-success" },
  already_claimed: { label: "已领取", className: "status-already-claimed" },
  failed: { label: "失败", className: "status-failed" },
  invalid: { label: "数据异常", className: "status-invalid" },
};

const mediaQuery =
  typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

function createElement(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}

function setText(node, value) {
  if (node) node.textContent = String(value ?? "");
}

function setNumber(node, value) {
  const numeric = Number(value);
  const text = Number.isFinite(numeric)
    ? new Intl.NumberFormat("zh-CN").format(numeric)
    : "--";
  setText(node, text);
}

function clampPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(100, Math.max(0, numeric));
}

function getStatusMeta(status) {
  return STATUS_META[String(status || "").toLowerCase()] || STATUS_META.unknown;
}

function createStatusBadge(status) {
  const meta = getStatusMeta(status);
  return createElement("span", `status-badge ${meta.className}`, meta.label);
}

function nowMs() {
  return Date.now() + state.clockOffset;
}

function formatDateTime(seconds, options = {}) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "暂无记录";
  const date = new Date(value * 1000);
  if (Number.isNaN(date.getTime())) return "暂无记录";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...options,
  }).format(date);
}

function formatRelative(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "暂无记录";
  const deltaSeconds = Math.round((nowMs() - value * 1000) / 1000);
  const future = deltaSeconds < 0;
  const distance = Math.abs(deltaSeconds);

  if (distance < 45) return future ? "即将" : "刚刚";
  if (distance < 3600) {
    const minutes = Math.max(1, Math.round(distance / 60));
    return future ? `${minutes} 分钟后` : `${minutes} 分钟前`;
  }
  if (distance < 86400) {
    const hours = Math.max(1, Math.round(distance / 3600));
    return future ? `${hours} 小时后` : `${hours} 小时前`;
  }
  if (distance < 7 * 86400) {
    const days = Math.max(1, Math.round(distance / 86400));
    return future ? `${days} 天后` : `${days} 天前`;
  }
  return formatDateTime(value);
}

function parseISOTime(value) {
  if (!value) return 0;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? Math.round(timestamp / 1000) : 0;
}

function loadThemePreference() {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (["auto", "dark", "light"].includes(stored)) return stored;
  } catch {
    // localStorage can be unavailable in hardened iframes.
  }
  return "auto";
}

function saveThemePreference() {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.themePreference);
  } catch {
    // Ignore persistence failures; the current page still works.
  }
}

function resolveThemeMode() {
  if (state.themePreference === "dark" || state.themePreference === "light") {
    return state.themePreference;
  }
  const context = bridge?.getContext?.();
  if (context?.isDark === true) return "dark";
  if (context?.isDark === false) return "light";
  return mediaQuery?.matches ? "dark" : "light";
}

function applyTheme() {
  const theme = resolveThemeMode();
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  const label = state.themePreference === "auto"
    ? "跟随系统"
    : state.themePreference === "dark"
      ? "深色"
      : "浅色";
  setText(els.themeLabel, label);
  if (els.themeBtn) {
    els.themeBtn.setAttribute("aria-label", `当前主题：${label}，点击切换`);
  }
}

function cycleTheme() {
  if (state.themePreference === "auto") state.themePreference = "dark";
  else if (state.themePreference === "dark") state.themePreference = "light";
  else state.themePreference = "auto";
  saveThemePreference();
  applyTheme();
}

function setActiveService(service, { focus = false } = {}) {
  const target = service === "strategy" ? "strategy" : "signin";
  state.activeService = target;
  const isStrategy = target === "strategy";
  const activeTab = isStrategy ? els.strategyTab : els.signinTab;
  const inactiveTab = isStrategy ? els.signinTab : els.strategyTab;

  if (activeTab) {
    activeTab.classList.add("is-active");
    activeTab.setAttribute("aria-selected", "true");
    activeTab.tabIndex = 0;
  }
  if (inactiveTab) {
    inactiveTab.classList.remove("is-active");
    inactiveTab.setAttribute("aria-selected", "false");
    inactiveTab.tabIndex = -1;
  }
  if (els.signinView) els.signinView.hidden = isStrategy;
  if (els.strategyView) els.strategyView.hidden = !isStrategy;
  if (focus && activeTab) activeTab.focus({ preventScroll: true });
}

function showBanner(message) {
  setText(els.statusBannerText, message);
  els.statusBanner.hidden = false;
}

function hideBanner() {
  els.statusBanner.hidden = true;
}

function showToast(message, type = "success") {
  const toast = createElement("div", `toast${type === "error" ? " error" : ""}`, message);
  els.toastLayer.appendChild(toast);
  while (els.toastLayer.children.length > 4) {
    els.toastLayer.firstElementChild?.remove();
  }
  window.setTimeout(() => {
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 190);
  }, 3200);
}

function normalizeError(error) {
  const message = String(error?.message || error || "未知错误").trim();
  return message || "未知错误";
}

function unwrapResponse(response) {
  if (
    response &&
    typeof response === "object" &&
    Object.prototype.hasOwnProperty.call(response, "ok")
  ) {
    if (!response.ok) {
      throw new Error(String(response.message || "请求失败"));
    }
    return Object.prototype.hasOwnProperty.call(response, "data")
      ? response.data
      : response;
  }
  return response;
}

async function apiGet(endpoint, params = {}) {
  if (!bridge || typeof bridge.apiGet !== "function") {
    throw new Error("AstrBot 页面桥接不可用，请从插件页面入口打开");
  }
  return unwrapResponse(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body = {}) {
  if (!bridge || typeof bridge.apiPost !== "function") {
    throw new Error("AstrBot 页面桥接不可用，请从插件页面入口打开");
  }
  return unwrapResponse(await bridge.apiPost(endpoint, body));
}

async function waitForBridgeReady() {
  if (!bridge || typeof bridge.ready !== "function") {
    throw new Error("未检测到 AstrBot 插件页面桥接");
  }
  let timer;
  try {
    await Promise.race([
      bridge.ready(),
      new Promise((_, reject) => {
        timer = window.setTimeout(
          () => reject(new Error("等待 AstrBot 页面上下文超时")),
          8000,
        );
      }),
    ]);
  } finally {
    window.clearTimeout(timer);
  }
}

function getMutationRuntime() {
  const runtime = state.bootstrap?.runtime;
  return runtime && typeof runtime === "object" ? runtime : {};
}

function getMutationLockMessage() {
  const runtime = getMutationRuntime();
  if (runtime.mutation_lock_reason) return String(runtime.mutation_lock_reason);
  if (runtime.auto_sign_progress?.running) return "全量签到任务正在执行";
  if (runtime.keep_sign_running) return "签到会话保活正在执行";
  return "当前运行状态不允许修改绑定";
}

function isMutationLocked() {
  return Boolean(getMutationRuntime().mutations_locked);
}

function updateMutationControls() {
  const locked = isMutationLocked();
  const busy = state.mutating;

  if (els.addBindingBtn) {
    els.addBindingBtn.disabled = locked || busy;
    els.addBindingBtn.title = locked ? getMutationLockMessage() : "";
  }

  if (els.addStrategyAuthorBtn) {
    els.addStrategyAuthorBtn.disabled = busy;
  }
  if (els.addStrategyPushBtn) {
    els.addStrategyPushBtn.disabled = busy;
  }
  for (const button of [
    els.addSigninTargetBtn,
    els.saveSigninGiftBtn,
    els.saveSigninNotificationBtn,
  ]) {
    if (button) button.disabled = busy;
  }
  for (const button of document.querySelectorAll("[data-signin-action]")) {
    button.disabled = busy;
  }

  if (els.mutationPill) {
    els.mutationPill.className = `live-pill ${locked ? "is-locked" : "is-editable"}`;
    els.mutationPill.replaceChildren(
      createElement("i"),
      document.createTextNode(locked ? "已锁定" : "可维护"),
    );
    els.mutationPill.title = locked
      ? getMutationLockMessage()
      : "已登录管理员可以新增、编辑或删除绑定";
  }

  for (const button of document.querySelectorAll("[data-mutation-action]")) {
    const forceDisabled = button.dataset.forceDisabled === "1";
    button.disabled = locked || busy || forceDisabled;
    if (locked) button.title = getMutationLockMessage();
    else if (forceDisabled) button.title = "该记录数据异常，请删除后重新添加";
    else button.removeAttribute("title");
  }
}

function setBindingFormHint(message) {
  els.bindingFormHint.textContent = message || "";
  els.bindingFormHint.hidden = !message;
}

function setBindingSubmitBusy(busy) {
  els.bindingSubmitBtn.disabled = busy || isMutationLocked();
  els.bindingSubmitBtn.classList.toggle("is-loading", busy);
  setText(
    els.bindingSubmitBtn,
    busy ? "保存中…" : state.editor.mode === "edit" ? "保存修改" : "新增绑定",
  );
}

function setBindingDialogOpen(open) {
  window.clearTimeout(state.dialogCloseTimer);
  if (open) {
    state.lastDialogFocus = document.activeElement;
    els.bindingBackdrop.hidden = false;
    els.bindingDialog.hidden = false;
    document.body.classList.add("dialog-open");
    window.requestAnimationFrame(() => {
      els.bindingBackdrop.classList.add("is-open");
      els.bindingDialog.classList.add("is-open");
      const firstInput = els.bindingQQ.readOnly
        ? els.bindingAccount
        : els.bindingQQ;
      firstInput.focus({ preventScroll: true });
    });
    return;
  }

  els.bindingBackdrop.classList.remove("is-open");
  els.bindingDialog.classList.remove("is-open");
  document.body.classList.remove("dialog-open");
  state.dialogCloseTimer = window.setTimeout(() => {
    els.bindingBackdrop.hidden = true;
    els.bindingDialog.hidden = true;
  }, 220);
  if (state.lastDialogFocus instanceof HTMLElement) {
    state.lastDialogFocus.focus({ preventScroll: true });
  }
}

function closeBindingDialog() {
  setBindingFormHint("");
  setBindingDialogOpen(false);
}

function setStrategyFormHint(message) {
  els.strategyFormHint.textContent = message || "";
  els.strategyFormHint.hidden = !message;
}

function setStrategySubmitBusy(busy) {
  els.strategySubmitBtn.disabled = busy;
  els.strategySubmitBtn.classList.toggle("is-loading", busy);
  const action = state.strategyEditor.kind === "author" ? "作者" : "目标";
  setText(
    els.strategySubmitBtn,
    busy ? "保存中…" : state.strategyEditor.mode === "edit" ? `保存${action}` : `新增${action}`,
  );
}

function setStrategyDialogOpen(open) {
  window.clearTimeout(state.strategyDialogCloseTimer);
  if (open) {
    state.lastStrategyDialogFocus = document.activeElement;
    els.strategyBackdrop.hidden = false;
    els.strategyDialog.hidden = false;
    document.body.classList.add("dialog-open");
    window.requestAnimationFrame(() => {
      els.strategyBackdrop.classList.add("is-open");
      els.strategyDialog.classList.add("is-open");
      const firstInput = state.strategyEditor.kind === "author"
        ? els.strategyAuthorName
        : els.strategyPushPlatform;
      firstInput.focus({ preventScroll: true });
    });
    return;
  }

  els.strategyBackdrop.classList.remove("is-open");
  els.strategyDialog.classList.remove("is-open");
  document.body.classList.remove("dialog-open");
  state.strategyDialogCloseTimer = window.setTimeout(() => {
    els.strategyBackdrop.hidden = true;
    els.strategyDialog.hidden = true;
  }, 220);
  if (state.lastStrategyDialogFocus instanceof HTMLElement) {
    state.lastStrategyDialogFocus.focus({ preventScroll: true });
  }
}

function closeStrategyDialog() {
  setStrategyFormHint("");
  setStrategyDialogOpen(false);
}

function setSigninPushHint(message) {
  els.signinPushHint.textContent = message || "";
  els.signinPushHint.hidden = !message;
}

function setSigninPushSubmitBusy(busy) {
  els.signinPushSubmitBtn.disabled = busy;
  els.signinPushSubmitBtn.classList.toggle("is-loading", busy);
  setText(
    els.signinPushSubmitBtn,
    busy
      ? "保存中…"
      : state.signinPushEditor.mode === "edit"
        ? "保存目标"
        : "新增目标",
  );
}

function setSigninPushDialogOpen(open) {
  window.clearTimeout(state.signinPushDialogCloseTimer);
  if (open) {
    state.lastSigninPushFocus = document.activeElement;
    els.signinPushBackdrop.hidden = false;
    els.signinPushDialog.hidden = false;
    document.body.classList.add("dialog-open");
    window.requestAnimationFrame(() => {
      els.signinPushBackdrop.classList.add("is-open");
      els.signinPushDialog.classList.add("is-open");
      els.signinPushPlatform.focus({ preventScroll: true });
    });
    return;
  }

  els.signinPushBackdrop.classList.remove("is-open");
  els.signinPushDialog.classList.remove("is-open");
  document.body.classList.remove("dialog-open");
  state.signinPushDialogCloseTimer = window.setTimeout(() => {
    els.signinPushBackdrop.hidden = true;
    els.signinPushDialog.hidden = true;
  }, 220);
  if (state.lastSigninPushFocus instanceof HTMLElement) {
    state.lastSigninPushFocus.focus({ preventScroll: true });
  }
}

function closeSigninPushDialog() {
  setSigninPushHint("");
  setSigninPushDialogOpen(false);
}

function setArticlesDialogOpen(open) {
  window.clearTimeout(state.articlesCloseTimer);
  if (open) {
    state.lastArticlesFocus = document.activeElement;
    els.articlesBackdrop.hidden = false;
    els.articlesDialog.hidden = false;
    document.body.classList.add("dialog-open");
    window.requestAnimationFrame(() => {
      els.articlesBackdrop.classList.add("is-open");
      els.articlesDialog.classList.add("is-open");
      els.articlesCloseBtn.focus({ preventScroll: true });
    });
    return;
  }

  els.articlesBackdrop.classList.remove("is-open");
  els.articlesDialog.classList.remove("is-open");
  document.body.classList.remove("dialog-open");
  state.articlesCloseTimer = window.setTimeout(() => {
    els.articlesBackdrop.hidden = true;
    els.articlesDialog.hidden = true;
  }, 220);
  if (state.lastArticlesFocus instanceof HTMLElement) {
    state.lastArticlesFocus.focus({ preventScroll: true });
  }
}

function closeArticlesDialog() {
  state.articlesToken += 1;
  setArticlesDialogOpen(false);
}

function renderArticlesLoading(name) {
  setText(els.articlesDialogTitle, `${name || "作者"} · 文章`);
  setText(els.articlesDialogSubtitle, "正在读取本地文章缓存…");
  setText(els.articlesMeta, "");
  els.articlesList.replaceChildren(
    createElement("div", "empty-inline", "正在载入文章列表…"),
  );
}

function renderArticlesError(name, message) {
  setText(els.articlesDialogTitle, `${name || "作者"} · 文章`);
  setText(els.articlesDialogSubtitle, "文章缓存读取失败");
  setText(els.articlesMeta, "");
  els.articlesList.replaceChildren(
    createElement("div", "empty-inline", message || "无法读取文章缓存"),
  );
}

function buildArticleItem(article) {
  const item = createElement("article", "article-item");
  const head = createElement("div", "article-item-head");
  const title = createElement(
    "strong",
    "article-item-title",
    article.title || "未命名文章",
  );
  title.title = String(article.title || "未命名文章");
  const published = Number(article.published_at || 0);
  const time = createElement(
    "span",
    "article-item-time",
    published ? formatRelative(published) : "时间未知",
  );
  time.title = published ? formatDateTime(published) : "";
  head.append(title, time);
  item.appendChild(head);

  if (article.digest) {
    item.appendChild(createElement("p", "article-item-digest", article.digest));
  }

  const link = String(article.link || "").trim();
  if (/^https?:\/\//i.test(link)) {
    const anchor = createElement("a", "article-item-link", "打开原文");
    anchor.href = link;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    item.appendChild(anchor);
  }
  return item;
}

function renderArticles(data) {
  const name = String(data?.name || "作者");
  const total = Math.max(0, Number(data?.total || 0));
  const syncedAt = Number(data?.synced_at || 0);
  const items = Array.isArray(data?.items) ? data.items : [];
  setText(els.articlesDialogTitle, `${name} · 文章`);
  setText(
    els.articlesDialogSubtitle,
    syncedAt
      ? `缓存同步于 ${formatDateTime(syncedAt)}`
      : "文章缓存尚未记录同步时间",
  );
  setText(
    els.articlesMeta,
    total
      ? `共 ${total} 篇${data?.has_more ? `，当前显示最近 ${items.length} 篇` : ""}`
      : "缓存中没有文章",
  );
  if (!items.length) {
    els.articlesList.replaceChildren(
      createElement("div", "empty-inline", "该作者暂无缓存文章"),
    );
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const article of items) {
    fragment.appendChild(buildArticleItem(article));
  }
  els.articlesList.replaceChildren(fragment);
}

async function openStrategyArticles(name) {
  const normalizedName = String(name || "").trim();
  if (!normalizedName) return;
  const token = ++state.articlesToken;
  renderArticlesLoading(normalizedName);
  setArticlesDialogOpen(true);
  try {
    const data = await apiGet("admin/strategy/author/articles", {
      name: normalizedName,
      limit: 100,
    });
    if (token !== state.articlesToken) return;
    renderArticles(data || {});
  } catch (error) {
    if (token !== state.articlesToken) return;
    renderArticlesError(normalizedName, normalizeError(error));
  }
}

function openStrategyEditor(kind, mode, options = {}) {
  const editorKind = kind === "push" ? "push" : "author";
  const editorMode = mode === "edit" ? "edit" : "create";
  const item = options.item || null;
  state.strategyEditor = {
    mode: editorMode,
    kind: editorKind,
    name: editorKind === "author" ? String(item?.name || "") : "",
    target: editorKind === "push" ? String(item?.target || "") : "",
  };

  els.strategyForm.reset();
  setStrategyFormHint("");
  setStrategySubmitBusy(false);
  els.strategyAuthorFields.hidden = editorKind !== "author";
  els.strategyPushFields.hidden = editorKind !== "push";

  if (editorKind === "author") {
    els.strategyAuthorName.value = String(item?.name || "");
    els.strategyAuthorFakeid.value = "";
    els.strategyAuthorFakeid.required = editorMode === "create";
    els.strategyFakeidRequired.hidden = editorMode === "edit";
    els.strategyFakeidHint.textContent = editorMode === "edit"
      ? "留空保持当前 fakeid，不会在页面回显"
      : "仅写入插件 KV，不会在页面或快照中回显";
    els.strategyAuthorFakeid.placeholder = editorMode === "edit"
      ? "留空保持不变"
      : "公众号唯一标识";
    setText(
      els.strategyDialogTitle,
      editorMode === "edit" ? "编辑攻略作者" : "新增攻略作者",
    );
    setText(
      els.strategyDialogSubtitle,
      editorMode === "edit"
        ? `当前作者：${state.strategyEditor.name} · 可同时修改名称与认证信息`
        : "填写公众号作者名称和 fakeid 后保存",
    );
  } else {
    els.strategyPushPlatform.value = String(item?.platform || "QQ");
    els.strategyPushKind.value = ["group", "private"].includes(item?.kind)
      ? item.kind
      : "group";
    els.strategyPushTarget.value = String(item?.identifier || "");
    setText(
      els.strategyDialogTitle,
      editorMode === "edit" ? "编辑推送目标" : "新增推送目标",
    );
    setText(
      els.strategyDialogSubtitle,
      editorMode === "edit"
        ? "修改平台、会话类型或群号/用户号后保存"
        : "保存后攻略更新会推送至该会话",
    );
  }

  setStrategyDialogOpen(true);
}

function readStrategyForm() {
  return {
    authorName: String(els.strategyAuthorName.value || "").trim(),
    fakeid: String(els.strategyAuthorFakeid.value || "").trim(),
    platform: String(els.strategyPushPlatform.value || "").trim(),
    kind: String(els.strategyPushKind.value || "").trim(),
    target: String(els.strategyPushTarget.value || "").trim(),
  };
}

function validateStrategyForm(kind, mode, values) {
  if (kind === "author") {
    if (!AUTHOR_NAME_PATTERN.test(values.authorName)) {
      return "作者名称应为 1-40 个字符，且不能包含 / \\ : * ? \" < > |";
    }
    if ([".", ".."].includes(values.authorName)) return "作者名称不能为 . 或 ..";
    if (mode === "create" && !values.fakeid) return "请填写作者 fakeid";
    if (values.fakeid && !FAKEID_PATTERN.test(values.fakeid)) {
      return "作者 fakeid 不能包含空白，且不能超过 128 个字符";
    }
    return "";
  }

  if (!PUSH_PLATFORM_PATTERN.test(values.platform)) {
    return "平台标识应为 1-64 位字母、数字、下划线、点或短横线";
  }
  if (!["group", "private"].includes(values.kind)) return "请选择有效的会话类型";
  if (!PUSH_TARGET_PATTERN.test(values.target)) {
    return "群号或用户号不能为空、不能包含空白或冒号，且不能超过 128 个字符";
  }
  return "";
}

async function submitStrategyForm(event) {
  event.preventDefault();
  if (state.mutating) return;

  const editor = state.strategyEditor;
  const values = readStrategyForm();
  const validationMessage = validateStrategyForm(editor.kind, editor.mode, values);
  if (validationMessage) {
    setStrategyFormHint(validationMessage);
    return;
  }

  setStrategyFormHint("");
  state.mutating = true;
  setStrategySubmitBusy(true);
  updateMutationControls();
  try {
    if (editor.kind === "author") {
      if (editor.mode === "edit") {
        await apiPost("admin/strategy/author/update", {
          name: editor.name,
          new_name: values.authorName,
          fakeid: values.fakeid,
        });
        showToast("攻略作者已更新");
      } else {
        await apiPost("admin/strategy/author/add", {
          name: values.authorName,
          fakeid: values.fakeid,
        });
        showToast("攻略作者已新增");
      }
    } else if (editor.mode === "edit") {
      await apiPost("admin/strategy/push/update", {
        original: editor.target,
        platform: values.platform,
        kind: values.kind,
        target: values.target,
      });
      showToast("攻略推送目标已更新");
    } else {
      await apiPost("admin/strategy/push/add", {
        platform: values.platform,
        kind: values.kind,
        target: values.target,
      });
      showToast("攻略推送目标已新增");
    }
    closeStrategyDialog();
    await loadBootstrap();
  } catch (error) {
    setStrategyFormHint(normalizeError(error));
  } finally {
    state.mutating = false;
    setStrategySubmitBusy(false);
    updateMutationControls();
  }
}

async function deleteStrategyAuthor(name, action) {
  if (state.mutating) return;
  const cleanCacheOnly = action === "cache";
  const confirmed = await openConfirmDialog({
    title: cleanCacheOnly ? "清理文章缓存" : "移除攻略作者",
    message: cleanCacheOnly
      ? `确认清理“${name}”的本地文章缓存？作者登记会保留，下次同步会重新拉取文章。`
      : `确认从攻略作者列表中移除“${name}”？本地文章缓存会保留，可在缓存卡片中单独清理。`,
    confirmLabel: cleanCacheOnly ? "清理缓存" : "移除作者",
  });
  if (!confirmed || state.mutating) return;

  state.mutating = true;
  updateMutationControls();
  try {
    await apiPost("admin/strategy/author/delete", {
      name,
      remove_registration: !cleanCacheOnly,
      delete_cache: cleanCacheOnly,
    });
    showToast(cleanCacheOnly ? "攻略文章缓存已清理" : "攻略作者已移除");
    await loadBootstrap();
  } catch (error) {
    showToast(`操作失败：${normalizeError(error)}`, "error");
  } finally {
    state.mutating = false;
    updateMutationControls();
  }
}

async function deleteStrategyPush(item) {
  if (state.mutating) return;
  const label = String(item.identifier || item.target || "该目标");
  const confirmed = await openConfirmDialog({
    title: "删除推送目标",
    message: `确认删除推送目标“${label}”？删除后攻略更新不再向该会话推送。`,
    confirmLabel: "删除目标",
  });
  if (!confirmed || state.mutating) return;

  state.mutating = true;
  updateMutationControls();
  try {
    await apiPost("admin/strategy/push/delete", { target: item.target });
    showToast("攻略推送目标已删除");
    await loadBootstrap();
  } catch (error) {
    showToast(`删除失败：${normalizeError(error)}`, "error");
  } finally {
    state.mutating = false;
    updateMutationControls();
  }
}

function setSigninGiftHint(message) {
  els.signinGiftHint.textContent = message || "";
  els.signinGiftHint.hidden = !message;
}

function setSigninNotificationHint(message) {
  els.signinNotificationHint.textContent = message || "";
  els.signinNotificationHint.hidden = !message;
}

async function saveSigninGiftSettings(event) {
  event.preventDefault();
  if (state.mutating) return;
  const claimMode = String(els.signinGiftMode.value || "").trim();
  if (!["all", "none"].includes(claimMode)) {
    setSigninGiftHint("请选择有效的礼包领取类型");
    return;
  }

  setSigninGiftHint("");
  state.mutating = true;
  setText(els.saveSigninGiftBtn, "保存中…");
  updateMutationControls();
  try {
    await apiPost("admin/signin/gift/update", { claim_mode: claimMode });
    showToast(claimMode === "all" ? "礼包领取已启用" : "礼包自动领取已关闭");
    await loadBootstrap();
  } catch (error) {
    setSigninGiftHint(normalizeError(error));
  } finally {
    state.mutating = false;
    setText(els.saveSigninGiftBtn, "保存礼包策略");
    updateMutationControls();
  }
}

async function saveSigninNotificationSettings(event) {
  event.preventDefault();
  if (state.mutating) return;
  setSigninNotificationHint("");
  state.mutating = true;
  setText(els.saveSigninNotificationBtn, "保存中…");
  updateMutationControls();
  try {
    await apiPost("admin/signin/notification/settings", {
      enabled: Boolean(els.signinNotifyEnabled.checked),
      include_reward_image: Boolean(els.signinNotifyImage.checked),
      detail_mode: String(els.signinDetailMode.value || "issues_overview"),
    });
    showToast("签到通知设置已更新");
    await loadBootstrap();
  } catch (error) {
    setSigninNotificationHint(normalizeError(error));
  } finally {
    state.mutating = false;
    setText(els.saveSigninNotificationBtn, "保存通知设置");
    updateMutationControls();
  }
}

function openSigninPushEditor(mode, item = null) {
  const editorMode = mode === "edit" ? "edit" : "create";
  state.signinPushEditor = {
    mode: editorMode,
    original: editorMode === "edit" ? String(item?.target || "") : "",
  };
  els.signinPushForm.reset();
  setSigninPushHint("");
  els.signinPushPlatform.value = String(item?.platform || "QQ");
  els.signinPushKind.value = ["group", "private"].includes(item?.kind)
    ? item.kind
    : "group";
  els.signinPushTarget.value = String(item?.identifier || "");
  setText(
    els.signinPushDialogTitle,
    editorMode === "edit" ? "编辑通知目标" : "新增通知目标",
  );
  setText(
    els.signinPushDialogSubtitle,
    editorMode === "edit"
      ? "修改平台、会话类型或群号/用户号后保存"
      : "保存后定时签到汇总会发送至该会话",
  );
  setSigninPushSubmitBusy(false);
  setSigninPushDialogOpen(true);
}

function readSigninPushForm() {
  return {
    platform: String(els.signinPushPlatform.value || "").trim(),
    kind: String(els.signinPushKind.value || "").trim(),
    target: String(els.signinPushTarget.value || "").trim(),
  };
}

function validateSigninPushForm(values) {
  if (!PUSH_PLATFORM_PATTERN.test(values.platform)) {
    return "平台标识应为 1-64 位字母、数字、下划线、点或短横线";
  }
  if (!["group", "private"].includes(values.kind)) return "请选择有效的会话类型";
  if (!PUSH_TARGET_PATTERN.test(values.target)) {
    return "群号或用户号不能为空、不能包含空白或冒号，且不能超过 128 个字符";
  }
  return "";
}

async function submitSigninPushForm(event) {
  event.preventDefault();
  if (state.mutating) return;
  const values = readSigninPushForm();
  const validationMessage = validateSigninPushForm(values);
  if (validationMessage) {
    setSigninPushHint(validationMessage);
    return;
  }

  setSigninPushHint("");
  state.mutating = true;
  setSigninPushSubmitBusy(true);
  updateMutationControls();
  try {
    if (state.signinPushEditor.mode === "edit") {
      await apiPost("admin/signin/notification/update", {
        original: state.signinPushEditor.original,
        ...values,
      });
      showToast("签到通知目标已更新");
    } else {
      await apiPost("admin/signin/notification/add", values);
      showToast("签到通知目标已新增");
    }
    closeSigninPushDialog();
    await loadBootstrap();
  } catch (error) {
    setSigninPushHint(normalizeError(error));
  } finally {
    state.mutating = false;
    setSigninPushSubmitBusy(false);
    updateMutationControls();
  }
}

async function deleteSigninPush(item) {
  if (state.mutating) return;
  const label = String(item.identifier || item.target || "该目标");
  const confirmed = await openConfirmDialog({
    title: "删除签到通知目标",
    message: `确认删除通知目标“${label}”？删除后定时签到不再向该会话发送汇总。`,
    confirmLabel: "删除目标",
  });
  if (!confirmed || state.mutating) return;

  state.mutating = true;
  updateMutationControls();
  try {
    await apiPost("admin/signin/notification/delete", { target: item.target });
    showToast("签到通知目标已删除");
    await loadBootstrap();
  } catch (error) {
    showToast(`删除失败：${normalizeError(error)}`, "error");
  } finally {
    state.mutating = false;
    updateMutationControls();
  }
}

function setConfirmDialogOpen(open) {
  window.clearTimeout(state.confirmCloseTimer);
  if (open) {
    state.lastConfirmFocus = document.activeElement;
    els.confirmBackdrop.hidden = false;
    els.confirmDialog.hidden = false;
    document.body.classList.add("confirm-open");
    window.requestAnimationFrame(() => {
      els.confirmBackdrop.classList.add("is-open");
      els.confirmDialog.classList.add("is-open");
      els.confirmCancelBtn.focus({ preventScroll: true });
    });
    return;
  }

  els.confirmBackdrop.classList.remove("is-open");
  els.confirmDialog.classList.remove("is-open");
  document.body.classList.remove("confirm-open");
  state.confirmCloseTimer = window.setTimeout(() => {
    els.confirmBackdrop.hidden = true;
    els.confirmDialog.hidden = true;
  }, 180);
  if (state.lastConfirmFocus instanceof HTMLElement) {
    state.lastConfirmFocus.focus({ preventScroll: true });
  }
}

function openConfirmDialog(options = {}) {
  const title = String(options.title || "确认删除");
  const message = String(options.message || "此操作不可撤销。");
  const confirmLabel = String(options.confirmLabel || "确认删除");

  if (state.confirmResolver) {
    const previousResolver = state.confirmResolver;
    state.confirmResolver = null;
    previousResolver(false);
  }

  setText(els.confirmTitle, title);
  setText(els.confirmMessage, message);
  setText(els.confirmOkBtn, confirmLabel);
  return new Promise((resolve) => {
    state.confirmResolver = resolve;
    setConfirmDialogOpen(true);
  });
}

function settleConfirmDialog(confirmed) {
  const resolver = state.confirmResolver;
  if (!resolver) return;
  state.confirmResolver = null;
  setConfirmDialogOpen(false);
  resolver(Boolean(confirmed));
}

function openBindingEditor(mode, options = {}) {
  if (isMutationLocked()) {
    showToast(`${getMutationLockMessage()}，请稍后再修改绑定`, "error");
    return;
  }

  const item = options.item || null;
  const qq = String(options.qq || "").trim();
  state.editor = {
    mode: mode === "edit" ? "edit" : "create",
    qq,
    index: Number(item?.index || 0),
  };

  els.bindingForm.reset();
  setBindingFormHint("");
  setBindingSubmitBusy(false);
  els.bindingQQ.readOnly = false;
  els.bindingAccount.required = true;
  els.bindingRole.required = true;
  els.bindingAccountRequired.hidden = false;
  els.bindingRoleRequired.hidden = false;
  els.bindingAccountHint.textContent = "用于查询角色，保存时加密";
  els.bindingInfoHint.textContent = "仅用于管理页辨识，不影响签到";

  if (state.editor.mode === "edit" && item) {
    els.bindingQQ.value = qq;
    els.bindingQQ.readOnly = true;
    els.bindingGame.value = String(item.game_id || "39");
    els.bindingInfo.value = String(item.info || "");
    els.bindingAccount.placeholder = "留空保持不变";
    els.bindingRole.placeholder = "留空保持不变";
    els.bindingAccountHint.textContent = "手机号与角色 ID 同时填写才会修改身份";
    els.bindingInfoHint.textContent = "留空保持当前备注，不影响签到";
    els.bindingAccount.required = false;
    els.bindingRole.required = false;
    els.bindingAccountRequired.hidden = true;
    els.bindingRoleRequired.hidden = true;
    setText(els.bindingDialogTitle, "编辑角色绑定");
    setText(
      els.bindingDialogSubtitle,
      `QQ ${qq} · 第 ${item.index} 个角色 · 身份留空则保持不变`,
    );
    setText(els.bindingSubmitBtn, "保存修改");
  } else {
    els.bindingQQ.value = qq;
    els.bindingQQ.readOnly = Boolean(qq);
    els.bindingGame.value = "39";
    els.bindingAccount.placeholder = "6-20 位数字";
    els.bindingRole.placeholder = "不含空白字符";
    setText(els.bindingDialogTitle, "新增官服绑定");
    setText(
      els.bindingDialogSubtitle,
      qq ? `为 QQ ${qq} 新增角色` : "填写账号与角色信息后保存",
    );
    setText(els.bindingSubmitBtn, "新增官服绑定");
  }

  setBindingDialogOpen(true);
}

function readBindingForm() {
  return {
    qq: String(els.bindingQQ.value || "").trim(),
    account: String(els.bindingAccount.value || "").trim(),
    role_id: String(els.bindingRole.value || "").trim(),
    game_id: String(els.bindingGame.value || "").trim(),
    info: String(els.bindingInfo.value || "").trim(),
  };
}

function validateBindingForm(mode, values) {
  if (!QQ_PATTERN.test(values.qq)) return "QQ 号应为 5-12 位数字";
  if (!["39", "26"].includes(values.game_id)) return "请选择有效的游戏区服";
  if (!values.account && !values.role_id) {
    if (mode === "edit") return "";
    return "请填写手机号和角色 ID";
  }
  if (mode === "edit" && Boolean(values.account) !== Boolean(values.role_id)) {
    return "修改身份时请同时填写手机号和角色 ID";
  }
  if (!ACCOUNT_PATTERN.test(values.account)) {
    return "手机号应为 6-20 位数字";
  }
  if (!values.role_id || /\s/.test(values.role_id)) {
    return "角色 ID 不能为空且不能包含空白字符";
  }
  if (values.role_id.length > 128) return "角色 ID 不能超过 128 个字符";
  if (values.info.length > 200) return "角色备注不能超过 200 个字符";
  return "";
}

async function submitBindingForm(event) {
  event.preventDefault();
  if (state.mutating) return;
  if (isMutationLocked()) {
    setBindingFormHint(`${getMutationLockMessage()}，请稍后再修改绑定`);
    return;
  }

  const mode = state.editor.mode;
  const values = readBindingForm();
  const validationMessage = validateBindingForm(mode, values);
  if (validationMessage) {
    setBindingFormHint(validationMessage);
    return;
  }

  setBindingFormHint("");
  state.mutating = true;
  setBindingSubmitBusy(true);
  updateMutationControls();
  try {
    let result;
    if (mode === "edit") {
      result = await apiPost("admin/binding/update", {
        qq: values.qq,
        index: state.editor.index,
        account: values.account,
        role_id: values.role_id,
        game_id: values.game_id,
        info: values.info,
      });
    } else {
      result = await apiPost("admin/binding/add", values);
    }

    closeBindingDialog();
    if (mode === "edit" && result?.identity_changed) {
      showToast("绑定已更新，角色需要重新签到");
    } else {
      showToast(mode === "edit" ? "绑定信息已更新" : "绑定已新增");
    }
    await loadBootstrap();
    await openUserDrawer(values.qq);
  } catch (error) {
    setBindingFormHint(normalizeError(error));
  } finally {
    state.mutating = false;
    setBindingSubmitBusy(false);
    updateMutationControls();
  }
}

async function deleteRoleBinding(qq, item) {
  if (isMutationLocked() || state.mutating) return;
  const label = String(item.info || `第 ${item.index} 个角色`);
  const confirmed = await openConfirmDialog({
    title: "删除角色绑定",
    message: `确认删除 QQ ${qq} 的“${label}”？该角色会从本地绑定记录中移除，此操作不可撤销。`,
    confirmLabel: "删除角色",
  });
  if (!confirmed) return;
  if (isMutationLocked() || state.mutating) {
    showToast(`${getMutationLockMessage()}，请稍后再修改绑定`, "error");
    return;
  }

  state.mutating = true;
  updateMutationControls();
  try {
    const result = await apiPost("admin/binding/delete", {
      qq,
      index: Number(item.index),
    });
    showToast("角色绑定已删除");
    await loadBootstrap();
    if (result?.user_removed) closeUserDrawer();
    else await openUserDrawer(qq);
  } catch (error) {
    showToast(`删除失败：${normalizeError(error)}`, "error");
  } finally {
    state.mutating = false;
    updateMutationControls();
  }
}

async function deleteUserBindings(qq, roles) {
  if (isMutationLocked() || state.mutating) return;
  const confirmed = await openConfirmDialog({
    title: "删除全部绑定",
    message: `确认删除 QQ ${qq} 的全部 ${roles} 个角色绑定？该用户的数据文件会被移除，此操作不可撤销。`,
    confirmLabel: "删除全部",
  });
  if (!confirmed) return;
  if (isMutationLocked() || state.mutating) {
    showToast(`${getMutationLockMessage()}，请稍后再修改绑定`, "error");
    return;
  }

  state.mutating = true;
  updateMutationControls();
  try {
    await apiPost("admin/user/delete", { qq });
    showToast(`QQ ${qq} 的全部绑定已删除`);
    closeUserDrawer();
    await loadBootstrap();
  } catch (error) {
    showToast(`删除失败：${normalizeError(error)}`, "error");
  } finally {
    state.mutating = false;
    updateMutationControls();
  }
}

function renderUserLoading() {
  els.userList.replaceChildren();
  for (let index = 0; index < 5; index += 1) {
    const row = createElement("div", "skeleton-row");
    for (let cell = 0; cell < 5; cell += 1) {
      row.appendChild(createElement("span"));
    }
    els.userList.appendChild(row);
  }
}

function renderUserEmpty(title, description, actionLabel = "") {
  els.userList.replaceChildren();
  const wrapper = createElement("div", "empty-state");
  const inner = createElement("div", "empty-state-inner");
  inner.appendChild(createElement("div", "empty-illustration", "空"));
  inner.appendChild(createElement("strong", "", title));
  inner.appendChild(createElement("p", "", description));

  if (actionLabel) {
    const button = createElement("button", "button ghost empty-action", actionLabel);
    button.type = "button";
    button.addEventListener("click", () => {
      void loadBootstrap({ notify: true });
    });
    inner.appendChild(button);
  }

  wrapper.appendChild(inner);
  els.userList.appendChild(wrapper);
}

async function loadBootstrap({ notify = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  els.refreshBtn.disabled = true;
  els.refreshBtn.classList.add("is-loading");
  els.refreshBtn.setAttribute("aria-busy", "true");

  try {
    const [signinData, strategyData] = await Promise.all([
      apiGet("admin/signin/bootstrap"),
      apiGet("admin/strategy/bootstrap"),
    ]);
    if (
      !signinData ||
      typeof signinData !== "object" ||
      !strategyData ||
      typeof strategyData !== "object"
    ) {
      throw new Error("管理接口返回了无效数据");
    }

    const data = {
      ...signinData,
      generated_at: Math.max(
        Number(signinData.generated_at || 0),
        Number(strategyData.generated_at || 0),
      ),
      strategy: strategyData.strategy,
      version: signinData.version || strategyData.version,
    };
    state.bootstrap = data;
    state.users = Array.isArray(data.users) ? data.users : [];
    state.pending = Array.isArray(data.pending?.items) ? data.pending.items : [];

    const serverTime = Number(data.runtime?.server_time || data.generated_at || 0);
    if (Number.isFinite(serverTime) && serverTime > 0) {
      state.clockOffset = serverTime * 1000 - Date.now();
    }

    renderAll();
    hideBanner();
    if (notify) showToast("管理数据已刷新");
  } catch (error) {
    const message = normalizeError(error);
    showBanner(`无法加载管理数据：${message}`);
    if (!state.bootstrap) {
      setText(els.versionBadge, "加载失败");
      renderUserEmpty(
        "暂时无法读取数据",
        "请确认插件已启用，并从 AstrBot 的插件页面入口打开。",
        "重新加载",
      );
      renderSigninUnavailable();
      renderPendingUnavailable();
      renderRuntimeUnavailable();
      renderStrategyUnavailable();
    } else {
      showToast(`刷新失败：${message}`, "error");
    }
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
    els.refreshBtn.classList.remove("is-loading");
    els.refreshBtn.removeAttribute("aria-busy");
  }
}

function renderAll() {
  const data = state.bootstrap || {};
  setText(els.versionBadge, data.version || "unknown");
  setText(els.lastUpdated, data.generated_at ? formatRelative(data.generated_at) : "刚刚");
  els.lastUpdated.title = data.generated_at ? formatDateTime(data.generated_at) : "";

  renderStats(data.stats || {});
  renderSigninPreferences(data.signin || {});
  renderFilterCounts();
  renderUserList();
  renderPending(data.pending || {});
  renderRuntime(data.runtime || {});
  renderStrategy(data.strategy || {});
  setNumber(els.signinTabCount, data.stats?.users || 0);
  setNumber(els.strategyTabCount, data.strategy?.author_count || 0);
  updateMutationControls();
}

function renderStats(stats) {
  setNumber(els.statUsers, stats.users || 0);
  setNumber(els.statAccounts, stats.accounts || 0);
  setNumber(els.statRoles, stats.roles || 0);
  setNumber(els.statAttention, stats.attention || 0);
  setNumber(els.statPending, stats.pending_web_requests || 0);

  setText(els.statUsersHint, "读取自本地 users 数据");
  setText(
    els.statRolesHint,
    `成功 ${stats.success || 0} · 已领取 ${stats.already_claimed || 0} · 处理中 ${stats.pending || 0} · 异常 ${stats.invalid || 0}`,
  );
  setText(
    els.statAttentionHint,
    `失败 ${stats.failed || 0} · 数据异常 ${stats.invalid || 0}`,
  );
  setText(
    els.statPendingHint,
    `涉及 ${stats.pending_web_roles || 0} 个角色`,
  );

  const hasRate = stats.success_rate !== null && stats.success_rate !== undefined;
  if (hasRate) {
    const rate = Number(stats.success_rate);
    setText(els.statRate, `${rate.toFixed(1).replace(/\.0$/, "")}%`);
    setText(
      els.statRateHint,
      `${stats.success || 0} 成功 / ${(stats.success || 0) + (stats.failed || 0) + (stats.invalid || 0)} 已结算`,
    );
    els.rateBar.style.width = `${clampPercent(rate)}%`;
  } else {
    setText(els.statRate, "—");
    setText(els.statRateHint, "尚未产生签到记录");
    els.rateBar.style.width = "0%";
  }
}

function matchesStatusFilter(user, filter) {
  if (filter === "all") return true;
  if (filter === "unknown") {
    return user.status === "unknown" || user.status === "empty";
  }
  return user.status === filter;
}

function matchesQuery(user, query) {
  if (!query) return true;
  const meta = getStatusMeta(user.status);
  const haystack = [
    user.qq,
    meta.label,
    user.accounts,
    user.roles,
    user.success,
    user.failed,
    user.pending,
    user.invalid,
    user.unknown,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function getFilteredUsers() {
  const query = String(state.query || "").trim().toLowerCase();
  return state.users.filter(
    (user) => matchesStatusFilter(user, state.filter) && matchesQuery(user, query),
  );
}

function renderFilterCounts() {
  const counts = {
    all: state.users.length,
    healthy: 0,
    attention: 0,
    pending: 0,
    unknown: 0,
  };
  for (const user of state.users) {
    if (user.status === "unknown" || user.status === "empty") counts.unknown += 1;
    else if (Object.prototype.hasOwnProperty.call(counts, user.status)) {
      counts[user.status] += 1;
    }
  }

  setNumber(els.countAll, counts.all);
  setNumber(els.countHealthy, counts.healthy);
  setNumber(els.countAttention, counts.attention);
  setNumber(els.countPending, counts.pending);
  setNumber(els.countUnknown, counts.unknown);

  for (const button of els.filterPills.querySelectorAll("[data-filter]")) {
    button.classList.toggle("is-active", button.dataset.filter === state.filter);
    button.setAttribute(
      "aria-pressed",
      button.dataset.filter === state.filter ? "true" : "false",
    );
  }
}

function buildUserRow(user) {
  const row = createElement("button", "user-row");
  row.type = "button";
  row.dataset.qq = String(user.qq || "");
  row.setAttribute("aria-label", `查看 QQ ${user.qq} 的绑定详情`);

  const identity = createElement("span", "user-identity");
  const qqSuffix = String(user.qq || "").slice(-2).padStart(2, "0");
  identity.appendChild(createElement("span", "user-avatar", qqSuffix));
  const identityCopy = createElement("span");
  identityCopy.appendChild(createElement("span", "user-primary", `QQ ${user.qq}`));
  identityCopy.appendChild(
    createElement("span", "user-secondary", `${user.accounts || 0} 个蜗牛账号`),
  );
  identity.appendChild(identityCopy);

  const bindingCell = createElement("span", "cell-stack user-binding-cell");
  bindingCell.appendChild(createElement("strong", "", `${user.roles || 0} 个角色`));
  bindingCell.appendChild(createElement("small", "", `${user.accounts || 0} 个账号`));

  const signCell = createElement("span", "cell-stack user-sign-cell");
  signCell.appendChild(createElement("strong", "", `${user.success || 0} 成功`));
  signCell.appendChild(
    createElement(
      "small",
      "",
      `${user.already_claimed || 0} 已领取 · ${user.failed || 0} 失败 · ${user.pending || 0} 处理中`,
    ),
  );

  const statusCell = createElement("span", "user-status-cell");
  statusCell.appendChild(createStatusBadge(user.status));

  const timeCell = createElement("span", "time-cell user-time-cell", formatRelative(user.last_updated));
  timeCell.title = formatDateTime(user.last_updated);

  row.append(
    identity,
    bindingCell,
    signCell,
    statusCell,
    timeCell,
    createElement("span", "row-chevron", "›"),
  );
  return row;
}

function renderUserList() {
  const users = getFilteredUsers();
  if (!state.users.length) {
    setText(els.userSummary, "当前没有有效绑定用户");
    renderUserEmpty("还没有绑定用户", "用户完成账号绑定后，会在这里显示签到概况。");
    return;
  }

  if (!users.length) {
    setText(
      els.userSummary,
      `共 ${state.users.length} 位用户，当前筛选无匹配结果`,
    );
    renderUserEmpty("没有匹配的用户", "尝试更换筛选条件或清空搜索关键词。");
    return;
  }

  setText(
    els.userSummary,
    `共 ${state.users.length} 位用户，当前显示 ${users.length} 位`,
  );
  const fragment = document.createDocumentFragment();
  for (const user of users) fragment.appendChild(buildUserRow(user));
  els.userList.replaceChildren(fragment);
}

function renderPendingUnavailable() {
  setText(els.pendingSummary, "队列读取失败");
  setText(els.pendingCount, "0");
  setText(els.pendingRoles, "--");
  setText(els.pendingDue, "--");
  setText(els.pendingExpired, "--");
  els.pendingList.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取网页暂存队列"),
  );
}

function buildPendingItem(item) {
  const node = createElement(
    "div",
    `pending-item${Number(item.due) > 0 ? " is-due" : ""}`,
  );
  node.title = `最早到期：${formatDateTime(item.earliest_expiry)}`;

  const suffix = String(item.qq || "").slice(-2).padStart(2, "0");
  node.appendChild(createElement("span", "pending-avatar", suffix));

  const main = createElement("div", "pending-item-main");
  main.appendChild(createElement("strong", "", `QQ ${item.qq}`));
  main.appendChild(
    createElement(
      "span",
      "",
      `${item.roles || 0} 角色 · 自动 ${item.auto || 0} · 手动 ${item.manual || 0}`,
    ),
  );
  node.appendChild(main);

  const tags = createElement("div", "pending-tags");
  if (Number(item.due) > 0) {
    tags.appendChild(createElement("span", "mini-tag is-due", `${item.due} 个待签到`));
  } else if (Number(item.auto) > 0) {
    tags.appendChild(createElement("span", "mini-tag is-auto", "自动排队"));
  } else {
    tags.appendChild(createElement("span", "mini-tag", "等待指令"));
  }
  if (item.earliest_expiry) {
    tags.appendChild(
      createElement("span", "mini-tag", `至 ${formatDateTime(item.earliest_expiry)}`),
    );
  }
  node.appendChild(tags);
  return node;
}

function renderPending(pending) {
  setNumber(els.pendingCount, pending.qq_count || 0);
  setNumber(els.pendingRoles, pending.roles || 0);
  setNumber(els.pendingDue, pending.due_roles || 0);
  setNumber(els.pendingExpired, pending.expired_roles || 0);
  setText(
    els.pendingSummary,
    pending.qq_count
      ? `${pending.qq_count} 位用户的申请等待处理`
      : "当前没有待处理申请",
  );

  const items = Array.isArray(pending.items) ? pending.items : [];
  if (!items.length) {
    els.pendingList.replaceChildren(
      createElement("div", "empty-inline", "暂无待导入申请，网页队列为空"),
    );
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const item of items) fragment.appendChild(buildPendingItem(item));
  els.pendingList.replaceChildren(fragment);
}

function renderRuntimeUnavailable() {
  els.schedulerPill.className = "health-pill is-offline";
  setText(els.schedulerPill, "不可用");
  els.runtimeChecks.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取运行状态"),
  );
  els.jobList.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取定时任务"),
  );
  els.autoSignProgress.hidden = true;
}

function buildCheckItem(label, configured) {
  const item = createElement(
    "div",
    `check-item ${configured ? "is-ok" : "is-warn"}`,
  );
  item.title = configured ? `${label}：已配置` : `${label}：未配置`;
  item.appendChild(createElement("i"));
  item.appendChild(createElement("span", "", label));
  return item;
}

function renderRuntime(runtime) {
  const online = Boolean(runtime.scheduler_running);
  els.schedulerPill.className = `health-pill ${online ? "is-online" : "is-offline"}`;
  els.schedulerPill.replaceChildren(
    createElement("i"),
    document.createTextNode(online ? "运行中" : "未运行"),
  );

  const checks = [
    ["签到请求头", runtime.headers_configured],
    ["网页绑定服务", runtime.portal_configured],
    ["数据加密密钥", runtime.encryption_configured],
  ];
  const fragment = document.createDocumentFragment();
  for (const [label, configured] of checks) {
    fragment.appendChild(buildCheckItem(label, Boolean(configured)));
  }
  els.runtimeChecks.replaceChildren(fragment);

  const jobs = (Array.isArray(runtime.jobs) ? runtime.jobs : []).filter(
    (job) => job.service !== "strategy",
  );
  setText(els.jobCount, `${jobs.length} 项`);
  if (!jobs.length) {
    els.jobList.replaceChildren(
      createElement("div", "empty-inline", "当前没有已注册的定时任务"),
    );
  } else {
    const jobFragment = document.createDocumentFragment();
    for (const job of jobs) {
      const row = createElement("div", "job-item");
      row.appendChild(createElement("strong", "", job.label || job.id || "未命名任务"));
      const nextRunSeconds = parseISOTime(job.next_run_time);
      const nextRun = createElement(
        "span",
        "",
        nextRunSeconds ? formatRelative(nextRunSeconds) : "未安排",
      );
      nextRun.title = nextRunSeconds ? formatDateTime(nextRunSeconds) : "";
      row.appendChild(nextRun);
      jobFragment.appendChild(row);
    }
    els.jobList.replaceChildren(jobFragment);
  }

  renderAutoSignProgress(runtime);
}

function renderAutoSignProgress(runtime) {
  const progress = runtime.auto_sign_progress || {};
  const running = Boolean(progress.running);
  const keepSignRunning = Boolean(runtime.keep_sign_running);
  const lastFinished = Number(progress.last_finished_at || 0);
  if (!running && !keepSignRunning && lastFinished <= 0) {
    els.autoSignProgress.hidden = true;
    return;
  }

  els.autoSignProgress.hidden = false;
  const total = Math.max(0, Number(progress.total_users || 0));
  const completed = Math.max(0, Number(progress.completed_users || 0));
  const percent = total > 0 ? clampPercent((completed / total) * 100) : 0;

  const head = createElement("div", "progress-card-head");
  head.appendChild(
    createElement(
      "span",
      "",
      running ? "全量签到执行中" : keepSignRunning ? "签到保活执行中" : "最近一次全量签到",
    ),
  );
  head.appendChild(createElement("span", "", total ? `${completed}/${total}` : "待命"));

  const track = createElement("div", "progress-track");
  const bar = createElement("span");
  bar.style.width = `${percent}%`;
  track.appendChild(bar);

  let detail = "";
  if (running) {
    detail = progress.current_user
      ? `当前：QQ ${progress.current_user}${progress.current_role ? ` · ${progress.current_role}` : ""}`
      : "正在准备签到任务…";
  } else if (lastFinished > 0) {
    detail = `完成于 ${formatRelative(lastFinished)}`;
  } else if (keepSignRunning) {
    detail = "正在保活签到会话";
  }
  els.autoSignProgress.replaceChildren(
    head,
    track,
    createElement("p", "", detail),
  );
}

function buildStrategyAuthorCard(author) {
  const card = createElement("article", "strategy-author-card");
  const top = createElement("div", "strategy-author-top");
  const name = createElement("strong", "strategy-author-name", author.name || "未命名作者");
  name.title = String(author.name || "未命名作者");
  top.appendChild(name);

  const badges = createElement("div", "strategy-author-badges");
  if (author.cached) {
    badges.appendChild(createElement("span", "mini-tag is-auto", "已缓存"));
  } else {
    badges.appendChild(createElement("span", "mini-tag is-due", "待同步"));
  }
  if (author.cached && !author.cache_readable) {
    badges.appendChild(createElement("span", "mini-tag is-due", "缓存异常"));
  }
  top.appendChild(badges);
  card.appendChild(top);

  const metrics = createElement("div", "strategy-author-metrics");
  const articleMetric = createElement("div", "strategy-metric");
  articleMetric.appendChild(createElement("strong", "", `${author.article_count || 0} 篇`));
  articleMetric.appendChild(createElement("span", "", "缓存文章"));
  const latestMetric = createElement("div", "strategy-metric");
  const latestText = author.latest_article_at
    ? formatRelative(author.latest_article_at)
    : "暂无文章";
  const latestValue = createElement("strong", "", latestText);
  latestValue.title = author.latest_article_at
    ? formatDateTime(author.latest_article_at)
    : "";
  latestMetric.appendChild(latestValue);
  latestMetric.appendChild(createElement("span", "", "最近文章"));
  metrics.append(articleMetric, latestMetric);
  card.appendChild(metrics);

  const foot = createElement("div", "strategy-author-foot");
  const cacheUpdated = Number(author.cache_updated_at || 0);
  const syncText = cacheUpdated ? `缓存 ${formatRelative(cacheUpdated)}` : "尚无缓存记录";
  const syncNode = createElement("span", "", syncText);
  syncNode.title = cacheUpdated ? formatDateTime(cacheUpdated) : "";
  foot.appendChild(syncNode);
  foot.appendChild(
    createElement("span", "", author.saved ? "作者列表" : "仅本地缓存"),
  );
  card.appendChild(foot);

  const actions = createElement("div", "strategy-card-actions");
  if (author.saved) {
    const editButton = createElement("button", "strategy-card-action", "编辑");
    editButton.type = "button";
    editButton.addEventListener("click", () => {
      openStrategyEditor("author", "edit", { item: author });
    });
    actions.appendChild(editButton);
  }
  if (author.cached && author.cache_readable) {
    const articlesButton = createElement("button", "strategy-card-action", "文章");
    articlesButton.type = "button";
    articlesButton.addEventListener("click", () => {
      void openStrategyArticles(String(author.name || ""));
    });
    actions.appendChild(articlesButton);
  }
  if (author.cached) {
    const cacheButton = createElement("button", "strategy-card-action", "清理缓存");
    cacheButton.type = "button";
    cacheButton.addEventListener("click", () => {
      void deleteStrategyAuthor(String(author.name || ""), "cache");
    });
    actions.appendChild(cacheButton);
  }
  if (author.saved) {
    const removeButton = createElement(
      "button",
      "strategy-card-action is-danger",
      "移除作者",
    );
    removeButton.type = "button";
    removeButton.addEventListener("click", () => {
      void deleteStrategyAuthor(String(author.name || ""), "remove");
    });
    actions.appendChild(removeButton);
  }
  card.appendChild(actions);
  return card;
}

function buildStrategyPushItem(item) {
  const node = createElement("div", "strategy-push-item");
  const kind = String(item.kind || "unknown");
  node.appendChild(
    createElement(
      "span",
      `strategy-push-kind${kind === "group" ? "" : " is-private"}`,
      kind === "group" ? "群聊" : kind === "private" ? "私聊" : "目标",
    ),
  );
  const copy = createElement("span", "strategy-push-copy");
  const identifier = String(item.identifier || item.target || "未命名目标");
  const title = createElement("strong", "", identifier);
  title.title = String(item.target || identifier);
  copy.appendChild(title);
  copy.appendChild(
    createElement("small", "", item.platform ? `${item.platform} · ${item.label}` : item.label),
  );
  node.appendChild(copy);

  const actions = createElement("div", "strategy-push-actions");
  const editButton = createElement("button", "strategy-card-action", "编辑");
  editButton.type = "button";
  editButton.addEventListener("click", () => {
    openStrategyEditor("push", "edit", { item });
  });
  const deleteButton = createElement(
    "button",
    "strategy-card-action is-danger",
    "删除",
  );
  deleteButton.type = "button";
  deleteButton.addEventListener("click", () => {
    void deleteStrategyPush(item);
  });
  actions.append(editButton, deleteButton);
  node.appendChild(actions);
  return node;
}

function buildSigninTargetItem(item) {
  const node = createElement("div", "strategy-push-item signin-target-item");
  const kind = String(item.kind || "unknown");
  node.appendChild(
    createElement(
      "span",
      `strategy-push-kind${kind === "group" ? "" : " is-private"}`,
      kind === "group" ? "群聊" : kind === "private" ? "私聊" : "目标",
    ),
  );
  const copy = createElement("span", "strategy-push-copy");
  const identifier = String(item.identifier || item.target || "未命名目标");
  const title = createElement("strong", "", identifier);
  title.title = String(item.target || identifier);
  copy.appendChild(title);
  copy.appendChild(
    createElement(
      "small",
      "",
      item.platform ? `${item.platform} · ${item.label}` : item.label,
    ),
  );
  node.appendChild(copy);

  const actions = createElement("div", "strategy-push-actions");
  const editButton = createElement("button", "strategy-card-action", "编辑");
  editButton.type = "button";
  editButton.dataset.signinAction = "";
  editButton.addEventListener("click", () => {
    openSigninPushEditor("edit", item);
  });
  const deleteButton = createElement(
    "button",
    "strategy-card-action is-danger",
    "删除",
  );
  deleteButton.type = "button";
  deleteButton.dataset.signinAction = "";
  deleteButton.addEventListener("click", () => {
    void deleteSigninPush(item);
  });
  actions.append(editButton, deleteButton);
  node.appendChild(actions);
  return node;
}

function renderSigninPreferences(signin) {
  const gift = signin?.gift && typeof signin.gift === "object" ? signin.gift : {};
  const claimMode = ["all", "none"].includes(gift.claim_mode)
    ? gift.claim_mode
    : "all";
  els.signinGiftMode.value = claimMode;
  els.signinGiftPill.className = `health-pill ${claimMode === "all" ? "is-online" : "is-offline"}`;
  els.signinGiftPill.replaceChildren(
    createElement("i"),
    document.createTextNode(claimMode === "all" ? "已启用" : "已关闭"),
  );

  const notification =
    signin?.notification && typeof signin.notification === "object"
      ? signin.notification
      : {};
  els.signinNotifyEnabled.checked = notification.enabled !== false;
  els.signinNotifyImage.checked = notification.include_reward_image !== false;
  const detailModes = Array.isArray(notification.detail_mode_options)
    ? notification.detail_mode_options
    : [];
  if (detailModes.length) {
    const detailFragment = document.createDocumentFragment();
    for (const option of detailModes) {
      const node = createElement("option", "", option.label || option.value || "");
      node.value = String(option.value || "");
      detailFragment.appendChild(node);
    }
    els.signinDetailMode.replaceChildren(detailFragment);
  }
  const detailMode = ["issues_overview", "issues_only", "full"].includes(
    notification.detail_mode,
  )
    ? notification.detail_mode
    : "issues_overview";
  els.signinDetailMode.value = detailMode;
  const targets = Array.isArray(notification.targets)
    ? notification.targets
    : [];
  setNumber(els.signinTargetCount, targets.length);
  if (!targets.length) {
    els.signinTargetList.replaceChildren(
      createElement("div", "empty-inline", "尚未配置签到通知目标"),
    );
  } else {
    const fragment = document.createDocumentFragment();
    for (const item of targets) {
      fragment.appendChild(buildSigninTargetItem(item));
    }
    els.signinTargetList.replaceChildren(fragment);
  }
  updateMutationControls();
}

function renderSigninUnavailable() {
  els.signinGiftPill.className = "health-pill is-offline";
  els.signinGiftPill.replaceChildren(
    createElement("i"),
    document.createTextNode("不可用"),
  );
  els.signinNotifyEnabled.checked = false;
  els.signinNotifyImage.checked = false;
  els.signinDetailMode.value = "issues_overview";
  setNumber(els.signinTargetCount, 0);
  els.signinTargetList.replaceChildren(
    createElement("div", "empty-inline", "无法读取签到策略与通知目标"),
  );
}

function renderStrategyUnavailable() {
  setText(els.strategyStatAuthors, "--");
  setText(els.strategyStatArticles, "--");
  setText(els.strategyStatTargets, "--");
  setText(els.strategyStatJob, "不可用");
  setText(els.strategyStatJobHint, "暂时无法读取攻略服务状态");
  setText(els.strategyAuthorSummary, "暂时无法读取攻略作者缓存");
  setNumber(els.strategyAuthorCount, 0);
  setNumber(els.strategyPushCount, 0);
  setText(els.strategyPushSummary, "暂时无法读取推送目标");
  els.strategyHealthPill.className = "health-pill is-offline";
  setText(els.strategyHealthPill, "不可用");
  els.strategyChecks.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取攻略配置状态"),
  );
  els.strategyJobList.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取攻略更新任务"),
  );
  els.strategyAuthorList.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取攻略作者缓存"),
  );
  els.strategyPushList.replaceChildren(
    createElement("div", "empty-inline", "暂时无法读取攻略推送目标"),
  );
}

function renderStrategy(strategy) {
  const authors = Array.isArray(strategy.authors) ? strategy.authors : [];
  const pushTargets = Array.isArray(strategy.push_targets)
    ? strategy.push_targets
    : [];
  const job = strategy.job || null;
  const exporterConfigured = Boolean(strategy.exporter_configured);
  const jobRunning = Boolean(job && strategy.scheduler_running);
  const latestSync = Number(strategy.latest_cache_sync_at || 0);

  setNumber(els.strategyStatAuthors, strategy.saved_author_count || authors.length);
  setText(
    els.strategyStatAuthorsHint,
    `缓存 ${strategy.cached_author_count || 0} · 可读 ${strategy.readable_author_count || 0}`,
  );
  setNumber(els.strategyStatArticles, strategy.article_count || 0);
  setText(
    els.strategyStatArticlesHint,
    latestSync ? `最近同步 ${formatRelative(latestSync)}` : "尚无缓存同步记录",
  );
  setNumber(els.strategyStatTargets, strategy.push_target_count || 0);
  const groupCount = pushTargets.filter((item) => item.kind === "group").length;
  const privateCount = pushTargets.filter((item) => item.kind === "private").length;
  setText(
    els.strategyStatTargetsHint,
    strategy.push_target_count
      ? `群聊 ${groupCount} · 私聊 ${privateCount}`
      : "尚未开启攻略推送",
  );

  setText(els.strategyStatJob, jobRunning ? "运行中" : exporterConfigured ? "待启用" : "未配置");
  const nextRun = parseISOTime(job?.next_run_time);
  setText(
    els.strategyStatJobHint,
    nextRun
      ? `下次更新 ${formatRelative(nextRun)}`
      : exporterConfigured
        ? "已配置服务，但更新任务未注册"
        : "需要配置 API 地址与认证密钥",
  );

  const ready = exporterConfigured && jobRunning;
  els.strategyHealthPill.className = `health-pill ${ready ? "is-online" : "is-offline"}`;
  els.strategyHealthPill.replaceChildren(
    createElement("i"),
    document.createTextNode(ready ? "运行中" : exporterConfigured ? "待启用" : "未配置"),
  );

  const checks = [
    ["攻略 API 地址", strategy.exporter_url_configured],
    ["API 认证密钥", strategy.exporter_key_configured],
    ["更新任务", Boolean(job)],
    ["调度器", strategy.scheduler_running],
  ];
  const checkFragment = document.createDocumentFragment();
  for (const [label, configured] of checks) {
    checkFragment.appendChild(buildCheckItem(label, Boolean(configured)));
  }
  els.strategyChecks.replaceChildren(checkFragment);

  setText(els.strategyJobCount, job ? "1 项" : "0 项");
  if (!job) {
    els.strategyJobList.replaceChildren(
      createElement(
        "div",
        "empty-inline",
        exporterConfigured
          ? "已配置攻略服务，但更新任务没有注册"
          : "未配置攻略 API 地址或认证密钥，更新任务未注册",
      ),
    );
  } else {
    const row = createElement("div", "job-item");
    row.appendChild(createElement("strong", "", job.label || "攻略更新监控"));
    const nextRunSeconds = parseISOTime(job.next_run_time);
    const nextRunNode = createElement(
      "span",
      "",
      nextRunSeconds ? formatRelative(nextRunSeconds) : "未安排",
    );
    nextRunNode.title = nextRunSeconds ? formatDateTime(nextRunSeconds) : "";
    row.appendChild(nextRunNode);
    els.strategyJobList.replaceChildren(row);
  }

  setText(
    els.strategyAuthorSummary,
    authors.length
      ? `共 ${authors.length} 位作者 · ${strategy.readable_author_count || 0} 位缓存可读 · ${strategy.article_count || 0} 篇文章`
      : "当前没有已保存或已缓存的攻略作者",
  );
  setNumber(els.strategyAuthorCount, authors.length);
  if (!authors.length) {
    els.strategyAuthorList.replaceChildren(
      createElement("div", "empty-inline", "暂无攻略作者缓存"),
    );
  } else {
    const authorFragment = document.createDocumentFragment();
    for (const author of authors) {
      authorFragment.appendChild(buildStrategyAuthorCard(author));
    }
    els.strategyAuthorList.replaceChildren(authorFragment);
  }

  setText(
    els.strategyPushSummary,
    pushTargets.length
      ? `${pushTargets.length} 个会话已开启自动推送`
      : "尚未开启攻略推送",
  );
  setNumber(els.strategyPushCount, pushTargets.length);
  if (!pushTargets.length) {
    els.strategyPushList.replaceChildren(
      createElement("div", "empty-inline", "暂无攻略推送目标"),
    );
  } else {
    const pushFragment = document.createDocumentFragment();
    for (const item of pushTargets) {
      pushFragment.appendChild(buildStrategyPushItem(item));
    }
    els.strategyPushList.replaceChildren(pushFragment);
  }
}

function setDrawerOpen(open) {
  window.clearTimeout(state.drawerCloseTimer);
  if (open) {
    state.lastFocusedElement = document.activeElement;
    els.drawerBackdrop.hidden = false;
    els.userDrawer.hidden = false;
    document.body.classList.add("drawer-open");
    window.requestAnimationFrame(() => {
      els.drawerBackdrop.classList.add("is-open");
      els.userDrawer.classList.add("is-open");
      els.drawerCloseBtn.focus({ preventScroll: true });
    });
    return;
  }

  els.drawerBackdrop.classList.remove("is-open");
  els.userDrawer.classList.remove("is-open");
  document.body.classList.remove("drawer-open");
  state.drawerCloseTimer = window.setTimeout(() => {
    els.drawerBackdrop.hidden = true;
    els.userDrawer.hidden = true;
  }, 270);
  if (state.lastFocusedElement instanceof HTMLElement) {
    state.lastFocusedElement.focus({ preventScroll: true });
  }
}

function closeUserDrawer() {
  state.detailToken += 1;
  state.activeQQ = "";
  setDrawerOpen(false);
}

function renderDrawerLoading() {
  els.drawerBody.replaceChildren(
    createElement("div", "drawer-loading", "正在读取脱敏角色详情…"),
  );
}

function renderDrawerError(qq, message) {
  els.drawerSubtitle.textContent = "读取失败";
  const wrapper = createElement("div", "drawer-error");
  wrapper.appendChild(createElement("strong", "", "无法读取该用户详情"));
  wrapper.appendChild(createElement("span", "", message));
  const retry = createElement("button", "button ghost empty-action", "重试");
  retry.type = "button";
  retry.addEventListener("click", () => void openUserDrawer(qq));
  wrapper.appendChild(retry);
  els.drawerBody.replaceChildren(wrapper);
}

function buildRoleCard(item, qq) {
  const stateKey = String(item.state || "unknown").toLowerCase();
  const isChannel = item.binding_type === "channel" || Boolean(item.channel);
  const card = createElement("article", `role-card is-${stateKey}`);
  const top = createElement("div", "role-top");
  top.appendChild(createElement("span", "role-name", item.info || "未知角色"));
  top.appendChild(createStatusBadge(stateKey));
  card.appendChild(top);

  const meta = createElement("div", "role-meta");
  if (isChannel) {
    meta.appendChild(
      createElement(
        "span",
        "",
        `渠道服 · ${item.platform_name || item.platform || "未知渠道"}`,
      ),
    );
  } else if (item.server) {
    meta.appendChild(createElement("span", "", item.server));
  }
  if (item.game_id) meta.appendChild(createElement("span", "", `区服 ${item.game_id}`));
  if (item.account) meta.appendChild(createElement("span", "", `账号 ${item.account}`));
  if (item.role_id) meta.appendChild(createElement("span", "", `角色 ${item.role_id}`));
  if (item.updated_at) {
    const updated = createElement("span", "", `更新 ${formatRelative(item.updated_at)}`);
    updated.title = formatDateTime(item.updated_at);
    meta.appendChild(updated);
  }
  card.appendChild(meta);

  if (item.message) {
    card.appendChild(createElement("p", "role-message", item.message));
  }

  const actions = createElement("div", "role-actions");
  if (!isChannel) {
    const editButton = createElement("button", "role-action", "编辑");
    editButton.type = "button";
    editButton.dataset.mutationAction = "";
    editButton.dataset.forceDisabled = stateKey === "invalid" ? "1" : "0";
    editButton.setAttribute("aria-label", `编辑第 ${item.index} 个角色`);
    editButton.addEventListener("click", () => {
      openBindingEditor("edit", { qq, item });
    });
    actions.append(editButton);
  }

  const deleteButton = createElement("button", "role-action is-danger", "删除");
  deleteButton.type = "button";
  deleteButton.dataset.mutationAction = "";
  deleteButton.setAttribute("aria-label", `删除第 ${item.index} 个角色`);
  deleteButton.addEventListener("click", () => {
    void deleteRoleBinding(qq, item);
  });

  actions.append(deleteButton);
  card.appendChild(actions);
  return card;
}

function buildMetric(value, label) {
  const metric = createElement("div", "drawer-metric");
  metric.appendChild(createElement("strong", "", String(value ?? 0)));
  metric.appendChild(createElement("span", "", label));
  return metric;
}

function renderUserDetail(data) {
  const qq = String(data.qq || state.activeQQ);
  const counts = data.state_counts || {};
  const items = Array.isArray(data.items) ? data.items : [];
  setText(els.drawerTitle, `QQ ${qq}`);
  setText(
    els.drawerSubtitle,
    `最近更新 ${formatRelative(data.last_updated)} · 数据已脱敏`,
  );

  const summary = createElement("div", "drawer-summary");
  const summaryCopy = createElement("div", "drawer-summary-primary");
  summaryCopy.appendChild(createElement("strong", "", `QQ ${qq}`));
  summaryCopy.appendChild(
    createElement(
      "span",
      "",
      `${data.accounts || 0} 个账号 · ${data.roles || 0} 个角色 · 最近 ${formatRelative(data.last_updated)}`,
    ),
  );
  summary.appendChild(summaryCopy);
  summary.appendChild(createStatusBadge(data.status));

  const metrics = createElement("div", "drawer-metric-grid");
  metrics.append(
    buildMetric(counts.success || 0, "成功"),
    buildMetric(counts.already_claimed || 0, "已领取"),
    buildMetric(counts.failed || 0, "失败"),
    buildMetric(counts.pending || 0, "处理中"),
    buildMetric(counts.invalid || 0, "数据异常"),
  );

  const detailActions = createElement("div", "detail-actions");
  const addRoleButton = createElement(
    "button",
    "button ghost detail-action",
    "新增官服角色",
  );
  addRoleButton.type = "button";
  addRoleButton.dataset.mutationAction = "";
  addRoleButton.addEventListener("click", () => {
    openBindingEditor("create", { qq });
  });
  const deleteUserButton = createElement(
    "button",
    "button ghost detail-action is-danger",
    "删除该 QQ 全部绑定",
  );
  deleteUserButton.type = "button";
  deleteUserButton.dataset.mutationAction = "";
  deleteUserButton.addEventListener("click", () => {
    void deleteUserBindings(qq, Number(data.roles || 0));
  });
  detailActions.append(addRoleButton, deleteUserButton);

  const heading = createElement("div", "detail-section-heading");
  heading.appendChild(createElement("h3", "", "角色明细"));
  heading.appendChild(createElement("span", "", `${items.length} 个角色 · 已脱敏`));

  const roleList = createElement("div", "role-list");
  if (items.length) {
    const fragment = document.createDocumentFragment();
    for (const item of items) fragment.appendChild(buildRoleCard(item, qq));
    roleList.replaceChildren(fragment);
  } else {
    roleList.appendChild(
      createElement("div", "empty-inline", "该用户没有可展示的角色记录"),
    );
  }

  const note = createElement(
    "p",
    "detail-note",
    "管理页只展示脱敏后的手机号与角色 ID。官服角色可新增或编辑；渠道服角色仅能通过网页提交绑定，管理页只允许删除，签到状态展示最近一次自动或手动签到结果。",
  );
  const lockNote = createElement(
    "p",
    "mutation-lock-note",
    isMutationLocked()
      ? `${getMutationLockMessage()}，绑定操作已暂时锁定。`
      : "已登录管理员可以新增、编辑或删除绑定；删除操作不可撤销。",
  );
  els.drawerBody.replaceChildren(
    summary,
    metrics,
    detailActions,
    lockNote,
    heading,
    roleList,
    note,
  );
  updateMutationControls();
}

async function openUserDrawer(qq) {
  const normalizedQQ = String(qq || "").trim();
  if (!normalizedQQ) return;
  state.activeQQ = normalizedQQ;
  const token = ++state.detailToken;
  setText(els.drawerTitle, `QQ ${normalizedQQ}`);
  setText(els.drawerSubtitle, "正在读取角色详情…");
  renderDrawerLoading();
  setDrawerOpen(true);

  try {
    const data = await apiGet("admin/user", { qq: normalizedQQ });
    if (token !== state.detailToken || state.activeQQ !== normalizedQQ) return;
    renderUserDetail(data || {});
  } catch (error) {
    if (token !== state.detailToken || state.activeQQ !== normalizedQQ) return;
    renderDrawerError(normalizedQQ, normalizeError(error));
  }
}

async function syncWebBindings() {
  if (state.syncing) return;
  state.syncing = true;
  const label = els.syncBtn.querySelector("span");
  els.syncBtn.disabled = true;
  els.syncBtn.classList.add("is-loading");
  els.syncBtn.setAttribute("aria-busy", "true");
  setText(label, "同步中…");

  try {
    const result = await apiPost("admin/signin/sync", {});
    const imported = Number(result?.imported || 0);
    showToast(
      imported > 0 ? `已导入 ${imported} 个网页申请` : "没有新的网页申请",
    );
    await loadBootstrap();
  } catch (error) {
    showToast(`同步失败：${normalizeError(error)}`, "error");
  } finally {
    state.syncing = false;
    els.syncBtn.disabled = false;
    els.syncBtn.classList.remove("is-loading");
    els.syncBtn.removeAttribute("aria-busy");
    setText(label, "同步网页申请");
  }
}

function bindEvents() {
  els.themeBtn.addEventListener("click", cycleTheme);
  els.refreshBtn.addEventListener("click", () => void loadBootstrap({ notify: true }));
  els.syncBtn.addEventListener("click", () => void syncWebBindings());
  els.dismissBannerBtn.addEventListener("click", hideBanner);
  els.addBindingBtn.addEventListener("click", () => openBindingEditor("create"));
  els.addStrategyAuthorBtn.addEventListener("click", () => {
    openStrategyEditor("author", "create");
  });
  els.addStrategyPushBtn.addEventListener("click", () => {
    openStrategyEditor("push", "create");
  });
  els.addSigninTargetBtn.addEventListener("click", () => {
    openSigninPushEditor("create");
  });
  els.signinGiftForm.addEventListener("submit", (event) => {
    void saveSigninGiftSettings(event);
  });
  els.signinNotificationForm.addEventListener("submit", (event) => {
    void saveSigninNotificationSettings(event);
  });
  els.bindingCloseBtn.addEventListener("click", closeBindingDialog);
  els.bindingCancelBtn.addEventListener("click", closeBindingDialog);
  els.bindingBackdrop.addEventListener("click", closeBindingDialog);
  els.bindingForm.addEventListener("submit", (event) => {
    void submitBindingForm(event);
  });
  els.strategyCloseBtn.addEventListener("click", closeStrategyDialog);
  els.strategyCancelBtn.addEventListener("click", closeStrategyDialog);
  els.strategyBackdrop.addEventListener("click", closeStrategyDialog);
  els.strategyForm.addEventListener("submit", (event) => {
    void submitStrategyForm(event);
  });
  els.signinPushCloseBtn.addEventListener("click", closeSigninPushDialog);
  els.signinPushCancelBtn.addEventListener("click", closeSigninPushDialog);
  els.signinPushBackdrop.addEventListener("click", closeSigninPushDialog);
  els.signinPushForm.addEventListener("submit", (event) => {
    void submitSigninPushForm(event);
  });
  els.articlesCloseBtn.addEventListener("click", closeArticlesDialog);
  els.articlesCloseFooterBtn.addEventListener("click", closeArticlesDialog);
  els.articlesBackdrop.addEventListener("click", closeArticlesDialog);
  els.confirmCancelBtn.addEventListener("click", () => settleConfirmDialog(false));
  els.confirmOkBtn.addEventListener("click", () => settleConfirmDialog(true));
  els.confirmBackdrop.addEventListener("click", () => settleConfirmDialog(false));

  els.serviceTabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-service]");
    if (!tab) return;
    setActiveService(tab.dataset.service);
  });

  els.serviceTabs.addEventListener("keydown", (event) => {
    const tabs = [els.signinTab, els.strategyTab];
    const currentIndex = tabs.indexOf(document.activeElement);
    if (currentIndex < 0) return;
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    setActiveService(tabs[nextIndex].dataset.service, { focus: true });
  });

  els.filterPills.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter || "all";
    renderFilterCounts();
    renderUserList();
  });

  els.searchInput.addEventListener("input", () => {
    state.query = els.searchInput.value || "";
    renderUserList();
  });

  els.userList.addEventListener("click", (event) => {
    const row = event.target.closest("[data-qq]");
    if (!row) return;
    void openUserDrawer(row.dataset.qq);
  });

  els.drawerCloseBtn.addEventListener("click", closeUserDrawer);
  els.drawerBackdrop.addEventListener("click", closeUserDrawer);

  document.addEventListener("keydown", (event) => {
    if (!els.confirmDialog.hidden) {
      if (event.key === "Escape") {
        event.preventDefault();
        settleConfirmDialog(false);
      }
      return;
    }
    if (event.key === "Escape" && !els.bindingDialog.hidden) {
      closeBindingDialog();
      return;
    }
    if (event.key === "Escape" && !els.strategyDialog.hidden) {
      closeStrategyDialog();
      return;
    }
    if (event.key === "Escape" && !els.signinPushDialog.hidden) {
      closeSigninPushDialog();
      return;
    }
    if (event.key === "Escape" && !els.articlesDialog.hidden) {
      closeArticlesDialog();
      return;
    }
    if (event.key === "Escape" && !els.userDrawer.hidden) {
      closeUserDrawer();
      return;
    }
    if (
      event.key === "/" &&
      state.activeService === "signin" &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)
    ) {
      event.preventDefault();
      els.searchInput.focus();
    }
  });

  mediaQuery?.addEventListener?.("change", () => {
    if (state.themePreference === "auto") applyTheme();
  });
}

async function init() {
  state.themePreference = loadThemePreference();
  applyTheme();
  setActiveService("signin");
  bridge?.onContext?.(() => {
    if (state.themePreference === "auto") applyTheme();
  });
  bindEvents();

  try {
    await waitForBridgeReady();
    applyTheme();
    await loadBootstrap();
  } catch (error) {
    const message = normalizeError(error);
    showBanner(`管理页初始化失败：${message}`);
    setText(els.versionBadge, "加载失败");
    setText(els.lastUpdated, "连接失败");
    renderUserEmpty(
      "无法连接到 AstrBot",
      "请关闭当前窗口，从 AstrBot 插件详情中的页面入口重新打开。",
      "重试连接",
    );
    renderSigninUnavailable();
    renderPendingUnavailable();
    renderRuntimeUnavailable();
    renderStrategyUnavailable();
  }
}

void init();
