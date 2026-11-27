(() => {
  if (window.EdabalansMasterclassDiscussion) return;
  const base = '/api/masterclass/discussion/day-04';
  const notice = 'Обсуждение работает в тестовом режиме. У вас пока нет доступа. Ожидайте уведомления.';
  let activePanel = null;
  let releaseComposer = () => {};
  let voiceTemplate = '';
  let dayEntry = null;

  async function api(path, options = {}) {
    const response = await fetch(base + path, {cache:'no-store', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте поля и повторите.');
    return data;
  }

  function dateLabel(value) {
    return value ? new Intl.DateTimeFormat('ru', {day:'numeric',month:'long',year:'numeric',timeZone:'Europe/Moscow'}).format(new Date(value)) : '';
  }

  function timeLabel(value) {
    return value ? new Intl.DateTimeFormat('ru', {hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(value)) : '';
  }

  // Lucide, ISC license. https://lucide.dev/license
  const icons = {
    paperclip: '<path d="M13.234 20.252 21 12.3"/><path d="m16 7-8.414 8.586a2 2 0 0 0 2.828 2.828L19 9.828a4 4 0 1 0-5.657-5.656L4.757 12.757a6 6 0 0 0 8.477 8.495"/>',
    mic: '<path d="M12 19v3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><rect x="9" y="2" width="6" height="13" rx="3"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  };
  function element(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function button(text, action, cls = 'back') {
    const node = element('button', cls, text);
    node.type = 'button';
    node.onclick = action;
    return node;
  }

  function setIcon(control, name) {
    control.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + icons[name] + '</svg>';
  }

  function pausePlayers(scope, except) {
    scope?.querySelectorAll('.day-voice-frame').forEach(frame => {
      const audio = frame.contentDocument?.querySelector('[data-voice-audio]');
      if (audio && audio !== except) audio.pause();
    });
  }

  function player(src, author = 'Сергей') {
    const frame = element('iframe', 'day-voice-frame');
    frame.title = 'Голосовое сообщение';
    const values = {src, author, avatar:'', duration:'—:—'};
    function escape(value) {
      const text = element('span', '', value);
      return text.innerHTML.replaceAll('"', '&quot;');
    }
    frame.srcdoc = voiceTemplate.replace(/{{(src|author|duration)}}/g,
      (placeholder, key) => escape(values[key])).replace('</style>',
        'body{padding-inline:5px 9px}.voice-widget{grid-template-columns:minmax(0,1fr)}.voice-widget__avatar,.voice-widget__author>span:first-child{display:none}.voice-widget__bubble-shadow{margin-left:0}</style>');
    frame.onload = () => {
      const audio = frame.contentDocument?.querySelector('[data-voice-audio]');
      audio?.addEventListener('play', () => pausePlayers(activePanel, audio));
    };
    return frame;
  }

  function picture(src) {
    const img = element('img', 'day-discussion-image');
    img.alt = 'Вложение к сообщению';
    img.loading = 'lazy';
    img.src = src;
    return img;
  }

  function quoteText(item) {
    return item.text || (item.photo ? 'Фото' : 'Голосовое');
  }

  function isOwnMessage(item) {
    return item.isAuthor;
  }

  function quote(target, jump) {
    const text = quoteText(target);
    const node = button('', () => jump(target.id), 'day-discussion-quote');
    node.setAttribute('aria-label', 'Перейти к сообщению: ' + text);
    node.append(element('span', 'day-discussion-quote-name', isOwnMessage(target) ? 'Вы' : target.name || 'Вопрос из обсуждения'),
      element('span', 'day-discussion-quote-text', text));
    return node;
  }

  function message(item, byId, answers, jump, reply, editProfile) {
    const own = isOwnMessage(item);
    const card = element('article', 'day-discussion-message' + (own ? ' own' : '') + (item.isAuthor ? ' by-author' : ''));
    card.id = 'day-discussion-message-' + item.id;
    card.tabIndex = -1;
    if (item.name) {
      const author = element('div', 'day-discussion-name');
      const avatar = element('span', 'day-discussion-avatar', item.name[0]);
      avatar.setAttribute('aria-hidden', 'true');
      if (item.profile?.avatar) {
        const photo = element('img');
        photo.src = item.profile.avatar;
        photo.alt = '';
        avatar.replaceChildren(photo);
      }
      if (item.profile || own) {
        const profile = element('div', 'day-discussion-profile');
        if (item.profile?.avatar) {
          const photo = element('img', 'day-discussion-profile-photo');
          photo.src = item.profile.avatar;
          photo.alt = '';
          profile.append(photo);
        }
        profile.append(element('strong', '', item.name));
        if (item.profile?.about) profile.append(element('p','',item.profile.about));
        if (own) profile.append(button('Мой профиль', editProfile, 'day-discussion-text-action'));
        profile.hidden = true;
        const name = button('', () => {
          profile.hidden = !profile.hidden;
          name.setAttribute('aria-expanded', String(!profile.hidden));
        }, 'day-discussion-profile-name');
        name.append(avatar, element('span', '', item.name));
        name.setAttribute('aria-expanded', 'false');
        author.append(name);
        card.append(author, profile);
      } else {
        author.append(avatar, element('span', '', own ? 'Вы' : item.name));
        card.append(author);
      }
    }
    const target = byId.get(item.replyTo);
    if (target) card.append(quote(target, jump));
    if (item.text) card.append(element('p', '', item.text));
    if (item.photo) card.append(picture(item.photo));
    if (item.voice) card.append(player(item.voice, item.name));
    const markedReply = byId.get(answers[item.id]);
    if (markedReply) {
      const answer = element('details', 'day-discussion-answer');
      answer.append(element('summary', '', markedReply.voice ? 'Ответ Сергея · голосовое' : 'Ответ Сергея'));
      if (markedReply.text) answer.append(element('p', '', markedReply.text));
      if (markedReply.voice) answer.append(player(markedReply.voice));
      if (markedReply.photo) answer.append(picture(markedReply.photo));
      answer.append(button('Перейти к ответу', () => jump(markedReply.id), 'day-discussion-text-action'));
      answer.ontoggle = () => { if (!answer.open) pausePlayers(answer); };
      card.append(answer);
    }
    {
      const footer = element('div', 'day-discussion-meta');
      footer.append(button('Ответить', () => reply(item), 'day-discussion-text-action'));
      if (item.at) footer.append(element('time', '', timeLabel(item.at)));
      card.append(footer);
    }
    return card;
  }

  function composerButton(symbol, label, action) {
    const control = button('', action, 'day-discussion-icon');
    setIcon(control, symbol);
    control.setAttribute('aria-label', label);
    control.title = label;
    return control;
  }

  async function open(day, entry, mode, wanted = 0) {
    if (day.querySelector('.day-discussion-panel')) return;
    const panel = element('section', 'day-discussion-panel');
    activePanel = panel;
    const head = element('div', 'article-head');
    const back = button('← К дню 4', () => {
      pausePlayers(panel);
      panel.remove();
      releaseComposer();
      activePanel = null;
      day.classList.remove('day-discussion-open');
      entry.scrollIntoView({block:'center',behavior:'instant'});
      entry.focus({preventScroll:true});
    });
    head.classList.add('day-discussion-head');
    const theme = button('', () => {
      document.querySelector('.account-theme-toggle')?.click();
      syncTheme();
    }, 'day-discussion-theme');
    function syncTheme() {
      const original = document.querySelector('.account-theme-toggle');
      if (!original) return;
      theme.innerHTML = original.innerHTML;
      theme.setAttribute('aria-label', original.getAttribute('aria-label'));
      theme.setAttribute('aria-pressed', original.getAttribute('aria-pressed'));
    }
    syncTheme();
    head.append(back, element('h1', '', 'Обсуждение дня 4'), theme);
    panel.append(head);
    if (mode !== 'owner') {
      panel.append(element('p', 'day-discussion-access-note', notice));
    } else {
      const loading = element('p', 'day-discussion-access-note', 'Загружаем обсуждение…');
      panel.append(loading);
      mountPanel();
      let initial;
      try { initial = await api('/thread'); }
      catch (error) { loading.textContent = error.message; return; }
      if (!panel.isConnected) return;
      loading.remove();
      voiceTemplate = initial.player;
      let profileData = initial.profile;
      const posts = new Map();
      const related = new Map();
      const answers = {};
      let more = initial.more;
      let cursor = 0;
      let pendingNonce = null;
      let replyTarget = null;
      let authorAnswer = false;
      const readIds = new Set();
      const timeline = element('div', 'day-discussion-timeline');
      panel.append(timeline);
      const form = element('div', 'day-discussion-compose');
      const textarea = element('textarea');
      textarea.rows = 2;
      textarea.maxLength = 2000;
      textarea.id = 'day-discussion-message';
      textarea.setAttribute('aria-label', 'Сообщение');
      textarea.placeholder = 'Сообщение';
      const photo = element('input');
      photo.type = 'file';
      photo.accept = 'image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif';
      photo.hidden = true;
      photo.setAttribute('aria-label', 'Файл фотографии');
      const attach = composerButton('paperclip', 'Прикрепить фото', () => photo.click());
      const mic = composerButton('mic', 'Записать голосовое', recordVoice);

      const submit = composerButton('send', 'Отправить', send);
      const actions = element('div', 'day-discussion-actions');
      const context = element('div', 'day-discussion-note');
      const status = element('div', 'day-discussion-note');
      status.setAttribute('role','status');
      const photoDraft = element('div', 'day-discussion-draft');
      const voiceDraft = element('div', 'day-discussion-draft');
      const voiceFile = element('input');
      voiceFile.type = 'file';
      voiceFile.accept = 'audio/*';
      voiceFile.hidden = true;
      voiceFile.setAttribute('aria-label', 'Файл голосового');
      const audioFallback = button('Прикрепить аудиофайл', () => voiceFile.click(), 'day-discussion-text-action');
      audioFallback.hidden = true;
      let photoDraftUrl = '';
      let voiceDraftUrl = '';
      let recorder;
      let voiceRecording;
      function validPhoto(file) {
        return /\.(png|jpe?g|webp|heic|heif)$/i.test(file.name);
      }

      function clearPhoto() {
        if (photoDraftUrl) URL.revokeObjectURL(photoDraftUrl);
        photoDraftUrl = '';
        photo.value = '';
        photoDraft.replaceChildren();
      }

      function clearVoice() {
        if (voiceDraftUrl) URL.revokeObjectURL(voiceDraftUrl);
        voiceDraftUrl = '';
        voiceRecording = null;
        voiceDraft.replaceChildren();
      }

      function draftVoice(audio) {
        if (!audio?.size || audio.size > 12_000_000) {
          status.textContent = 'Не удалось сохранить голосовое. Максимальный размер — 12 МБ.';
          return;
        }
        clearVoice();
        voiceRecording = audio;
        voiceDraftUrl = URL.createObjectURL(audio);
        voiceDraft.append(player(voiceDraftUrl), button('Удалить запись', clearVoice, 'day-discussion-text-action'));
      }
      voiceFile.onchange = () => {
        const file = voiceFile.files[0];
        if (file?.type.startsWith('audio/')) {
          status.textContent = '';
          draftVoice(file);
        }
        voiceFile.value = '';
      };

      photo.addEventListener('change', () => {
        if (photoDraftUrl) URL.revokeObjectURL(photoDraftUrl);
        photoDraftUrl = '';
        photoDraft.replaceChildren();
        status.textContent = '';
        const image = photo.files[0];
        if (!image) return;
        if (!validPhoto(image) || image.size > 8_000_000) {
          clearPhoto();
          status.textContent = 'Выберите фото JPEG, PNG, WebP или HEIC до 8 МБ.';
          return;
        }
        photoDraftUrl = URL.createObjectURL(image);
        const thumbnail = picture(photoDraftUrl);
        thumbnail.onerror = () => thumbnail.replaceWith(element('span', '', image.name));
        photoDraft.append(thumbnail, button('Убрать фото', clearPhoto, 'day-discussion-text-action'));
      });

      function finishCapture() {
        mic.disabled = false;
        setIcon(mic, 'mic');
        mic.title = 'Записать голосовое';
        mic.setAttribute('aria-label', mic.title);
        submit.disabled = false;
      }

      async function recordVoice() {
        if (recorder?.state === 'recording') {
          mic.disabled = true;
          recorder.stop();
          return;
        }
        if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder !== 'function') {
          status.textContent = window.isSecureContext
            ? 'Этот браузер не поддерживает запись голосовых.'
            : 'Для записи нужен адрес HTTPS или этот компьютер через localhost.';
          audioFallback.hidden = false;
          return;
        }
        mic.disabled = true;
        status.textContent = 'Запрашиваем доступ к микрофону…';
        audioFallback.hidden = false;
        let stream;
        try {
          stream = await navigator.mediaDevices.getUserMedia({audio:true});
          if (!panel.isConnected) {
            stream.getTracks().forEach(track => track.stop());
            return;
          }
          recorder = new MediaRecorder(stream);
          const chunks = [];
          recorder.ondataavailable = (event) => {
            if (event.data.size) chunks.push(event.data);
          };
          recorder.onstop = async () => {
            stream.getTracks().forEach(track => track.stop());
            if (!panel.isConnected) return;
            const recording = new Blob(chunks, {type:recorder.mimeType});
            if (recording.size && recording.size <= 12_000_000) {
              status.textContent = 'Готовим голосовое…';
              try {
                const data = new FormData();
                data.append('voice', recording, 'recording');
                const response = await fetch(base + '/voice-preview', {method:'POST',body:data,cache:'no-store'});
                if (!response.ok) throw new Error('Audio conversion failed');
                const ready = await response.blob();
                if (panel.isConnected) {
                  status.textContent = '';
                  draftVoice(ready);
                }
              } catch {
                if (panel.isConnected) {
                  draftVoice(recording);
                  status.textContent = 'Запись сохранена. Для этого формата перемотка может быть недоступна.';
                }
              }
            } else {
              draftVoice(recording);
            }
            if (panel.isConnected) finishCapture();
          };
          recorder.start();
          submit.disabled = true;
          mic.disabled = false;
          setIcon(mic, 'stop');
          mic.title = 'Остановить запись';
          mic.setAttribute('aria-label', mic.title);
          status.textContent = 'Идёт запись…';
          audioFallback.hidden = true;
        } catch (error) {
          stream?.getTracks().forEach(track => track.stop());
          finishCapture();
          status.textContent = {
            NotAllowedError: 'Разрешите микрофон в настройках сайта и попробуйте снова.',
            NotFoundError: 'Микрофон не найден. Проверьте подключение.',
          }[error.name] || 'Не удалось включить микрофон. Проверьте устройство и разрешение браузера.';
          audioFallback.hidden = false;
        }
      }

      let pendingRead = [];
      let readTimer = 0;
      async function flushRead() {
        if (!pendingRead.length) return;
        const ids = pendingRead.splice(0, 100);
        try {
          const result = await api('/read', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ids}),
          });
          setBadge(dayEntry, result.unread);
        } catch {
          if (panel.isConnected) {
            pendingRead.unshift(...ids);
            clearTimeout(readTimer);
            readTimer = setTimeout(flushRead, 3000);
          }
        }
      }
      const readObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
          const id = Number(entry.target.id.replace('day-discussion-message-', ''));
          if (!entry.isIntersecting || readIds.has(id)) continue;
          readIds.add(id);
          pendingRead.push(id);
          readObserver.unobserve(entry.target);
        }
        if (pendingRead.length) {
          clearTimeout(readTimer);
          readTimer = setTimeout(flushRead, 150);
        }
      }, {threshold:0.2, rootMargin:'-65px 0px 0px'});
      releaseComposer = () => {
        if (recorder?.state === 'recording') recorder.stop();
        clearTimeout(readTimer);
        flushRead();
        readObserver.disconnect();
        clearInterval(refreshTimer);
        clearPhoto();
        clearVoice();
      };

      async function jump(id) {
        let target = panel.querySelector('#day-discussion-message-' + id);
        if (!target) {
          try {
            merge(await api('/thread?around=' + encodeURIComponent(id)));
            renderTimeline();
          } catch (error) { status.textContent = error.message; }
          target = panel.querySelector('#day-discussion-message-' + id);
        }
        if (!target) return;
        timeline.querySelector('.quoted-message')?.classList.remove('quoted-message');
        target.classList.add('quoted-message');
        target.scrollIntoView({block:'center',behavior:'instant'});
        target.focus({preventScroll:true});
      }

      function selectReply(item) {
        replyTarget = item;
        authorAnswer = false;
        context.replaceChildren(
          quote(item, jump),
          button('Отменить ответ', () => {
            replyTarget = null;
            authorAnswer = false;
            context.replaceChildren();
            textarea.focus();
          }, 'day-discussion-text-action')
        );
        if (!isOwnMessage(item)) {
          const label = element('label', 'day-discussion-mark', 'Пометить как ответ Сергея');
          const check = element('input');
          check.type = 'checkbox';
          check.onchange = () => { authorAnswer = check.checked; };
          label.prepend(check);
          context.append(label);
        }
        textarea.focus();
      }

      function merge(data) {
        for (const item of data.posts) posts.set(item.id, item);
        for (const item of data.related) if (!posts.has(item.id)) related.set(item.id, item);
        Object.assign(answers, data.answers);
        setBadge(dayEntry, data.unread);
      }

      const nextPage = button('Ещё сообщения', async () => {
        nextPage.disabled = true;
        try {
          const result = await api('/thread?after=' + cursor);
          cursor = result.posts.at(-1)?.id || cursor;
          more = result.more;
          merge(result);
          renderTimeline();
        } catch (error) { status.textContent = error.message; }
        finally { nextPage.disabled = false; }
      }, 'day-discussion-text-action');

      function renderTimeline() {
        const items = [...posts.values()].sort((a,b) => a.id-b.id);
        const byId = new Map([...related, ...posts]);
        readObserver.disconnect();
        pausePlayers(timeline);
        timeline.replaceChildren();
        const old = items.filter(item => item.archived);
        if (old.length) {
          timeline.append(element('h2', 'day-discussion-divider', 'Старые обсуждения'));
          for (const item of old) timeline.append(message(item, byId, answers, jump, selectReply, editProfile));
        }
        timeline.append(element('h2', 'day-discussion-divider new-questions', 'Новые вопросы'));
        let lastDate = '';
        for (const item of items.filter(post => !post.archived)) {
          const date = dateLabel(item.at);
          if (date && date !== lastDate) timeline.append(element('p', 'day-discussion-date', date));
          lastDate = date;
          timeline.append(message(item, byId, answers, jump, selectReply, editProfile));
        }
        if (more) timeline.append(nextPage);
        for (const item of timeline.querySelectorAll('.day-discussion-message')) readObserver.observe(item);
      }

      async function send() {
        const text = textarea.value.trim();
        const image = photo.files[0];
        const audio = voiceRecording;
        if (!text && !image && !audio) {
          status.textContent = 'Добавьте сообщение или вложение.';
          return;
        }
        pendingNonce ||= crypto.randomUUID();
        const formData = new FormData();
        formData.set('nonce', pendingNonce);
        formData.set('text', text);
        if (replyTarget) formData.set('reply_to', replyTarget.id);
        if (authorAnswer) formData.set('featured', 'true');
        if (image) formData.set('photo', image);
        if (audio) formData.set('voice', audio, 'voice');
        submit.disabled = true;
        textarea.readOnly = true;
        attach.disabled = true;
        mic.disabled = true;
        status.textContent = 'Отправляем…';
        try {
          const data = await api('/posts', {method:'POST',body:formData});
          if (!panel.isConnected) return;
          merge(data);
          const posted = data.posts.at(-1);
          if (!more) cursor = Math.max(cursor, posted.id);
          pendingNonce = null;
          replyTarget = null;
          authorAnswer = false;
          context.replaceChildren();
          textarea.value = '';
          clearPhoto();
          clearVoice();
          status.textContent = '';
          renderTimeline();
          jump(posted.id);
        } catch (error) {
          status.textContent = error.message;
        } finally {
          submit.disabled = false;
          textarea.readOnly = false;
          attach.disabled = false;
          mic.disabled = false;
        }
      }

      function editProfile() {
        const dialog = element('dialog','day-discussion-profile-dialog');
        dialog.append(element('h2','','Мой профиль'));
        const controls = [
          ['Имя для обсуждения', 'input', 'name', profileData.name, 80],
          ['О себе', 'textarea', 'about', profileData.about, 500],
          ['Показывать карточку в обсуждении', 'input', 'visible', profileData.visible],
          ['Фотография', 'input', 'photo'],
          ['Удалить фотографию', 'input', 'remove_photo', false],
        ];
        const fields = new Map();
        for (const [caption, tag, key, value, max] of controls) {
          const label = element('label','',caption);
          const input = element(tag);
          if (typeof value === 'boolean') {
            input.type = 'checkbox';
            input.checked = value;
          } else if (key === 'photo') {
            input.type = 'file';
            input.accept = photo.accept;
          } else {
            input.value = value || '';
            input.maxLength = max;
          }
          label.append(input);
          fields.set(key,input);
          dialog.append(label);
        }
        const feedback = element('p','day-discussion-note');
        const save = button('Сохранить', async () => {
          save.disabled = true;
          const data = new FormData();
          for (const [key,input] of fields) {
            if (input.type === 'file') {
              if (input.files[0]) data.set(key,input.files[0]);
            } else data.set(key, input.type === 'checkbox' ? input.checked : input.value);
          }
          try {
            const saved = await api('/profile', {method:'PUT',body:data});
            dialog.close();
            const refreshed = await api('/thread');
            profileData = refreshed.profile;
            for (const item of posts.values()) {
              if (item.isAuthor) {
                item.name = profileData.visible ? profileData.name || 'Сергей' : 'Сергей';
                item.profile = saved.profile;
              }
            }
            merge(refreshed);
            renderTimeline();
          } catch(error) { feedback.textContent = error.message; }
          finally { save.disabled = false; }
        });
        dialog.append(save,button('Закрыть', () => dialog.close()),feedback);
        dialog.addEventListener('close', () => dialog.remove(), {once:true});
        panel.append(dialog);
        dialog.showModal();
      }

      function notificationSettings() {
        const dialog = element('dialog', 'day-discussion-profile-dialog');
        dialog.append(element('h2', '', 'Уведомления'));
        const info = element('p', 'day-discussion-note');
        const options = element('div', 'day-discussion-push-options');
        const choices = [
          ['replies', 'Ответы на мои вопросы', true],
          ['new_posts', 'Новые сообщения дня 4', false],
        ].map(([key, caption, checked]) => {
          const label = element('label', '', caption);
          const input = element('input');
          input.type = 'checkbox';
          input.checked = checked;
          label.prepend(input);
          options.append(label);
          return {key, input};
        });
        let registration;
        let subscription;
        const prefs = () => Object.fromEntries(choices.map(({key,input}) => [key,input.checked]));
        const save = button('Сохранить подписку', async () => {
          save.disabled = true;
          try {
            if (!('Notification' in window) || !('serviceWorker' in navigator) || !window.isSecureContext ||
                !location.pathname.startsWith('/lk')) {
              throw new Error('Откройте уведомления в личном кабинете через HTTPS. На iPhone добавьте кабинет на экран «Домой».');
            }
            const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
            if (permission !== 'granted') throw new Error('Разрешите уведомления для кабинета в настройках браузера.');
            registration = await navigator.serviceWorker.register('/masterclass-discussion-sw.js', {scope:'/lk'});
            registration = await navigator.serviceWorker.ready;
            subscription = await registration.pushManager.getSubscription();
            if (!subscription) {
              const {key} = await api('/push/key', {method:'POST'});
              const bytes = Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')), char => char.charCodeAt(0));
              subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
            }
            await api('/push/subscription', {
              method:'PUT', headers:{'Content-Type':'application/json'},
              body:JSON.stringify({...subscription.toJSON(), ...prefs()}),
            });
            info.textContent = 'Настройки этого устройства сохранены.';
          } catch (error) { info.textContent = error.message; }
          finally { save.disabled = false; }
        });
        const stop = button('Отключить на этом устройстве', async () => {
          if (!subscription) return;
          try {
            await api('/push/subscription', {
              method:'DELETE', headers:{'Content-Type':'application/json'},
              body:JSON.stringify({endpoint:subscription.endpoint}),
            });
            await subscription.unsubscribe();
            subscription = null;
            info.textContent = 'Уведомления отключены.';
          } catch (error) { info.textContent = error.message; }
        });
        function test(kind) {
          return async () => {
            if (!subscription) {
              info.textContent = 'Сначала включите подписку на этом устройстве.';
              return;
            }
            try {
              await api('/push/test', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({endpoint:subscription.endpoint,kind,nonce:crypto.randomUUID(),post_id:cursor || null}),
              });
              info.textContent = 'Тестовое уведомление поставлено в очередь.';
            } catch (error) { info.textContent = error.message; }
          };
        }
        dialog.append(options,save,stop,button('Проверить пуш об ответе', test('reply')),
          button('Проверить пуш о сообщении', test('day')),button('Закрыть', () => dialog.close()),info);
        dialog.addEventListener('close', () => dialog.remove(), {once:true});
        panel.append(dialog);
        dialog.showModal();
        if ('serviceWorker' in navigator) {
          navigator.serviceWorker.getRegistration('/lk').then(async current => {
            if (!current) return;
            subscription = await current.pushManager.getSubscription();
            if (!subscription || !dialog.isConnected) return;
            const stored = await api('/push/preferences', {
              method:'POST', headers:{'Content-Type':'application/json'},
              body:JSON.stringify({endpoint:subscription.endpoint}),
            });
            for (const {key,input} of choices) input.checked = stored[key];
          }).catch(() => {});
        }
      }

      merge(initial);
      cursor = initial.posts.at(-1)?.id || 0;
      const refreshTimer = setInterval(async () => {
        if (!panel.isConnected || document.hidden || more) return;
        try {
          const result = await api('/thread?after=' + cursor);
          if (result.posts.length && panel.isConnected) {
            cursor = result.posts.at(-1).id;
            more = result.more;
            merge(result);
            renderTimeline();
          }
        } catch { /* Keep the last loaded page and retry on the next interval. */ }
      }, 15000);

      actions.append(textarea, attach, mic, submit);
      const composeOptions = element('div', 'day-discussion-options');
      composeOptions.append(button('Мой профиль', editProfile, 'day-discussion-text-action'),
        button('Уведомления', notificationSettings, 'day-discussion-text-action'));
      form.append(composeOptions, context, photo, voiceFile, photoDraft, voiceDraft, actions, status, audioFallback);
      panel.append(form);
      renderTimeline();
      if (wanted) {
        if (matchMedia('(max-width: 900px)').matches) {
          document.querySelector('#sidebar.open #close')?.click();
        }
        jump(wanted);
      }
      return;
    }
    mountPanel();

    function mountPanel() {
      day.classList.add('day-discussion-open');
      day.append(panel);
      back.scrollIntoView({block:'start',behavior:'instant'});
      back.focus({preventScroll:true});
    }
  }

  function setBadge(entry, count) {
    const badge = entry?.querySelector('.day-discussion-unread');
    if (!badge) return;
    badge.hidden = !count;
    badge.textContent = String(count || 0);
    badge.setAttribute('aria-label', 'Непрочитанных: ' + (count || 0));
  }

  async function mount(day, assignment) {
    if (activePanel && !activePanel.isConnected) {
      pausePlayers(activePanel);
      releaseComposer();
      activePanel = null;
    }
    day.classList.remove('day-discussion-open');
    if (!assignment) return;
    let access;
    try { access = await api('/status'); }
    catch { return; }
    if (!assignment.isConnected || assignment.previousElementSibling?.classList.contains('day-discussion-entry') ||
        !['owner', 'locked'].includes(access.mode)) return;
    const entry = element('section', 'day-discussion-entry');
    entry.setAttribute('aria-label', 'Обсуждение дня');
    const copy = element('div');
    copy.append(element('strong', '', 'Обсуждение дня'), element('p', '',
      access.mode === 'locked' ? 'Тестовый режим' : 'Вопросы и ответы по материалам дня.'));
    const go = button('Обсуждение →', () => open(day, go, access.mode), 'next-button ready');
    go.append(element('span', 'day-discussion-unread'));
    entry.append(copy, go);
    assignment.before(entry);
    dayEntry = entry;
    setBadge(entry, access.unread);
    const link = new URL(location.href);
    const wanted = Number(link.searchParams.get('discussion_post'));
    if (wanted && access.mode === 'owner') {
      link.searchParams.delete('discussion_post');
      history.replaceState(history.state, '', link);
      open(day, go, access.mode, wanted);
    }
  }

  window.EdabalansMasterclassDiscussion = {mount};
})();
