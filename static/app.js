const authPanel = document.getElementById("authPanel");
const appShell = document.getElementById("appShell");
const authForm = document.getElementById("authForm");
const authTitle = document.getElementById("authTitle");
const authNameField = document.getElementById("authNameField");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const authLoginModeBtn = document.getElementById("authLoginModeBtn");
const authSignupModeBtn = document.getElementById("authSignupModeBtn");
const authMessage = document.getElementById("authMessage");
const userSession = document.getElementById("userSession");
const userBadge = document.getElementById("userBadge");
const logoutBtn = document.getElementById("logoutBtn");

const form = document.getElementById("subscriptionForm");
const formMessage = document.getElementById("formMessage");
const formTitle = document.getElementById("formTitle");
const submitBtn = document.getElementById("submitBtn");
const cancelEditBtn = document.getElementById("cancelEditBtn");
const subscriptionsBody = document.getElementById("subscriptionsBody");
const emptySubscriptions = document.getElementById("emptySubscriptions");
const remindersList = document.getElementById("remindersList");
const emptyReminders = document.getElementById("emptyReminders");
const totalMonthlySpendEl = document.getElementById("totalMonthlySpend");
const subscriptionCountEl = document.getElementById("subscriptionCount");
const nextReminderEl = document.getElementById("nextReminder");
const pieChartEl = document.getElementById("pieChart");
const pieLegendEl = document.getElementById("pieLegend");
const nextPaymentInput = document.querySelector('input[name="nextPaymentDate"]');
const enableNotificationsBtn = document.getElementById("enableNotificationsBtn");
const notificationStatusEl = document.getElementById("notificationStatus");

const subscriptionCategorySelect = document.getElementById("subscriptionCategorySelect");
const newCategoryInput = document.getElementById("newCategoryInput");
const addCategoryBtn = document.getElementById("addCategoryBtn");
const categoryMessage = document.getElementById("categoryMessage");
const categoryList = document.getElementById("categoryList");
const searchInput = document.getElementById("searchInput");
const categoryFilterSelect = document.getElementById("categoryFilterSelect");
const sortSelect = document.getElementById("sortSelect");
const currencySelect = document.getElementById("currencySelect");
const billingCurrencyLabel = document.getElementById("billingCurrencyLabel");

let editingId = null;
let authMode = "login";
let currentUser = null;
let allSubscriptions = [];
let allReminders = [];
let allCategories = [];

const pieColors = [
  "#ff8a3d",
  "#2ec4b6",
  "#ffd166",
  "#4cc9f0",
  "#ff6b6b",
  "#80ed99",
  "#f4a261",
  "#90be6d",
];

const CURRENCY_STORAGE_KEY = "subtracker-currency";
const DEFAULT_CURRENCY = "USD";
let currentCurrency = DEFAULT_CURRENCY;
let currencyFormatter = createCurrencyFormatter(DEFAULT_CURRENCY);

function createCurrencyFormatter(code) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: code,
      maximumFractionDigits: code === "JPY" ? 0 : 2,
    });
  } catch (_error) {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: DEFAULT_CURRENCY,
    });
  }
}

function formatMoney(value) {
  return currencyFormatter.format(Number(value) || 0);
}

function isSupportedCurrency(code) {
  if (!currencySelect) {
    return code === DEFAULT_CURRENCY;
  }
  return Array.from(currencySelect.options).some((option) => option.value === code);
}

function getStoredCurrency() {
  try {
    const stored = (localStorage.getItem(CURRENCY_STORAGE_KEY) || "").toUpperCase();
    if (isSupportedCurrency(stored)) {
      return stored;
    }
  } catch (_error) {
    // ignore storage errors and use default
  }
  return DEFAULT_CURRENCY;
}

function setCurrency(code, persist = true) {
  const normalized = String(code || "").toUpperCase();
  currentCurrency = isSupportedCurrency(normalized) ? normalized : DEFAULT_CURRENCY;
  currencyFormatter = createCurrencyFormatter(currentCurrency);

  if (currencySelect) {
    currencySelect.value = currentCurrency;
  }
  if (billingCurrencyLabel) {
    billingCurrencyLabel.textContent = currentCurrency;
  }
  if (!persist) {
    return;
  }
  try {
    localStorage.setItem(CURRENCY_STORAGE_KEY, currentCurrency);
  } catch (_error) {
    // ignore storage errors
  }
}

