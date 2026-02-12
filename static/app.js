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

let editingId = null;

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

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

function setFormMessage(message, type = "") {
  formMessage.textContent = message;
  formMessage.classList.remove("error", "success");
  if (type) {
    formMessage.classList.add(type);
  }
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

function setFormMode(mode, sub = null) {
  if (mode === "edit" && sub) {
    editingId = sub.id;
    formTitle.textContent = "Edit Subscription";
    submitBtn.textContent = "Update Subscription";
    cancelEditBtn.hidden = false;
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
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error || "Something went wrong");
  }

  return body;
}

async function loadDashboard() {
  try {
    const [subscriptionsData, remindersData] = await Promise.all([
      apiRequest("/api/subscriptions"),
      apiRequest("/api/reminders"),
    ]);

    renderSummary(subscriptionsData.totalMonthlySpend, remindersData.nextReminder);
    renderSubscriptions(subscriptionsData.subscriptions);
    renderReminders(remindersData.reminders);
    renderPieChart(subscriptionsData.spendingByCategory);
    maybeNotifyDueSoon(remindersData.reminders);
  } catch (error) {
    setFormMessage(error.message, "error");
  }
}

function renderSummary(totalMonthlySpend, nextReminder) {
  totalMonthlySpendEl.textContent = currency.format(totalMonthlySpend || 0);

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
    amountCell.textContent = currency.format(sub.amount);

    const monthlyCell = document.createElement("td");
    monthlyCell.textContent = currency.format(sub.monthlyCost);

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
    dateLine.textContent = `${toFriendlyDate(reminder.nextPaymentDate)} • ${currency.format(reminder.amount)} (${toFriendlyCycle(
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
    value.textContent = `${currency.format(item.monthlyCost)} (${share.toFixed(1)}%)`;

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
      body: `${currency.format(reminder.amount)} ${dueText} (${toFriendlyDate(reminder.nextPaymentDate)}).`,
    });
    localStorage.setItem(key, "1");
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
    setFormMessage(error.message, "error");
  }
}

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

setDefaultDate();
updateNotificationStatus();
loadDashboard();
