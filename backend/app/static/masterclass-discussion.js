(() => {
  if (window.EdabalansMasterclassDiscussion) return;
  const authorName = 'Сергей Воронцов';
  const voiceLimit = 16_000_000;
  const voiceBitrate = 128_000;
  const notice = 'Обсуждения пока доступны только автору курса. Дождитесь уведомления об открытии.';
  const panelsByCard = new WeakMap();
  let activePanel = null;
  let releaseComposer = () => {};
  let voiceTemplate = '';

  function dayPath(number) {
    return '/api/masterclass/discussion/day-' + String(number).padStart(2, '0');
  }

  async function requestForDay(number, path, options = {}) {
    const response = await fetch(dayPath(number) + path, {cache:'no-store', ...options});
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
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 22v-2a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5v2"/>',
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

  function player(src, author = authorName) {
    const frame = element('iframe', 'day-voice-frame');
    frame.title = 'Голосовое сообщение';
    const values = {src, author, avatar:'', duration:'—:—'};
    function escape(value) {
      const text = element('span', '', value);
      return text.innerHTML.replaceAll('"', '&quot;');
    }
    frame.srcdoc = voiceTemplate.replace(/{{(src|author|duration)}}/g,
      (placeholder, key) => escape(values[key])).replace('</style>',
        'html,body{overflow:hidden}body{padding:5px 9px 9px 5px}.voice-widget{grid-template-columns:minmax(0,1fr)}.voice-widget__avatar,.voice-widget__author>span:first-child{display:none}.voice-widget__author{position:absolute;bottom:8px;left:calc(69px + var(--bubble-tail));min-height:0;line-height:14px;pointer-events:none}.voice-widget__bubble-shadow{margin-left:0}.voice-widget__bubble{min-height:0;padding-block:8px}.voice-widget__player{margin-top:0}</style>');
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
    return item.isOwn;
  }

  function messageName(message) {
    if (message.isAuthor) return authorName;
    return message.ownerIdentity ? message.ownerIdentity.name || 'Имя не указано' : message.name;
  }

  function quote(target, jump) {
    const text = quoteText(target);
    const node = button('', () => jump(target.id), 'day-discussion-quote');
    node.setAttribute('aria-label', 'Перейти к сообщению: ' + text);
    node.append(element('span', 'day-discussion-quote-name', messageName(target) || 'Вопрос из обсуждения'),
      element('span', 'day-discussion-quote-text', text));
    return node;
  }

  function message(item, byId, answers, jump, reply, editProfile) {
    const own = isOwnMessage(item);
    const card = element('article', 'day-discussion-message' + (own ? ' own' : '') + (item.isAuthor ? ' by-author' : ''));
    card.id = 'day-discussion-message-' + item.id;
    card.tabIndex = -1;
    if (item.name) {
      const displayName = messageName(item);
      const author = element('div', 'day-discussion-name');
      const avatar = element('span', 'day-discussion-avatar', displayName[0]);
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
        profile.append(element('strong', '', displayName));
        if (item.profile?.about) profile.append(element('p','',item.profile.about));
        if (own) profile.append(button('Мой профиль', editProfile, 'day-discussion-text-action'));
        profile.hidden = true;
        const name = button('', () => {
          profile.hidden = !profile.hidden;
          name.setAttribute('aria-expanded', String(!profile.hidden));
        }, 'day-discussion-profile-name');
        name.append(avatar, element('span', '', displayName));
        name.setAttribute('aria-expanded', 'false');
        author.append(name);
        card.append(author, profile);
      } else {
        author.append(avatar, element('span', '', displayName));
        card.append(author);
      }
    }
    if (item.ownerIdentity) {
      const {email, telegram, telegramLinked} = item.ownerIdentity;
      const contact = element('div', 'day-discussion-identity');
      const username = telegram?.trim().replace(/^@+/, '');
      contact.append(element('span', '', email || 'Почта не указана'),
        element('span', '', username ? '@' + username : telegramLinked ? 'В Telegram нет ника' : 'Telegram не привязан'));
      card.append(contact);
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

  async function open(day, entry, dayNumber, mode, wanted = 0) {
    const api = (path, options) => requestForDay(dayNumber, path, options);
    const returnEntry = entry.closest('.day-discussion-entry');
    const cardEntry = Number(returnEntry.dataset.dayNumber) === dayNumber ? returnEntry : null;
    const base = dayPath(dayNumber);
    if (day.querySelector('.day-discussion-panel')) return;
    const panel = element('section', 'day-discussion-panel');
    if (cardEntry) panelsByCard.set(cardEntry, panel);
    function updateCard(total, unread) {
      if (cardEntry && panelsByCard.get(cardEntry) === panel) updateMessageCount(cardEntry, total, unread);
    }
    activePanel = panel;
    const head = element('div', 'article-head');
    const dayObserver = new MutationObserver(() => {
      if (day.hidden || !panel.isConnected) dismiss();
    });
    function dismiss() {
      dayObserver.disconnect();
      if (activePanel !== panel) return;
      pausePlayers(panel);
      panel.remove();
      releaseComposer();
      activePanel = null;
      day.classList.remove('day-discussion-open');
    }
    const back = button('← К дню ' + returnEntry.dataset.dayNumber, () => {
      dismiss();
      entry.scrollIntoView({block:'center',behavior:'instant'});
      entry.focus({preventScroll:true});
      document.querySelector('.course-shell #sidebar.open #close')?.click();
    });
    head.classList.add('day-discussion-head');
    const theme = button('', () => {
      document.querySelector('.course-shell .account-theme-toggle')?.click();
      syncTheme();
    }, 'day-discussion-theme');
    function syncTheme() {
      const original = document.querySelector('.course-shell .account-theme-toggle');
      if (!original) return;
      theme.innerHTML = original.innerHTML;
      theme.setAttribute('aria-label', original.getAttribute('aria-label'));
      theme.setAttribute('aria-pressed', original.getAttribute('aria-pressed'));
    }
    syncTheme();
    back.classList.add('day-discussion-back');
    const outline = button('☰ Оглавление', () => document.querySelector('.course-shell .topbar #menu')?.click(),
      'day-discussion-outline back');
    const headActions = element('div', 'day-discussion-head-actions');
    headActions.append(theme);
    head.append(back, outline, element('h1', '', 'Обсуждение дня № ' + dayNumber), headActions);
    panel.append(head);
    const themeObserver = new MutationObserver(syncTheme);
    themeObserver.observe(document.documentElement, {attributes:true, attributeFilter:['data-account-theme']});
    releaseComposer = () => themeObserver.disconnect();
    panel.addEventListener('click', event => {
      const clickedMessage = event.target.closest('.day-discussion-profile-name, .day-discussion-profile')?.closest('article');
      for (const shown of panel.querySelectorAll('.day-discussion-profile:not([hidden])')) {
        if (shown.closest('article') === clickedMessage) continue;
        shown.hidden = true;
        shown.parentElement.querySelector('.day-discussion-profile-name').setAttribute('aria-expanded', 'false');
      }
    });
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
      const canAuthor = initial.canAuthor;
      let profileData = initial.profile;
      const posts = new Map();
      const related = new Map();
      const answers = {};
      let unreadStart = initial.firstUnread;
      let more = initial.more;
      let cursor = 0;
      let pendingNonce = null;
      let replyTarget = null;
      let authorAnswer = false;
      const readIds = new Set();
      const timeline = element('div', 'day-discussion-timeline');
      const settings = element('section', 'day-discussion-settings');
      settings.hidden = true;
      const contact = element('div', 'day-discussion-contact');
      window.EdabalansFooter?.mountDiscussionLinks?.(contact);
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
      mic.disabled = !canAuthor;

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

      function draftVoice(audio, preview = audio) {
        if (!audio?.size || audio.size > voiceLimit) {
          status.textContent = 'Не удалось сохранить голосовое. Максимальный размер — 16 МБ.';
          return;
        }
        clearVoice();
        voiceRecording = audio;
        voiceDraftUrl = URL.createObjectURL(preview);
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
        mic.disabled = !canAuthor;
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
          recorder = new MediaRecorder(stream, {audioBitsPerSecond:voiceBitrate});
          const chunks = [];
          recorder.ondataavailable = (event) => {
            if (event.data.size) chunks.push(event.data);
          };
          recorder.onstop = async () => {
            stream.getTracks().forEach(track => track.stop());
            if (!panel.isConnected) return;
            const recording = new Blob(chunks, {type:recorder.mimeType});
            if (recording.size && recording.size <= voiceLimit) {
              status.textContent = 'Готовим голосовое…';
              try {
                const data = new FormData();
                data.append('voice', recording, 'recording');
                const response = await fetch(base + '/voice-preview', {method:'POST',body:data,cache:'no-store'});
                if (!response.ok) throw new Error('Audio conversion failed');
                const ready = await response.blob();
                if (panel.isConnected) {
                  status.textContent = '';
                  draftVoice(recording, ready);
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
          mic.disabled = !canAuthor;
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

      let readRevision = 0;
      async function fetchTimeline(path, options) {
        const revision = readRevision;
        const response = await api(path, options);
        return {...response, readRevision:revision};
      }
      let pendingRead = [];
      let readTimer = 0;
      let readInFlight = false;
      async function flushRead() {
        if (readInFlight || !pendingRead.length) return;
        readInFlight = true;
        let retry = false;
        const ids = pendingRead.splice(0, 100);
        try {
          const result = await api('/read', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ids}),
          });
          readRevision += 1;
          updateCard(null, result.unread);
        } catch {
          if (panel.isConnected) {
            pendingRead.unshift(...ids);
            retry = true;
          }
        } finally {
          readInFlight = false;
          if (pendingRead.length) {
            clearTimeout(readTimer);
            readTimer = setTimeout(flushRead, retry ? 3000 : 0);
          }
        }
      }
      const readObserver = new IntersectionObserver(entries => {
        if (document.hidden || panel.querySelector('.day-discussion-guide[open]')) return;
        for (const entry of entries) {
          const id = Number(entry.target.closest('.day-discussion-message').id.replace('day-discussion-message-', ''));
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
      function observeTimeline() {
        readObserver.disconnect();
        if (document.hidden || panel.querySelector('.day-discussion-guide[open]')) return;
        for (const messageName of timeline.querySelectorAll('.day-discussion-name')) readObserver.observe(messageName);
      }
      document.addEventListener('visibilitychange', observeTimeline);
      releaseComposer = () => {
        themeObserver.disconnect();
        document.removeEventListener('visibilitychange', observeTimeline);
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
            merge(await fetchTimeline('/thread?around=' + encodeURIComponent(id)));
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
        if (canAuthor && !isOwnMessage(item)) {
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
        if (!unreadStart) unreadStart = data.firstUnread;
        updateCard(data.total,
          data.readRevision == null || data.readRevision === readRevision ? data.unread : null);
      }

      const nextPage = button('Ещё сообщения', async () => {
        nextPage.disabled = true;
        try {
          const result = await fetchTimeline('/thread?after=' + cursor);
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
        function appendMessage(item) {
          if (item.id === unreadStart) timeline.append(element('p', 'day-discussion-unread-line', 'Непрочитанные сообщения'));
          timeline.append(message(item, byId, answers, jump, selectReply, editProfile));
        }
        const old = items.filter(item => item.archived);
        if (old.length) {
          timeline.append(element('h2', 'day-discussion-divider', 'Старые обсуждения'));
          for (const item of old) appendMessage(item);
        }
        timeline.append(element('h2', 'day-discussion-divider new-questions', 'Новые вопросы'));
        let lastDate = '';
        for (const item of items.filter(post => !post.archived)) {
          const date = dateLabel(item.at);
          if (date && date !== lastDate) timeline.append(element('p', 'day-discussion-date', date));
          lastDate = date;
          appendMessage(item);
        }
        if (more) timeline.append(nextPage);
        observeTimeline();
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
          const data = await fetchTimeline('/posts', {method:'POST',body:formData});
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
          mic.disabled = !canAuthor;
        }
      }

      let settingsScroll = 0;
      let notifications;
      const profileControl = composerButton('user', 'Мой профиль', editProfile);
      profileControl.classList.add('day-discussion-theme');
      headActions.append(profileControl);

      function openGuide() {
        const guide = element('dialog', 'day-discussion-profile-dialog day-discussion-guide');
        guide.append(element('h2', '', 'Как устроено обсуждение'));
        const tips = [
          ['Мой профиль', 'Нажмите на значок человека вверху. Там можно изменить имя и фото и выбрать, какие уведомления получать на этом устройстве.'],
          ['Старые обсуждения', 'Здесь собраны прежние вопросы и ответы. Нажмите «Ответ Сергея», чтобы раскрыть ответ под вопросом.'],
          ['Новые вопросы', 'Здесь идёт текущая переписка. Сообщения Сергея Воронцова выделены оранжевым. Нажмите на цитату, чтобы перейти к исходному сообщению.'],
          ['Ваше сообщение', 'Поле ввода внизу. Нажмите скрепку, чтобы добавить фото. Голосовые записывает Сергей Воронцов. Метка «Непрочитанные сообщения» показывает, где вы остановились.'],
        ];
        for (const [title, copy] of tips) {
          const heading = element('h3', '', title);
          if (title === 'Мой профиль') {
            const icon = element('span', 'day-discussion-guide-icon');
            setIcon(icon, 'user');
            heading.prepend(icon);
          }
          guide.append(heading, element('p', '', copy));
          if (title === 'Новые вопросы') {
            const preview = element('div', 'day-discussion-guide-example');
            preview.append(element('span', '', authorName), element('p', '', 'Ответ на вопрос участника'));
            guide.append(preview);
          }
        }
        guide.append(button('Понятно', () => guide.close()));
        guide.addEventListener('click', event => {
          if (event.target === guide) {
            const box = guide.getBoundingClientRect();
            if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) guide.close();
          }
        });
        guide.addEventListener('close', () => {
          guide.remove();
          if (panel.isConnected) observeTimeline();
        }, {once:true});
        panel.append(guide);
        guide.showModal();
        readObserver.disconnect();
      }

      function editProfile() {
        if (!settings.hidden) return;
        settingsScroll = scrollY;
        pausePlayers(timeline);
        timeline.hidden = form.hidden = contact.hidden = true;
        settings.hidden = false;
        const settingsHead = element('div', 'day-discussion-settings-head');
        settingsHead.append(element('h2', '', 'Мой профиль'),
          button('Как устроен раздел обсуждения?', openGuide, 'day-discussion-text-action'));
        settings.replaceChildren(settingsHead);
        const formFields = element('form', 'day-discussion-settings-form');
        const field = (caption, placeholder, tag, key, value, max) => {
          const label = element('label', '', caption);
          const input = element(tag);
          input.name = key;
          input.setAttribute('aria-label', caption);
          input.placeholder = placeholder;
          input.value = value || '';
          input.maxLength = max;
          label.append(input);
          formFields.append(label);
        };
        field('Ваше имя (его увидят другие участники)', 'Введите ваше имя', 'input', 'name', profileData.name, 80);
        const about = element('textarea');
        about.name = 'about';
        about.value = profileData.about || '';
        about.maxLength = 500;
        about.placeholder = 'Пару слов о себе (если хотите)';
        about.setAttribute('aria-label', about.placeholder);
        formFields.append(about);
        const file = element('input');
        file.type = 'file';
        file.name = 'photo';
        file.accept = photo.accept;
        file.hidden = true;
        const filename = element('span', 'day-discussion-note', profileData.avatar ? 'Фото профиля загружено' : '');
        let remove = false;
        const removePhoto = button('Удалить фотографию', () => {
          file.value = '';
          remove = true;
          removePhoto.hidden = true;
          filename.textContent = 'Фото будет удалено после сохранения.';
        }, 'day-discussion-text-action');
        removePhoto.hidden = !profileData.avatar;
        file.onchange = () => {
          if (!file.files.length) return;
          remove = false;
          filename.textContent = file.files[0].name;
          removePhoto.hidden = false;
        };
        const photoActions = element('div', 'day-discussion-settings-actions');
        photoActions.append(button('Выбрать файл', () => file.click()), removePhoto);
        const privacy = element('a', 'day-discussion-text-action', 'Политика обработки персональных данных');
        privacy.href = '/legal/privacy';
        formFields.append(element('span', '', 'Фотография'), file, photoActions, filename, privacy);
        notifications ??= notificationSettings();
        settings.append(formFields, notifications);
        const feedback = element('p', 'day-discussion-note');
        feedback.setAttribute('role', 'status');
        function closeSettings() {
          settings.hidden = true;
          settings.replaceChildren();
          timeline.hidden = form.hidden = contact.hidden = false;
          scrollTo(0, settingsScroll);
          profileControl.focus({preventScroll:true});
        }
        const save = button('Сохранить', () => formFields.requestSubmit(), 'next-button ready');
        const close = button('Закрыть', closeSettings);
        formFields.onsubmit = async event => {
          event.preventDefault();
          save.disabled = close.disabled = true;
          feedback.textContent = '';
          const data = new FormData(formFields);
          const selected = file.files[0];
          if (!selected) data.delete('photo');
          data.set('remove_photo', remove);
          data.set('visible', Boolean(data.get('name').trim() || data.get('about').trim() || selected || (!remove && profileData.avatar)));
          try {
            const saved = await api('/profile', {method:'PUT',body:data});
            profileData = {...profileData, name:data.get('name').trim(), about:data.get('about').trim(), avatar:saved.avatar};
            for (const item of [...posts.values(), ...related.values()]) if (item.isOwn) {
              item.name = item.isAuthor ? authorName : saved.profile?.name || profileData.defaultName;
              item.profile = saved.profile;
            }
            renderTimeline();
            closeSettings();
          } catch(error) { feedback.textContent = error.message; }
          finally { save.disabled = close.disabled = false; }
        };
        const actions = element('div', 'day-discussion-settings-submit');
        actions.append(save, close);
        settings.append(actions, feedback);
        scrollTo(0, 0);
        settings.querySelector('h2').tabIndex = -1;
        settings.querySelector('h2').focus({preventScroll:true});
      }

      function notificationSettings() {
        const section = element('section', 'day-discussion-push');
        section.append(element('h3', '', 'Уведомления:'));
        const info = element('p', 'day-discussion-note');
        info.setAttribute('role', 'status');
        const options = element('div', 'day-discussion-push-options');
        const choices = [
          ['replies', 'Ответы на мои вопросы'],
          ['new_posts', 'Новые сообщения от других участников'],
        ].map(([key, caption]) => {
          const label = element('label', '', caption);
          const input = element('input');
          input.type = 'checkbox';
          input.checked = true;
          input.onchange = () => subscription && enabled ? update(savePreferences) : sync();
          label.prepend(input);
          options.append(label);
          return {key, input};
        });
        let registration, subscription;
        let enabled = false;
        let busy = true;
        let savedChoices;
        const preferences = () => Object.fromEntries(choices.map(({key,input}) => [key,input.checked]));
        const toggle = button('', () => update(enabled ? disable : enable), 'day-discussion-push-switch');
        const state = element('span', 'day-discussion-push-state');
        const track = element('span', 'day-discussion-push-track');
        state.setAttribute('aria-hidden', 'true');
        track.setAttribute('aria-hidden', 'true');
        toggle.setAttribute('role', 'switch');
        toggle.setAttribute('aria-label', 'Уведомления на этом устройстве');
        toggle.append(element('span', '', 'Уведомления на этом устройстве'), state, track);
        function sync() {
          toggle.setAttribute('aria-checked', String(enabled));
          state.textContent = enabled ? 'Вкл' : 'Выкл';
          toggle.disabled = busy || (!enabled && choices.every(({input}) => !input.checked));
          for (const {input} of choices) input.disabled = busy;
        }
        async function update(action) {
          if (busy) return;
          busy = true;
          sync();
          try { await action(); }
          catch (error) {
            if (savedChoices) for (const {key,input} of choices) input.checked = savedChoices[key];
            info.textContent = error.message;
          } finally { busy = false; sync(); }
        }
        async function savePreferences() {
          const prefs = preferences();
          await api('/push/subscription', {
            method:'PUT', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({...subscription.toJSON(), ...prefs}),
          });
          savedChoices = prefs;
          enabled = true;
          info.textContent = 'Настройки этого устройства сохранены.';
        }
        async function enable() {
          if (!('Notification' in window) || !('PushManager' in window) || !('serviceWorker' in navigator) ||
              !window.isSecureContext || !location.pathname.startsWith('/lk')) {
            throw new Error('Откройте кабинет в поддерживаемом браузере. На iPhone откройте его с иконки на экране «Домой».');
          }
          const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
          if (permission !== 'granted') throw new Error('Разрешите уведомления для кабинета в настройках устройства или браузера.');
          registration = await navigator.serviceWorker.register('/masterclass-discussion-sw.js', {scope:'/lk'});
          registration = await navigator.serviceWorker.ready;
          subscription = await registration.pushManager.getSubscription();
          if (!subscription) {
            const {key} = await api('/push/key', {method:'POST'});
            const bytes = Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')), char => char.charCodeAt(0));
            subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
          }
          await savePreferences();
        }
        async function disable() {
          await api('/push/subscription', {
            method:'DELETE', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({endpoint:subscription.endpoint}),
          });
          enabled = false;
          savedChoices = null;
          info.textContent = 'Уведомления отключены.';
          await subscription.unsubscribe();
          subscription = null;
        }
        async function loadSettings() {
          try {
            if (!('serviceWorker' in navigator)) return;
            const current = await navigator.serviceWorker.getRegistration('/lk');
            subscription = await current?.pushManager?.getSubscription();
            if (!subscription) return;
            const stored = await api('/push/preferences', {
              method:'POST', headers:{'Content-Type':'application/json'},
              body:JSON.stringify({endpoint:subscription.endpoint}),
            });
            enabled = stored.enabled;
            if (enabled) {
              savedChoices = stored;
              for (const {key,input} of choices) input.checked = stored[key];
            }
          } catch (error) { info.textContent = error.message; }
          finally { busy = false; sync(); }
        }
        const install = element('a', 'day-discussion-text-action', 'Как установить кабинет');
        install.href = '/lk/install';
        section.append(toggle, options, install, info);
        sync();
        loadSettings();
        return section;
      }

      merge(initial);
      cursor = initial.posts.at(-1)?.id || 0;
      const refreshTimer = setInterval(async () => {
        if (!panel.isConnected || document.hidden || more) return;
        try {
          const result = await fetchTimeline('/thread?after=' + cursor);
          if (!panel.isConnected) return;
          merge(result);
          if (result.posts.length) {
            cursor = result.posts.at(-1).id;
            more = result.more;
            renderTimeline();
          }
        } catch { /* Keep the last loaded page and retry on the next interval. */ }
      }, 15000);

      actions.append(textarea, attach, mic, submit);
      form.append(context, photo, voiceFile, photoDraft, voiceDraft, actions, status, audioFallback);
      panel.append(form, contact, settings);
      renderTimeline();
      try {
        if (!localStorage.getItem('masterclass-discussion-guide-v1')) {
          openGuide();
          localStorage.setItem('masterclass-discussion-guide-v1', 'seen');
        }
      } catch { /* Keep the guide available from My profile when storage is unavailable. */ }
      if (wanted || new URL(location.href).searchParams.has('discussion_open')) {
        if (matchMedia('(max-width: 900px)').matches) {
          document.querySelector('#sidebar.open #close')?.click();
        }
        const link = new URL(location.href);
        link.searchParams.delete('discussion_open');
        link.searchParams.delete('discussion_post');
        history.replaceState(history.state, '', link);
        if (wanted) jump(wanted);
      }
      return;
    }
    mountPanel();

    function mountPanel() {
      day.classList.add('day-discussion-open');
      day.append(panel);
      dayObserver.observe(day, {attributes:true, attributeFilter:['hidden'], childList:true});
      scrollTo(0, 0);
      syncTheme();
      (matchMedia('(max-width: 900px)').matches ? outline : back).focus({preventScroll:true});
    }
  }

  function updateMessageCount(entry, total, unread) {
    const label = entry?.querySelector('.day-discussion-total');
    const badge = entry?.querySelector('.day-discussion-count');
    if (!label || !badge) return;
    if (total != null) {
      label.dataset.total = total;
      label.textContent = ' (сообщений: ' + total + ')';
    }
    if (unread != null) badge.textContent = String(unread);
    const unreadCount = Number(badge.textContent);
    badge.hidden = unreadCount === 0;
    badge.parentElement.setAttribute('aria-label', 'Обсуждение. Сообщений: ' +
      label.dataset.total + ', непрочитанных: ' + unreadCount);
  }

  async function mount(day, assignment, dayNumber) {
    if (activePanel && !activePanel.isConnected) {
      pausePlayers(activePanel);
      releaseComposer();
      activePanel = null;
    }
    day.classList.remove('day-discussion-open');
    if (!assignment) return;
    const link = new URL(location.href);
    const wanted = Number(link.searchParams.get('discussion_post'));
    const openOnLoad = wanted || link.searchParams.has('discussion_open');
    const requested = openOnLoad ? Number(link.searchParams.get('course_day')) || dayNumber : dayNumber;
    let access;
    try { access = await requestForDay(dayNumber, '/status'); }
    catch { return; }
    if (!assignment.isConnected || assignment.previousElementSibling?.classList.contains('day-discussion-entry') ||
        !['owner', 'locked'].includes(access.mode)) return;
    const entry = element('section', 'day-discussion-entry');
    entry.setAttribute('aria-label', 'Обсуждение дня');
    entry.dataset.dayNumber = dayNumber;
    const copy = element('div', 'day-discussion-entry-copy');
    const heading = element('div', 'day-discussion-entry-heading');
    heading.append(element('strong', '', 'Обсуждение дня'));
    copy.append(heading, element('p', '', access.mode === 'locked'
      ? 'Доступ пока закрыт'
      : 'Прочитайте вопросы, которые задавали другие участники, и ответы на них. Либо задайте свой личный вопрос.'));
    const go = button('Обсуждение →', () => open(day, go, dayNumber, access.mode), 'next-button ready');
    entry.append(copy, go);
    if (access.mode === 'owner') {
      const count = element('span', 'day-discussion-count');
      count.setAttribute('aria-hidden', 'true');
      go.append(count);
      heading.append(element('span', 'day-discussion-total'));
      updateMessageCount(entry, access.total ?? 0, access.unread);
    }
    assignment.before(entry);
    if (openOnLoad && access.mode === 'owner') {
      const requestedAccess = requested === dayNumber ? access : await requestForDay(requested, '/status').catch(() => null);
      if (assignment.isConnected && requestedAccess?.mode === 'owner') {
        open(day, go, requested, requestedAccess.mode, wanted);
      }
    }
  }

  window.EdabalansMasterclassDiscussion = {mount};
})();
