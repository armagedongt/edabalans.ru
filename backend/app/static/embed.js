(function () {
  'use strict';

  var APP_HOST = /^(localhost|127\.0\.0\.1)$/.test(location.hostname)
    ? location.origin
    : 'https://app.edabalans.ru';
  var STORAGE_IDENTITY = 'edabalans_identity_v1';
  var PROTECTED_APPS = {
    'masterclass-course': true,
    'onboarding-questionnaire': true,
    'masterclass-offers': true,
    'recipes-part-1': true,
    'recipes-part-2': true,
    'closing-review': true
  };
  var roots = {
    'masterclass-course': 'masterclass-course-app',
    dqs: 'dqs-app',
    strength: 'strength-app',
    metabolism: 'metabolism-app',
    'onboarding-questionnaire': 'onboarding-questionnaire-app',
    'masterclass-offers': 'masterclass-offers-app',
    'recipes-part-1': 'recipes-part-1-app',
    'recipes-part-2': 'recipes-part-2-app',
    'closing-review': 'closing-review-app'
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
      if (!saved || !validEmail(normalizeEmail(saved.email))) return null;
      return {
        email: normalizeEmail(saved.email),
        sessionToken: String(saved.sessionToken || ''),
        expiresAt: Number(saved.expiresAt || 0)
      };
    } catch (error) {
      return null;
    }
  }

  function remember(email, sessionToken, expiresIn) {
    var current = rememberedIdentity() || {};
    var token = sessionToken === undefined ? String(current.sessionToken || '') : String(sessionToken || '');
    var expiresAt = expiresIn === undefined
      ? Number(current.expiresAt || 0)
      : Date.now() + Number(expiresIn || 0) * 1000;
    try {
      localStorage.setItem(STORAGE_IDENTITY, JSON.stringify({
        email: email,
        sessionToken: token,
        expiresAt: expiresAt,
        confirmedAt: new Date().toISOString()
      }));
      localStorage.setItem('dqs_email', email);
    } catch (error) {}
    window.EdabalansIdentity = {email: email, sessionToken: token};
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

  function askIdentity(mounts, candidate, requireConfirmation) {
    var host = mounts[0];
    host.innerHTML = '<div style="max-width:520px;margin:30px auto;padding:24px;border-radius:20px;background:#fff;box-shadow:0 12px 35px rgba(0,0,0,.09);font-family:Arial,sans-serif;color:#1d1d1f">' +
      '<div style="font-size:22px;font-weight:700;margin-bottom:10px">Вход в приложение</div>' +
      (candidate ? '<div style="line-height:1.45;margin-bottom:18px">Вы входите как:<br><b>' + candidate.replace(/</g, '&lt;') + '</b><br>Это ваш email?</div>' : '<div style="line-height:1.45;margin-bottom:14px">Не удалось автоматически определить email. Введите email, на который оформлена покупка.</div>') +
      '<input data-edabalans-email type="email" value="' + candidate.replace(/"/g, '&quot;') + '" placeholder="email@example.com" style="box-sizing:border-box;width:100%;padding:12px 14px;border:1px solid #c7c7cc;border-radius:12px;font-size:16px;margin-bottom:12px">' +
      '<button data-edabalans-confirm style="width:100%;padding:12px;border:0;border-radius:12px;background:#1d1d1f;color:#fff;font-size:16px;font-weight:600;cursor:pointer">' + (requireConfirmation ? 'Получить код на почту' : 'Продолжить') + '</button>' +
      '<div data-edabalans-error style="color:#b42318;font-size:14px;margin-top:10px"></div></div>';
    host.querySelector('[data-edabalans-confirm]').addEventListener('click', function () {
      var email = normalizeEmail(host.querySelector('[data-edabalans-email]').value);
      if (!validEmail(email)) {
        host.querySelector('[data-edabalans-error]').textContent = 'Введите корректный email';
        return;
      }
      if (!requireConfirmation) {
        remember(email, '', 0);
        start(mounts);
        return;
      }
      var button = host.querySelector('[data-edabalans-confirm]');
      var error = host.querySelector('[data-edabalans-error]');
      button.disabled = true;
      error.textContent = 'Отправляю код…';
      fetch(APP_HOST + '/api/app-auth/challenge', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: email})
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.detail || 'Не удалось отправить код');
          return data;
        });
      }).then(function (challenge) {
        host.innerHTML = '<div style="max-width:520px;margin:30px auto;padding:24px;border-radius:20px;background:#fff;box-shadow:0 12px 35px rgba(0,0,0,.09);font-family:Arial,sans-serif;color:#1d1d1f">' +
          '<div style="font-size:22px;font-weight:700;margin-bottom:10px">Введите код</div>' +
          '<div style="line-height:1.45;margin-bottom:18px">Шестизначный код отправлен на <b>' + email.replace(/</g, '&lt;') + '</b>. Он действует 10 минут.</div>' +
          '<input data-edabalans-code inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="000000" style="box-sizing:border-box;width:100%;padding:12px 14px;border:1px solid #c7c7cc;border-radius:12px;font-size:22px;letter-spacing:6px;text-align:center;margin-bottom:12px">' +
          '<button data-edabalans-verify style="width:100%;padding:12px;border:0;border-radius:12px;background:#1d1d1f;color:#fff;font-size:16px;font-weight:600;cursor:pointer">Войти</button>' +
          '<button data-edabalans-back style="width:100%;padding:10px;border:0;background:transparent;color:#555;cursor:pointer">Изменить email</button>' +
          '<div data-edabalans-error style="color:#b42318;font-size:14px;margin-top:10px"></div></div>';
        host.querySelector('[data-edabalans-back]').onclick = function () {
          askIdentity(mounts, email, true);
        };
        host.querySelector('[data-edabalans-verify]').onclick = function () {
          var code = String(host.querySelector('[data-edabalans-code]').value || '').replace(/\D/g, '');
          var verifyError = host.querySelector('[data-edabalans-error]');
          if (code.length !== 6) {
            verifyError.textContent = 'Введите все 6 цифр';
            return;
          }
          verifyError.textContent = 'Проверяю…';
          fetch(APP_HOST + '/api/app-auth/verify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({challenge_token: challenge.challenge_token, code: code})
          }).then(function (response) {
            return response.json().then(function (data) {
              if (!response.ok) throw new Error(data.detail || 'Неверный код');
              return data;
            });
          }).then(function (session) {
            remember(session.email, session.session_token, session.expires_in);
            start(mounts);
          }).catch(function (verifyFailure) {
            verifyError.textContent = String(verifyFailure.message || verifyFailure);
          });
        };
      }).catch(function (failure) {
        button.disabled = false;
        error.textContent = String(failure.message || failure);
      });
    });
  }

  function executeScripts(doc) {
    var scripts = doc.querySelectorAll('script');
    return Array.prototype.reduce.call(scripts, function (promise, source) {
      return promise.then(function () {
        return new Promise(function (resolve, reject) {
          var script = document.createElement('script');
          if (source.getAttribute('src')) {
            var sourcePath = source.getAttribute('src');
            script.src = sourcePath.charAt(0) === '/' ? APP_HOST + sourcePath : sourcePath;
            script.onload = resolve;
            script.onerror = reject;
          } else {
            script.text = source.textContent;
          }
          document.body.appendChild(script);
          if (!source.getAttribute('src')) resolve();
        });
      });
    }, Promise.resolve());
  }

  function load(mount) {
    var app = String(mount.getAttribute('data-edabalans-app') || '').toLowerCase();
    var adminUser = String(mount.getAttribute('data-edabalans-admin-user') || '');
    var placement = String(mount.getAttribute('data-edabalans-placement') || '');
    var placementToken = String(mount.getAttribute('data-edabalans-placement-token') || '');
    var accountUrl = String(mount.getAttribute('data-edabalans-account-url') || '');
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
        window.EdabalansAppHost = APP_HOST;
        window.EdabalansAppContext = adminUser
          ? {mode: 'admin', targetUserId: adminUser, app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl}
          : {mode: 'user', app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl};
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
    var protectedApps = mounts.some(function (mount) {
      return Boolean(PROTECTED_APPS[String(mount.getAttribute('data-edabalans-app') || '').toLowerCase()]);
    });
    var detected = detectTildaEmail();
    var remembered = rememberedIdentity();
    if (remembered && remembered.sessionToken && remembered.expiresAt > Date.now() && (!detected || remembered.email === detected)) {
      remember(remembered.email);
      start(mounts);
      return;
    }
    if (!protectedApps && remembered && (!detected || remembered.email === detected)) {
      remember(remembered.email);
      start(mounts);
      return;
    }
    askIdentity(mounts, detected || (remembered && remembered.email) || '', protectedApps);
  }

  window.EdabalansEmbed = {load: load, boot: boot};

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
