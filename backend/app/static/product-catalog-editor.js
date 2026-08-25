(function () {
  "use strict";
  var data, payload, dirty = false;
  function e(value) { return String(value || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]; }); }
  function api(url, options) { return fetch(url, options).then(function (response) { return response.json().then(function (body) { if (!response.ok) throw Error(typeof body.detail === "string" ? body.detail : "Ошибка сервера"); return body; }); }); }
  function field(kind, index, key, label, value, full) { return '<label class="field ' + (full ? "full" : "") + '"><span>' + label + '</span><textarea data-' + kind + '="' + index + '" data-field="' + key + '">' + e(value) + "</textarea></label>"; }
  function product(item, index) {
    return '<details class="day" ' + (index === 0 ? "open" : "") + "><summary>" + e(item.fullName) + '</summary><div class="day-body">' +
      '<section class="group"><h3>Показывается пользователю</h3><div class="grid">' +
      field("product", index, "shortName", "Короткое название", item.shortName) +
      field("product", index, "fullName", "Полное название", item.fullName) +
      field("product", index, "descriptor", "Короткий дескрипшн — начинается с «Как…»", item.descriptor, true) +
      field("product", index, "status", "Статус: active / planned / archived", item.status) +
      '</div></section><section class="group"><h3>Для работы и ИИ · не показывается пользователю</h3>' +
      field("product", index, "marketing", "Полный маркетинговый контекст", item.marketing, true) +
      "</section></div></details>";
  }
  function tariff(item, index) { return '<details class="day"><summary>Тариф · ' + e(item.name) + '</summary><div class="day-body"><section class="group"><div class="grid">' + field("tariff", index, "name", "Название тарифа", item.name) + field("tariff", index, "status", "Статус: active / planned / archived", item.status) + field("tariff", index, "descriptor", "Короткое описание", item.descriptor, true) + "</div></section></div></details>"; }
  function render() { document.querySelector("#catalog").innerHTML = "<h2>Продукты</h2>" + payload.products.map(product).join("") + "<h2>Входные тарифы Мастер-класса</h2>" + payload.tariffs.map(tariff).join(""); document.querySelector("#history").innerHTML = data.history.map(function (version) { return '<div class="history-row"><span>Редакция ' + version.version + " · " + new Date(version.created_at).toLocaleString("ru-RU") + "</span>" + (version.active ? "<b>активна</b>" : '<button class="secondary" data-restore="' + version.version + '">Вернуть</button>') + "</div>"; }).join(""); }
  function state() { document.querySelector("#save").disabled = !dirty; document.querySelector("#status").textContent = dirty ? "Есть несохранённые изменения" : "Редакция " + data.active.version; }
  function fail(error) { var box = document.querySelector("#error"); box.hidden = false; box.textContent = error.message; }
  function update(target) { var index; if (target.dataset.product != null) { index = +target.dataset.product; payload.products[index][target.dataset.field] = target.value; } else if (target.dataset.tariff != null) { index = +target.dataset.tariff; payload.tariffs[index][target.dataset.field] = target.value; } else return; dirty = true; state(); }
  function load() { api("/admin/api/product-catalog").then(function (result) { data = result; payload = result.active.manifest; render(); state(); }).catch(fail); }
  document.querySelector("#catalog").addEventListener("input", function (event) { update(event.target); });
  document.querySelector("#save").onclick = function () { this.disabled = true; api("/admin/api/product-catalog", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: data.active.version, payload: payload }) }).then(function (result) { data = result; payload = result.active.manifest; dirty = false; render(); state(); }).catch(function (error) { fail(error); dirty = true; state(); }); };
  document.querySelector("#history").addEventListener("click", function (event) { var button = event.target.closest("[data-restore]"); if (!button || !confirm("Вернуть редакцию " + button.dataset.restore + "?")) return; api("/admin/api/product-catalog/versions/" + button.dataset.restore + "/restore", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: data.active.version }) }).then(function (result) { data = result; payload = result.active.manifest; dirty = false; render(); state(); }).catch(fail); });
  load();
}());