function getCookieValue(name) {
  const pairs = document.cookie ? document.cookie.split("; ") : [];
  for (const pair of pairs) {
    const [key, ...rest] = pair.split("=");
    if (key === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return "";
}

function setMessage(targetEl, message, type = "") {
  targetEl.textContent = message;
  targetEl.classList.remove("error", "success");
  if (type) {
    targetEl.classList.add(type);
  }
}

function setFormMessage(message, type = "") {
  setMessage(formMessage, message, type);
}

function setAuthMessage(message, type = "") {
  setMessage(authMessage, message, type);
}

function setCategoryMessage(message, type = "") {
  setMessage(categoryMessage, message, type);
}

function toFriendlyCycle(cycle) {
  return cycle.charAt(0).toUpperCase() + cycle.slice(1);
}

function toFriendlyDate(dateString) {
  return new Date(`${dateString}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function setDefaultDate() {
  nextPaymentInput.valueAsDate = new Date();
}

function setAuthMode(mode) {
  authMode = mode;
  const isSignup = mode === "signup";

  authTitle.textContent = isSignup ? "Create Account" : "Sign In";
  authSubmitBtn.textContent = isSignup ? "Create Account" : "Sign In";
  authNameField.hidden = !isSignup;

  authLoginModeBtn.classList.toggle("active", !isSignup);
  authSignupModeBtn.classList.toggle("active", isSignup);

  const passwordInput = authForm.elements.authPassword;
  passwordInput.autocomplete = isSignup ? "new-password" : "current-password";
}

function clearDataState() {
  allSubscriptions = [];
  allReminders = [];
  allCategories = [];
}

function setAuthenticatedUser(user) {
  currentUser = user;
  const isLoggedIn = Boolean(user);

  authPanel.hidden = isLoggedIn;
  appShell.hidden = !isLoggedIn;
  userSession.hidden = !isLoggedIn;

  if (isLoggedIn) {
    userBadge.textContent = `${user.name} • ${user.email}`;
    setAuthMessage("");
    setDefaultDate();
    updateNotificationStatus();
    return;
  }

  userBadge.textContent = "";
  setFormMode("create");
  searchInput.value = "";
  categoryFilterSelect.value = "";
  sortSelect.value = "due_soon";
  clearDataState();
  renderCategoryControls();
  applyFiltersAndRender();
  updateNotificationStatus();
}

async function apiRequest(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = getCookieValue("subtracker_csrf");
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  const response = await fetch(url, {
    credentials: "same-origin",
    headers,
    ...options,
  });

  let body = {};
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }

  if (!response.ok) {
    const err = new Error(body.error || "Something went wrong");
    err.status = response.status;
    throw err;
  }

  return body;
}

function handleUnauthorized(error) {
  if (error && error.status === 401) {
    setAuthenticatedUser(null);
    setAuthMessage("Please sign in to continue.", "error");
    return true;
  }
  return false;
}

function renderSummary(totalMonthlySpend, nextReminder) {
  totalMonthlySpendEl.textContent = formatMoney(totalMonthlySpend || 0);

  if (!nextReminder) {
    nextReminderEl.textContent = "No reminders";
    return;
  }

  const dueText =
    nextReminder.daysUntilPayment === 0
      ? "due today"
      : `due in ${nextReminder.daysUntilPayment} day${nextReminder.daysUntilPayment === 1 ? "" : "s"}`;

  nextReminderEl.textContent = `${nextReminder.name} (${dueText})`;
}

function renderSubscriptions(subscriptions) {
  subscriptionsBody.innerHTML = "";

  if (!subscriptions.length) {
    emptySubscriptions.style.display = "block";
    subscriptionCountEl.textContent = "0 items";
    return;
  }

  emptySubscriptions.style.display = "none";
  subscriptionCountEl.textContent = `${subscriptions.length} item${subscriptions.length === 1 ? "" : "s"}`;

  for (const sub of subscriptions) {
    const row = document.createElement("tr");

    const nameCell = document.createElement("td");
    nameCell.textContent = `${sub.name} (${sub.category})`;

    const cycleCell = document.createElement("td");
    cycleCell.textContent = toFriendlyCycle(sub.billingCycle);

    const amountCell = document.createElement("td");
    amountCell.textContent = formatMoney(sub.amount);

    const monthlyCell = document.createElement("td");
    monthlyCell.textContent = formatMoney(sub.monthlyCost);

    const dateCell = document.createElement("td");
    dateCell.textContent = toFriendlyDate(sub.nextPaymentDate);

    const actionCell = document.createElement("td");
    const actionGroup = document.createElement("div");
    actionGroup.className = "action-group";

    const editBtn = document.createElement("button");
    editBtn.className = "mini-btn edit-btn";
    editBtn.type = "button";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => {
      setFormMode("edit", sub);
      setFormMessage(`Editing ${sub.name}.`, "success");
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "mini-btn";
    deleteBtn.type = "button";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => deleteSubscription(sub.id));

    actionGroup.append(editBtn, deleteBtn);
    actionCell.appendChild(actionGroup);

    row.append(nameCell, cycleCell, amountCell, monthlyCell, dateCell, actionCell);
    subscriptionsBody.appendChild(row);
  }
}

function renderReminders(reminders) {
  remindersList.innerHTML = "";

  if (!reminders.length) {
    emptyReminders.style.display = "block";
    return;
  }

  emptyReminders.style.display = "none";

  for (const reminder of reminders) {
    const item = document.createElement("li");
    item.className = "reminder-item";

    const title = document.createElement("strong");
    title.textContent = reminder.name;

    const dateLine = document.createElement("span");
    dateLine.textContent = `${toFriendlyDate(reminder.nextPaymentDate)} • ${formatMoney(reminder.amount)} (${toFriendlyCycle(
      reminder.billingCycle,
    )})`;

    const dueLine = document.createElement("span");
    dueLine.textContent =
      reminder.daysUntilPayment === 0
        ? "Due today"
        : `Due in ${reminder.daysUntilPayment} day${reminder.daysUntilPayment === 1 ? "" : "s"}`;

    if (reminder.isDueSoon) {
      dueLine.classList.add("due-soon");
    }

    item.append(title, dateLine, dueLine);
    remindersList.appendChild(item);
  }
}

function renderPieChart(spendingByCategory) {
  pieLegendEl.innerHTML = "";

  if (!spendingByCategory.length) {
    pieChartEl.style.background = "conic-gradient(#20374e 0% 100%)";
    const li = document.createElement("li");
    li.className = "legend-item";
    li.textContent = "No spending data yet";
    pieLegendEl.appendChild(li);
    return;
  }

  const total = spendingByCategory.reduce((sum, item) => sum + item.monthlyCost, 0);
  let current = 0;
  const gradientParts = [];

  spendingByCategory.forEach((item, index) => {
    const color = pieColors[index % pieColors.length];
    const share = total === 0 ? 0 : (item.monthlyCost / total) * 100;
    const start = current;
    const end = current + share;
    gradientParts.push(`${color} ${start.toFixed(2)}% ${end.toFixed(2)}%`);
    current = end;

    const legendItem = document.createElement("li");
    legendItem.className = "legend-item";

    const label = document.createElement("span");
    label.className = "legend-label";

    const colorDot = document.createElement("span");
    colorDot.className = "legend-color";
    colorDot.style.backgroundColor = color;

    const text = document.createElement("span");
    text.textContent = item.category;

    label.append(colorDot, text);

    const value = document.createElement("span");
    value.textContent = `${formatMoney(item.monthlyCost)} (${share.toFixed(1)}%)`;

    legendItem.append(label, value);
    pieLegendEl.appendChild(legendItem);
  });

  pieChartEl.style.background = `conic-gradient(${gradientParts.join(", ")})`;
}

function notificationsSupported() {
  return typeof window !== "undefined" && "Notification" in window;
}

function updateNotificationStatus() {
  if (!notificationsSupported()) {
    enableNotificationsBtn.disabled = true;
    enableNotificationsBtn.textContent = "Browser Alerts Unsupported";
    notificationStatusEl.textContent = "This browser does not support notifications.";
    return;
  }

  if (!currentUser) {
    enableNotificationsBtn.disabled = true;
    enableNotificationsBtn.textContent = "Sign In To Enable Alerts";
    notificationStatusEl.textContent = "Sign in to manage reminder notifications.";
    return;
  }

  if (Notification.permission === "granted") {
    enableNotificationsBtn.disabled = true;
    enableNotificationsBtn.textContent = "Browser Alerts Enabled";
    notificationStatusEl.textContent = "Alerts enabled. You will be notified for upcoming due payments.";
    return;
  }

  enableNotificationsBtn.disabled = false;
  enableNotificationsBtn.textContent = "Enable Browser Alerts";
  notificationStatusEl.textContent =
    Notification.permission === "denied"
      ? "Alerts blocked. Re-enable notifications in browser site settings."
      : "Notifications are off.";
}

function maybeNotifyDueSoon(reminders) {
  if (!notificationsSupported() || Notification.permission !== "granted") {
    return;
  }

  const today = new Date().toISOString().slice(0, 10);

  for (const reminder of reminders) {
    if (reminder.daysUntilPayment > 3) {
      continue;
    }

    const key = `subtracker:notified:${today}:${reminder.id}`;
    if (localStorage.getItem(key)) {
      continue;
    }

    const dueText =
      reminder.daysUntilPayment === 0
        ? "is due today"
        : `is due in ${reminder.daysUntilPayment} day${reminder.daysUntilPayment === 1 ? "" : "s"}`;

    new Notification(`${reminder.name} payment reminder`, {
      body: `${formatMoney(reminder.amount)} ${dueText} (${toFriendlyDate(reminder.nextPaymentDate)}).`,
    });
    localStorage.setItem(key, "1");
  }
}

function ensureSelectOption(selectEl, value) {
  if (!value) {
    return;
  }
  const exists = Array.from(selectEl.options).some((option) => option.value === value);
  if (exists) {
    return;
  }
  const option = document.createElement("option");
  option.value = value;
  option.textContent = value;
  selectEl.appendChild(option);
}

function renderCategoryControls() {
  const previousFormValue = subscriptionCategorySelect.value;
  const previousFilterValue = categoryFilterSelect.value;

  const categoryNames = new Set(allCategories.map((category) => category.name));
  for (const sub of allSubscriptions) {
    categoryNames.add(sub.category);
  }
  if (categoryNames.size === 0) {
    categoryNames.add("Other");
  }

  const sortedNames = Array.from(categoryNames).sort((a, b) => a.localeCompare(b));

  subscriptionCategorySelect.innerHTML = "";
  for (const name of sortedNames) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    subscriptionCategorySelect.appendChild(option);
  }

  categoryFilterSelect.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "All categories";
  categoryFilterSelect.appendChild(allOption);

  for (const name of sortedNames) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    categoryFilterSelect.appendChild(option);
  }

  const formValueExists = Array.from(subscriptionCategorySelect.options).some((option) => option.value === previousFormValue);
  if (formValueExists) {
    subscriptionCategorySelect.value = previousFormValue;
  } else if (subscriptionCategorySelect.options.length > 0) {
    subscriptionCategorySelect.value = subscriptionCategorySelect.options[0].value;
  }

  const filterValueExists = Array.from(categoryFilterSelect.options).some((option) => option.value === previousFilterValue);
  if (filterValueExists) {
    categoryFilterSelect.value = previousFilterValue;
  } else {
    categoryFilterSelect.value = "";
  }

  categoryList.innerHTML = "";
  if (!allCategories.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "No categories yet. Add one above.";
    categoryList.appendChild(emptyItem);
    return;
  }

  for (const category of allCategories) {
    const chip = document.createElement("li");
    chip.className = "category-chip";

    const label = document.createElement("span");
    label.textContent = category.name;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.setAttribute("aria-label", `Delete ${category.name} category`);
    removeBtn.textContent = "x";
    removeBtn.addEventListener("click", () => deleteCategory(category.id, category.name));

    chip.append(label, removeBtn);
    categoryList.appendChild(chip);
  }
}

function buildSpendingByCategory(subscriptions) {
  const totals = {};
  for (const sub of subscriptions) {
    totals[sub.category] = (totals[sub.category] || 0) + Number(sub.monthlyCost);
  }

  return Object.entries(totals)
    .map(([category, monthlyCost]) => ({ category, monthlyCost: Number(monthlyCost.toFixed(2)) }))
    .sort((a, b) => b.monthlyCost - a.monthlyCost);
}

function getFilteredSubscriptions() {
  const query = searchInput.value.trim().toLowerCase();
  const categoryFilter = categoryFilterSelect.value;
  const sortMode = sortSelect.value;

  let filtered = allSubscriptions.filter((sub) => {
    const matchesName = !query || sub.name.toLowerCase().includes(query);
    const matchesCategory = !categoryFilter || sub.category === categoryFilter;
    return matchesName && matchesCategory;
  });

  filtered = [...filtered];

  if (sortMode === "cost_desc") {
    filtered.sort((a, b) => b.monthlyCost - a.monthlyCost || a.name.localeCompare(b.name));
  } else if (sortMode === "cost_asc") {
    filtered.sort((a, b) => a.monthlyCost - b.monthlyCost || a.name.localeCompare(b.name));
  } else if (sortMode === "name_asc") {
    filtered.sort((a, b) => a.name.localeCompare(b.name));
  } else if (sortMode === "newest") {
    filtered.sort((a, b) => b.id - a.id);
  } else {
    filtered.sort((a, b) => a.daysUntilPayment - b.daysUntilPayment || a.name.localeCompare(b.name));
  }

  return filtered;
}

function remindersForSubscriptions(subscriptions) {
  const idSet = new Set(subscriptions.map((sub) => sub.id));
  return allReminders
    .filter((reminder) => idSet.has(reminder.id))
    .sort((a, b) => a.daysUntilPayment - b.daysUntilPayment || a.name.localeCompare(b.name));
}

function applyFiltersAndRender() {
  const filteredSubs = getFilteredSubscriptions();
  const filteredReminders = remindersForSubscriptions(filteredSubs);
  const totalMonthly = filteredSubs.reduce((sum, sub) => sum + Number(sub.monthlyCost), 0);

  renderSummary(Number(totalMonthly.toFixed(2)), filteredReminders[0] || null);
  renderSubscriptions(filteredSubs);
  renderReminders(filteredReminders);
  renderPieChart(buildSpendingByCategory(filteredSubs));
}

function setFormMode(mode, sub = null) {
  if (mode === "edit" && sub) {
    editingId = sub.id;
    formTitle.textContent = "Edit Subscription";
    submitBtn.textContent = "Update Subscription";
    cancelEditBtn.hidden = false;
    ensureSelectOption(subscriptionCategorySelect, sub.category);

    form.elements.name.value = sub.name;
    form.elements.category.value = sub.category;
    form.elements.amount.value = String(sub.amount);
    form.elements.billingCycle.value = sub.billingCycle;
    form.elements.nextPaymentDate.value = sub.initialPaymentDate;
    return;
  }

  editingId = null;
  formTitle.textContent = "Add Subscription";
  submitBtn.textContent = "Save Subscription";
  cancelEditBtn.hidden = true;
  form.reset();
  setDefaultDate();

  if (subscriptionCategorySelect.options.length > 0) {
    subscriptionCategorySelect.value = subscriptionCategorySelect.options[0].value;
  }
}

async function deleteSubscription(id) {
  try {
    await apiRequest(`/api/subscriptions/${id}`, { method: "DELETE" });
    if (editingId === id) {
      setFormMode("create");
    }
    await loadDashboard();
    setFormMessage("Subscription removed.", "success");
  } catch (error) {
    if (handleUnauthorized(error)) {
      return;
    }
    setFormMessage(error.message, "error");
  }
}

async function createCategory() {
  const name = newCategoryInput.value.trim();
  if (name.length < 2) {
    setCategoryMessage("Category name must be at least 2 characters.", "error");
    return;
  }

  try {
    const data = await apiRequest("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name }),
    });

    newCategoryInput.value = "";
    setCategoryMessage(`Category \"${data.category.name}\" added.`, "success");
    await loadDashboard();
    ensureSelectOption(subscriptionCategorySelect, data.category.name);
    subscriptionCategorySelect.value = data.category.name;
  } catch (error) {
    if (handleUnauthorized(error)) {
      return;
    }
    setCategoryMessage(error.message, "error");
  }
}

async function deleteCategory(categoryId, categoryName) {
  try {
    await apiRequest(`/api/categories/${categoryId}`, { method: "DELETE" });
    setCategoryMessage(`Category \"${categoryName}\" deleted.`, "success");
    await loadDashboard();
  } catch (error) {
    if (handleUnauthorized(error)) {
      return;
    }
    setCategoryMessage(error.message, "error");
  }
}

async function loadDashboard() {
  if (!currentUser) {
    return;
  }

  try {
    const [subscriptionsData, remindersData, categoriesData] = await Promise.all([
      apiRequest("/api/subscriptions"),
      apiRequest("/api/reminders"),
      apiRequest("/api/categories"),
    ]);

    allSubscriptions = subscriptionsData.subscriptions;
    allReminders = remindersData.reminders;
    allCategories = categoriesData.categories;

    renderCategoryControls();
    applyFiltersAndRender();
    maybeNotifyDueSoon(allReminders);
  } catch (error) {
    if (handleUnauthorized(error)) {
      return;
    }
    setFormMessage(error.message, "error");
  }
}

async function checkSession() {
  try {
    const data = await apiRequest("/api/auth/me");
    if (data.user) {
      setAuthenticatedUser(data.user);
      await loadDashboard();
      return;
    }
    setAuthenticatedUser(null);
  } catch (_error) {
    setAuthenticatedUser(null);
  }
}

authLoginModeBtn.addEventListener("click", () => {
  setAuthMode("login");
  setAuthMessage("");
});

authSignupModeBtn.addEventListener("click", () => {
  setAuthMode("signup");
  setAuthMessage("");
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const wasSignup = authMode === "signup";
  setAuthMessage(wasSignup ? "Creating account..." : "Signing in...");

  const formData = new FormData(authForm);
  const payload = {
    email: String(formData.get("authEmail") || "").trim(),
    password: String(formData.get("authPassword") || ""),
  };

  if (wasSignup) {
    payload.name = String(formData.get("authName") || "").trim();
  }

  const endpoint = wasSignup ? "/api/auth/signup" : "/api/auth/login";

  try {
    const data = await apiRequest(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setAuthenticatedUser(data.user);
    authForm.reset();
    setAuthMode("login");
    setAuthMessage(wasSignup ? "Account created." : "Signed in.", "success");
    setFormMessage("");
    setCategoryMessage("");
    await loadDashboard();
  } catch (error) {
    setAuthMessage(error.message, "error");
  }
});

logoutBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
  } catch (_error) {
    // ignore logout transport issues and clear local UI state anyway
  }

  setAuthenticatedUser(null);
  setAuthMode("login");
  setAuthMessage("Signed out.", "success");
  setFormMessage("");
  setCategoryMessage("");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormMessage("Saving...");

  const formData = new FormData(form);
  const payload = {
    name: String(formData.get("name") || "").trim(),
    category: String(formData.get("category") || "").trim(),
    amount: Number(formData.get("amount")),
    billingCycle: String(formData.get("billingCycle") || "").trim(),
    nextPaymentDate: String(formData.get("nextPaymentDate") || "").trim(),
  };

  try {
    const isEditing = editingId !== null;
    const endpoint = isEditing ? `/api/subscriptions/${editingId}` : "/api/subscriptions";

    await apiRequest(endpoint, {
      method: isEditing ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });

    setFormMode("create");
    setFormMessage(isEditing ? "Subscription updated." : "Subscription added.", "success");
    await loadDashboard();
  } catch (error) {
    if (handleUnauthorized(error)) {
      return;
    }
    setFormMessage(error.message, "error");
  }
});

