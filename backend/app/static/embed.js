(function () {
  'use strict';

  var APP_HOST = /^(localhost|127\.0\.0\.1)$/.test(location.hostname)
    ? location.origin
    : 'https://app.edabalans.ru';
  var STORAGE_IDENTITY = 'edabalans_identity_v1';
  var roots = {
    dqs: 'dqs-app',
    strength: 'strength-app',
    metabolism: 'metabolism-app'
  };

  function normalizeEmail(value) {
    return String(value || '').trim().toLowerCase();
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function detectTildaEmail() {
    var candidates = [];
    var inputs = document.querySelectorAll('input');
    var i;
    for (i = 0; i < inputs.length; i += 1) {
      if (/email/i.test(String(inputs[i].name || '') + ' ' + String(inputs[i].type || ''))) {
        candidates.push(inputs[i].value);
      }
    }
    var text = String(document.body && document.body.innerText || '');
    var matches = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || [];
    candidates = candidates.concat(matches);
    for (i = 0; i < candidates.length; i += 1) {
      var email = normalizeEmail(candidates[i]);
      if (validEmail(email)) return email;
    }
    return '';
  }

  function rememberedIdentity() {
    try {
      var saved = JSON.parse(localStorage.getItem(STORAGE_IDENTITY) || 'null');
      return saved && validEmail(normalizeEmail(saved.email)) ? normalizeEmail(saved.email) : '';
    } catch (error) {
      return '';
    }
  }

  function remember(email) {
    try {
      localStorage.setItem(STORAGE_IDENTITY, JSON.stringify({email: email, confirmedAt: new Date().toISOString()}));
      localStorage.setItem('dqs_email', email);
    } catch (error) {}
    window.EdabalansIdentity = {email: email};
    var marker = document.getElementById('edabalans-member-email');
    if (!marker) {
      marker = document.createElement('input');
      marker.id = 'edabalans-member-email';
      marker.name = 'member_email';
      marker.type = 'hidden';
      document.body.appendChild(marker);
    }
    marker.value = email;
  }

  function askIdentity(mounts, candidate) {
    var host = mounts[0];
    host.innerHTML = '<div style="max-width:520px;margin:30px auto;padding:24px;border-radius:20px;background:#fff;box-shadow:0 12px 35px rgba(0,0,0,.09);font-family:Arial,sans-serif;color:#1d1d1f">' +
      '<div style="font-size:22px;font-weight:700;margin-bottom:10px">Вход в приложение</div>' +
      (candidate ? '<div style="line-height:1.45;margin-bottom:18px">Вы входите как:<br><b>' + candidate.replace(/</g, '&lt;') + '</b><br>Это ваш email?</div>' : '<div style="line-height:1.45;margin-bottom:14px">Не удалось автоматически определить email. Введите email, на который оформлена покупка.</div>') +
      '<input data-edabalans-email type="email" value="' + candidate.replace(/"/g, '&quot;') + '" placeholder="email@example.com" style="box-sizing:border-box;width:100%;padding:12px 14px;border:1px solid #c7c7cc;border-radius:12px;font-size:16px;margin-bottom:12px">' +
      '<button data-edabalans-confirm style="width:100%;padding:12px;border:0;border-radius:12px;background:#1d1d1f;color:#fff;font-size:16px;font-weight:600;cursor:pointer">Продолжить</button>' +
      '<div data-edabalans-error style="color:#b42318;font-size:14px;margin-top:10px"></div></div>';
    host.querySelector('[data-edabalans-confirm]').addEventListener('click', function () {
      var email = normalizeEmail(host.querySelector('[data-edabalans-email]').value);
      if (!validEmail(email)) {
        host.querySelector('[data-edabalans-error]').textContent = 'Введите корректный email';
        return;
      }
      remember(email);
      start(mounts);
    });
  }

  function executeScripts(doc) {
    var scripts = doc.querySelectorAll('script');
    return Array.prototype.reduce.call(scripts, function (promise, source) {
      return promise.then(function () {
        return new Promise(function (resolve, reject) {
          var script = document.createElement('script');
          if (source.src) {
            script.src = source.src;
            script.onload = resolve;
            script.onerror = reject;
          } else {
            script.text = source.textContent;
          }
          document.body.appendChild(script);
          if (!source.src) resolve();
        });
      });
    }, Promise.resolve());
  }

  function load(mount) {
    var app = String(mount.getAttribute('data-edabalans-app') || '').toLowerCase();
    var adminUser = String(mount.getAttribute('data-edabalans-admin-user') || '');
    if (!roots[app]) {
      mount.textContent = 'Неизвестное приложение: ' + app;
      return Promise.resolve();
    }
    mount.innerHTML = '<div style="padding:30px;text-align:center;font-family:Arial,sans-serif">Загрузка…</div>';
    return fetch(APP_HOST + '/apps/' + app + '.html', {cache: 'no-cache'})
      .then(function (response) {
        if (!response.ok) throw new Error('Не удалось загрузить приложение');
        return response.text();
      })
      .then(function (html) {
        window.EdabalansAppContext = adminUser
          ? {mode: 'admin', targetUserId: adminUser, app: app}
          : {mode: 'user', app: app};
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var sourceRoot = doc.getElementById(roots[app]);
        mount.id = roots[app];
        mount.innerHTML = sourceRoot ? sourceRoot.innerHTML : '';
        Array.prototype.forEach.call(doc.querySelectorAll('style'), function (style) {
          var key = 'edabalans-style-' + app;
          if (!document.getElementById(key)) {
            var copy = document.createElement('style');
            copy.id = key;
            copy.textContent = style.textContent;
            document.head.appendChild(copy);
          }
        });
        return executeScripts(doc);
      })
      .catch(function (error) {
        mount.innerHTML = '<div style="padding:24px;color:#b42318;font-family:Arial,sans-serif">' + String(error.message || error) + '</div>';
      });
  }

  function start(mounts) {
    mounts.forEach(load);
  }

  function boot() {
    var mounts = Array.prototype.slice.call(document.querySelectorAll('[data-edabalans-app]'));
    if (!mounts.length) return;
    var detected = detectTildaEmail();
    var remembered = rememberedIdentity();
    if (remembered && (!detected || remembered === detected)) {
      remember(remembered);
      start(mounts);
      return;
    }
    askIdentity(mounts, detected || remembered);
  }

  window.EdabalansEmbed = {load: load, boot: boot};

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