cancelEditBtn.addEventListener("click", () => {
  setFormMode("create");
  setFormMessage("Edit cancelled.");
});

enableNotificationsBtn.addEventListener("click", async () => {
  if (!notificationsSupported()) {
    setFormMessage("This browser does not support notifications.", "error");
    updateNotificationStatus();
    return;
  }

  if (!currentUser) {
    setAuthMessage("Sign in before enabling notifications.", "error");
    updateNotificationStatus();
    return;
  }

  if (Notification.permission === "denied") {
    setFormMessage("Notifications are blocked. Update browser site settings to enable alerts.", "error");
    updateNotificationStatus();
    return;
  }

  const permission = await Notification.requestPermission();
  if (permission === "granted") {
    setFormMessage("Browser alerts enabled.", "success");
  } else {
    setFormMessage("Browser alerts were not enabled.");
  }
  updateNotificationStatus();
  await loadDashboard();
});

addCategoryBtn.addEventListener("click", createCategory);
newCategoryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    createCategory();
  }
});

searchInput.addEventListener("input", applyFiltersAndRender);
categoryFilterSelect.addEventListener("change", applyFiltersAndRender);
sortSelect.addEventListener("change", applyFiltersAndRender);
if (currencySelect) {
  currencySelect.addEventListener("change", () => {
    setCurrency(currencySelect.value);
    applyFiltersAndRender();
  });
}

setAuthMode("login");
setDefaultDate();
sortSelect.value = "due_soon";
setCurrency(getStoredCurrency(), false);
updateNotificationStatus();
renderCategoryControls();
applyFiltersAndRender();
checkSession();
