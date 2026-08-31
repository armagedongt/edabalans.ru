import json
import os
import re
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.course_structure_service import normalize_seed  # noqa: E402


client = TestClient(app)


def test_masterclass_article_tables_keep_mobile_scroll_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")

    wrapper = re.search(r"\.article-table-wrap\{(?P<rules>[^}]*)\}", source)
    table = re.search(r"\.article-data-table\{(?P<rules>[^}]*)\}", source)
    assert wrapper is not None
    assert "overflow-x:auto" in wrapper.group("rules")
    assert table is not None
    assert "min-width:620px" in table.group("rules")


def test_stable_embed_loader_is_public() -> None:
    response = client.get("/embed.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "data-edabalans-app" in response.text


def test_course_footer_contract_is_shared_and_minimal() -> None:
    loader = client.get("/embed.js").text
    assert "data-edabalans-legal-footer" in loader
    assert "data-edabalans-footer-owner" in loader
    assert 'data-edabalans-footer-action="dqs-tutorial"' not in loader
    assert 'mount.querySelector(\'[data-edabalans-app="dqs"]\')' in loader
    assert "mount.parentElement.closest('[data-edabalans-footer-owner]')" in loader
    assert "ensureLegalFooter(mount);" in loader
    assert "function legalFooterHost(mount)" in loader
    assert 'var dqsMount = mount.querySelector(\'[data-edabalans-app="dqs"]\')' in loader
    assert "if (dqsMount) return dqsMount" in loader
    assert "courseMount.querySelector(':scope > .main')" in loader
    assert "footer.parentElement !== host" in loader
    assert "host.appendChild(footer)" in loader
    assert "{childList: true, subtree: true}" in loader
    footer = loader[loader.index("function legalFooterHtml"):loader.index("function ensureLegalFooter")]
    assert "data-edabalans-footer-context" in footer
    assert "© ' + new Date().getFullYear() + ' Воронцов Сергей" in footer
    assert "Полное или частичное копирование запрещено" in footer
    assert "Контакты:" in footer
    assert 'href="https://t.me/FitnessSergey" target="_blank" rel="noopener" style="color:inherit">Telegram</a>' in footer
    assert 'href="https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw" target="_blank" rel="noopener" style="color:inherit">MAX</a>' in footer
    assert 'href="https://go.похудение-это-есть.рф/legal/disclaimer" target="_blank" rel="noopener" style="color:inherit">Образовательный дисклеймер</a>' in footer
    assert 'href="https://go.похудение-это-есть.рф/legal/privacy" target="_blank" rel="noopener" style="color:inherit">Политика обработки данных</a>' in footer
    assert "Похудение — это есть!" not in footer
    assert "/legal/offer" not in footer
    assert "/legal/consent" not in footer


def test_stable_site_footer_loader_is_public() -> None:
    response = client.get("/site-footer.js")
    text = response.text.replace("\r\n", "\n")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "data-edabalans-site-footer" in text
    assert "new Date().getFullYear()" in text
    assert "ИП Воронцов Сергей Сергеевич" in text
    assert "ИНН 230409966750" in text
    assert "Все права защищены" in text
    assert "Копирование материалов запрещено" in text
    assert "root.innerHTML = markup(index)" in text
    assert "roots.forEach(mount)" in text
    assert "document.addEventListener('DOMContentLoaded', boot)" in text
    close_all = re.search(
        r"    function closeAll\(\) \{\n(?P<body>.*?)\n    \}\n\n    buttons\.forEach",
        text,
        re.DOTALL,
    )
    assert close_all is not None
    assert "item.setAttribute('aria-expanded', 'false')" in close_all.group("body")
    assert "item.hidden = false" in close_all.group("body")
    assert "item.hidden = true" in close_all.group("body")
    assert "panel.hidden = false" in text
    click_handler = re.search(
        r"button\.addEventListener\('click', function \(\) \{(?P<body>.*?)\n\s*\}\);",
        text,
        re.DOTALL,
    )
    assert click_handler is not None
    click_body = click_handler.group("body")
    assert click_body.index("closeAll();") < click_body.index("panel.hidden = false;")
    assert click_body.index("button.hidden = true;") < click_body.index("panel.hidden = false;")
    close_handler = re.search(
        r"closeButton\.addEventListener\('click', function \(\) \{(?P<body>.*?)\n\s*\}\);",
        response.text,
        re.DOTALL,
    )
    assert close_handler is not None
    assert "closeAll();" in close_handler.group("body")
    assert "button.focus();" in close_handler.group("body")
    assert "data-close-panel>Бесплатный интенсив" in response.text
    assert "data-close-panel>Контакты" in response.text
    assert re.search(
        r"'<div class=\"eb-site-footer__action-group\">' \+\s*"
        r"'<button.*?data-panel=\"' \+ intensiveId .*?</button>' \+\s*"
        r"'<section.*?id=\"' \+ intensiveId .*?</section>' \+\s*"
        r"'</div>' \+",
        response.text,
        re.DOTALL,
    )
    assert re.search(
        r"'<div class=\"eb-site-footer__action-group\">' \+\s*"
        r"'<button.*?data-panel=\"' \+ contactsId .*?</button>' \+\s*"
        r"'<section.*?id=\"' \+ contactsId .*?</section>' \+\s*"
        r"'</div>' \+",
        response.text,
        re.DOTALL,
    )
    assert ".eb-site-footer{box-sizing:border-box;width:100%;background:transparent" in response.text
    assert "https://t.me/Fitness_Talks_bot?start=" in response.text
    assert "https://t.me/Fitness_Talks" in response.text
    assert "https://t.me/FitnessSergey" in response.text
    assert "https://max.ru/u/" in response.text
    assert "LINKS.intensiveTelegram" in response.text
    assert "Понадобится VPN" in response.text
    assert "Пока недоступно" not in response.text
    assert "optionLink(LINKS.telegramChannel, 'Telegram-канал')" in response.text
    assert "optionLink(LINKS.telegram, 'Написать в Telegram')" in response.text
    assert "optionLink(LINKS.max, 'Написать в MAX')" in response.text
    assert "MAX-канал" in response.text
    assert "Скоро" in response.text
    assert "https://go.похудение-это-есть.рф/legal/offer" in response.text
    assert "https://go.похудение-это-есть.рф/legal/privacy" in response.text
    assert "https://go.похудение-это-есть.рф/legal/consent" in response.text
    assert "https://go.похудение-это-есть.рф/legal/disclaimer" in response.text
    assert "link(LINKS.offer, 'Оферта')" in response.text
    assert "link(LINKS.privacy, 'Политика обработки данных')" in response.text
    assert "link(LINKS.consent, 'Согласие на обработку данных')" in response.text
    assert "link(LINKS.disclaimer, 'Образовательный дисклеймер')" in response.text


def test_application_fragments_use_server_api() -> None:
    for app_code in ("dqs", "strength", "metabolism"):
        response = client.get(f"/apps/{app_code}.html")
        assert response.status_code == 200
        assert "api.edabalans.ru/api/apps/" in response.text
        assert "REDACTED_LEGACY_APPS_SCRIPT_URL" not in response.text
        lowered = response.text.lower()
        assert "google" not in lowered
        assert "apps script" not in lowered

    dqs = client.get("/apps/dqs.html").text
    assert "showLogin" not in dqs
    assert "loginUser" not in dqs
    assert 'id="dqs-email"' not in dqs
    assert 'type="email"' not in dqs
    assert "window.EdabalansIdentity" in dqs
    assert "tildaIdentity.source === 'tilda'" in dqs
    assert "tma__userbar__sendLogout" in dqs
    assert "location.replace('/members/login')" in dqs
    assert "dqs-app-footer" not in dqs
    assert "renderAppFooter" not in dqs
    assert "Все права защищены" not in dqs
    assert "© ${new Date().getFullYear()}" not in dqs
    assert "Сергей Воронцов" not in dqs
    desktop_grid = "grid-template-columns:minmax(0,1.42fr) minmax(58px,1fr) minmax(58px,.92fr) 42px"
    compact_grid = "grid-template-columns:minmax(0,1.36fr) minmax(52px,1fr) minmax(52px,.94fr) 42px"
    assert dqs.count(desktop_grid) == 3  # base, max-width:520px and tutorial preview
    assert compact_grid in dqs  # max-width:385px
    assert dqs.count('class="dqs-foot-left"') == 2  # diary and scores
    assert dqs.count('class="dqs-foot-account"') == 2
    assert dqs.count('onclick="window.EdabalansDqsOpenTutorial()"') == 2
    assert "function masterclassCategoriesUrl()" in dqs
    assert "url.searchParams.set('course_day', '4')" in dqs
    assert "url.searchParams.set('course_material', 'day-04-article-01')" in dqs
    assert 'href="${MASTERCLASS_CATEGORIES_URL}"' in dqs
    assert "opisanie-produktovyh-kategorij" not in dqs
    dqs_mobile = dqs.split("@media(max-width:520px){", 1)[1].split(
        "@media(max-width:385px){", 1
    )[0]
    dqs_narrow = dqs.split("@media(max-width:385px){", 1)[1].split("</style>", 1)[0]
    for mobile_rules in (dqs_mobile, dqs_narrow):
        assert re.search(
            r"\.dqs-chip-date-text\s*\{\s*font-size:13px", mobile_rules
        )
        assert re.search(
            r"\.dqs-chip-day,\s*\.dqs-chip-score\s*\{\s*font-size:15px",
            mobile_rules,
        )
    date_formatter = dqs[
        dqs.index("function getDateForDay") : dqs.index("function isCurrentDayToday")
    ]
    assert "year:'numeric'" not in date_formatter
    dqs_radii = set(re.findall(r"border-radius:([^;]+)", dqs))
    assert dqs_radii <= {
        "8px",
        "10px",
        "var(--radius-control)",
        "var(--radius-small)",
        "var(--radius-large)",
    }


def test_client_apps_share_design_tokens_account_link_and_single_footer() -> None:
    shell = client.get("/assets/app-shell.css")
    assert shell.status_code == 200
    assert "--ed-app-accent:#6f3de8" in shell.text
    assert "--ed-app-radius-large:16px" in shell.text
    assert "--ed-app-radius-small:10px" in shell.text
    assert "--ed-app-radius-control:8px" in shell.text
    assert ".ed-app-account-link" in shell.text
    assert "border-radius:var(--ed-app-radius-control)" in shell.text

    account = client.get("/apps/account.html").text
    assert "border-radius:var(--radius-large)" in account
    assert "border-radius:var(--radius-small)" in account
    assert "border-radius:var(--radius-control)" in account
    assert "border-radius:999px" not in account
    assert re.search(
        r"\.account-card\{[^}]*border-radius:var\(--radius-large\)", account
    )
    assert re.search(
        r"\.account-review\{[^}]*border-radius:var\(--radius-large\)", account
    )
    assert re.search(
        r"\.account-legal\{[^}]*border-radius:var\(--radius-large\)", account
    )
    assert re.search(
        r"\.application-card\{[^}]*border-radius:var\(--radius-small\)", account
    )
    assert re.search(
        r"\.legacy-card\{[^}]*border-radius:var\(--radius-small\)", account
    )
    assert re.search(
        r"\.legal-card\{[^}]*border-radius:var\(--radius-small\)", account
    )
    assert re.search(
        r"\.account-open\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert re.search(
        r"\.account-state\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert re.search(
        r"\.account-contact a\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert re.search(
        r"\.legacy-link\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert re.search(
        r"\.legal-action\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert re.search(
        r"\.application-icon\{[^}]*border-radius:var\(--radius-control\)", account
    )
    assert "@media(max-width:760px){#account-app{font-size:17px}" in account
    assert ".account-session{font-size:15px}" in account
    assert ".account-kicker,.account-state{font-size:13px}" in account
    assert ".account-card p,.account-legal>p{font-size:17px}" in account
    assert ".account-open,.account-contact a,.legacy-link{font-size:15px}" in account
    assert ".application-card h3{font-size:18px}" in account
    assert ".application-card p,.legacy-card p,.legal-error{font-size:15px}" in account

    course = client.get("/apps/masterclass-course.html").text
    assert ":root{--text-xs:13px;--text-sm:14px;--text-base:17px;--text-lead:18px}" in course
    assert ".hero h1{font-size:38px}" in course
    assert ".article h1{font-size:38px}" in course
    assert "font-size:12px;white-space:nowrap" in course

    loader = client.get("/embed.js").text
    load_function = loader[loader.index("function load(mount)") : loader.index("function start(mounts)")]
    assert "ensureAppShellStylesheet();" in load_function
    assert "'/assets/app-shell.css'" in loader
    assert "location.hostname === 'app.edabalans.ru' ? PUBLIC_ACCOUNT_URL : '/lk'" in loader
    assert "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/lk" in loader
    assert "var(--ed-app-line,#e7e7ef)" in loader
    assert "var(--ed-app-muted,#7b8094)" in loader

    fragments = {
        app_code: client.get(f"/apps/{app_code}.html").text
        for app_code in ("dqs", "strength", "recipes", "metabolism")
    }
    for fragment in fragments.values():
        assert "accountUrl" in fragment
        assert "'/lk'" in fragment
        assert "openmembersbar" not in fragment
        assert "<footer" not in fragment
        assert "data-edabalans-legal-footer" not in fragment
        assert "--ed-app-" in fragment

    assert "--ed-app-radius," not in fragments["strength"]
    assert "--ed-app-radius," not in fragments["recipes"]
    assert "--ed-app-radius-large" in fragments["strength"]
    assert "--ed-app-radius-large" in fragments["recipes"]
    assert "border-radius:var(--ed-app-radius-control,8px)" in fragments["strength"]
    assert "border-radius:var(--ed-app-radius-control,8px)" in fragments["recipes"]

    for app_code in ("strength", "recipes", "metabolism"):
        assert re.search(r'class=["\'][^"\']*footer', fragments[app_code], re.IGNORECASE) is None
        assert "©" not in fragments[app_code]

    assert 'href="${escapeHtml(ACCOUNT_URL)}"' in fragments["dqs"]
    assert re.search(r'dqs-profile-link ed-app-account-link[^>]*>\s*<svg', fragments["dqs"])
    assert "href=\"'+esc(ACCOUNT_URL)+'\"" in fragments["strength"]
    assert re.search(r'st-profile ed-app-account-link[^>]*>\s*[^<]*<svg', fragments["strength"])
    assert "root.querySelector('.open-account').onclick=function(){location.href=accountUrl}" in fragments["recipes"]
    assert "mask:url(" in fragments["recipes"]
    metabolism = fragments["metabolism"]
    assert "href=\"'+escapeAttr(accountUrl)+'\"" in metabolism
    assert "ed-app-account-link" in metabolism
    assert re.search(r'ed-app-account-link[^>]*>[^<]*\'\+\s*\'<svg', metabolism)
    assert "mc-footer" not in metabolism
    assert "Сергей Воронцов" not in metabolism


def test_production_admin_assets_do_not_name_legacy_storage() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    for asset in ("admin.js", "crm.js"):
        lowered = (static_dir / asset).read_text(encoding="utf-8").lower()
        assert "google" not in lowered
        assert "apps script" not in lowered


def test_unknown_application_fragment_is_404() -> None:
    assert client.get("/apps/unknown.html").status_code == 404


def test_shared_content_gallery_asset_is_public_without_captions() -> None:
    response = client.get("/assets/content-gallery.js")

    assert response.status_code == 200
    assert "window.EdabalansContentGallery" in response.text
    assert "eb-content-gallery__lightbox" in response.text
    assert "flex:0 0 85%" in response.text
    assert "max-height:90vh" in response.text
    assert "max-width:85vw" in response.text
    assert "overflow-x:auto" in response.text
    assert "Листайте → " in response.text
    assert "scrollToImage" in response.text
    assert "figcaption" not in response.text


def test_masterclass_fragments_and_shared_assets_are_public() -> None:
    account = client.get("/apps/account.html")
    assert account.status_code == 200
    assert 'id="account-app"' in account.text
    assert "function openRequestedCourse" in account.text
    assert "params.has('course_day')||params.has('course_material')" in account.text
    assert "url.searchParams.delete('course_day')" in account.text
    assert "url.searchParams.delete('course_material')" in account.text
    assert "if(openRequestedCourse(data))return" in account.text
    assert "/api/account" in account.text
    assert 'data-edabalans-app="' in account.text
    assert "data-offer-product" in account.text
    assert "/api/masterclass/account-offers" in account.text
    assert ".account-card.available-card" in account.text
    assert ".account-card.featured" in account.text
    assert "item.product_code==='consultation'?' featured'" in account.text
    assert "<article class=\"account-card'+cardCls+'\">" in account.text
    assert "function legalSummary" in account.text
    assert "legal-paragraph" in account.text
    assert "+legalSummary(item.summary)+" in account.text
    assert "String(value||'').split(/\\n\\s*\\n/).map" in account.text
    for app_code in ("onboarding-questionnaire", "masterclass-offers", "recipes-part-1", "recipes-part-2", "closing-review"):
        response = client.get(f"/apps/{app_code}.html")
        assert response.status_code == 200
        assert f'id="{app_code}-app"' in response.text
        assert "masterclass.js" in response.text
    offers_js = client.get("/assets/masterclass.js")
    offers_css = client.get("/assets/masterclass.css")
    assert offers_js.status_code == 200
    assert offers_css.status_code == 200
    assert "o.code==='single:consultation'?' is-featured':''" in offers_js.text
    assert ".mc-offer-card.is-featured" in offers_css.text
    assert client.get("/assets/max-logo.png").status_code == 200
    course = client.get("/apps/masterclass-course.html")
    assert course.status_code == 200
    assert 'id="masterclass-course-app"' in course.text
    assert "api/masterclass/course" in course.text
    assert "step.kind==='questionnaire'||step.kind==='closing-review'" in course.text
    assert "step.questionnaireKind||'onboarding'" in course.text
    assert "А какая у вас сейчас «диета»?" in course.text
    assert "После заполнения обязательно нажмите «Отправить в Telegram и продолжить»" in course.text
    assert "Получить саморевью в Telegram" in course.text
    assert "Как проходит консультация" in course.text
    assert "Эта анкета нужна не только перед консультацией" in course.text
    assert "id=\"q-later\"" not in course.text
    assert "Как отвечать" not in course.text
    assert "materialMetaHtml" in course.text
    assert "function openCourseStep" in course.text
    assert "function advanceCourseStep" in course.text
    assert "function renderCourseRoute" in course.text
    assert "remote.can_open&&!remote.opened" in course.text
    assert "Direct course day open failed" in course.text
    assert "advanceCourseStep(d,currentStep,true)" in course.text
    assert "advanceCourseStep(days[state.day-1],currentStep,false)" in course.text
    assert "saveQuestionnaire('submit')" in course.text
    assert "openEmbeddedApp('onboarding-questionnaire'" not in course.text
    assert "disposeInlineMaterial();advanceCourseStep" in course.text
    assert "К заданиям ↓" in course.text
    assert 'id="mc-skip"' not in client.get("/assets/masterclass.js").text
    masterclass_asset = client.get("/assets/masterclass.js").text
    assert "Получить саморевью в Telegram" in masterclass_asset
    assert "Сергей получит уведомление" not in masterclass_asset
    assert "item.status==='soon'||!item.openable" in masterclass_asset
    assert 'class="mc-recipe-item soon" aria-disabled="true"' in masterclass_asset
    assert "<strong>Скоро</strong>" in masterclass_asset
    assert "itemCards(d.items)" in masterclass_asset
    loader = client.get("/embed.js").text
    assert "data-edabalans-placement" in loader
    assert "data-edabalans-placement-token" in loader
    assert "onboarding-questionnaire" in loader
    assert "tma__getProfileObjFromLS" in loader
    assert "function ensureTildaProfileReader" in loader
    assert "https://members.tildaapi.com/frontend/js/tilda-members-init.min.js" in loader
    assert loader.index("ensureTildaProfileReader().then") < loader.index(
        "var detected = detectTildaMemberEmail();",
        loader.index("function boot"),
    )
    assert "detectTildaMemberEmail" in loader
    assert "waitForTildaEmail" in loader
    assert "redirectToTildaLogin" in loader
    assert "location.replace('/members/login')" in loader
    assert "edabalans_return_path_v1" in loader
    assert "restoreReturnPath" in loader
    assert "returnPath.indexOf('://')" in loader
    assert "askIdentity" not in loader
    assert "Не удалось автоматически определить email" not in loader
    assert "Введите email, на который оформлена покупка" not in loader
    assert "remember(detected)" in loader
    assert "masterclass-course" in loader
    assert "hideTildaUserbar" in loader
    assert "data-edabalans-account-url" in loader
    assert "data-edabalans-account-offer" in loader
    assert "focusProductCode" in loader
    assert "source: 'tilda'" in loader
    account = client.get("/apps/account.html").text
    assert (
        '<h1>Личный кабинет</h1><p class="account-session">'
        '<strong class="account-session-email">'
    ) in account
    assert "Вы вошли как" not in account
    assert 'class="account-logout" href="/members/login?exit=y">Выйти</a>' in account
    assert "Курсы и программы" in account
    assert "Приложения" in account
    assert "Курсы, программы и приложения собраны в одном месте." not in account
    assert "Доступные вам материалы можно открыть сразу." not in account
    assert "Ваша программа откроется здесь после покупки или подтверждения прежнего доступа." not in account
    assert "Чтобы худеть было проще." not in account
    assert "Рабочие инструменты — компактно, без отдельного входа." not in account
    assert (
        '<section class="account-legal"><p>Чтобы пользоваться личным кабинетом, '
        'прочитайте дисклеймер и политику обработки персональных данных.</p><div class="legal-grid">'
    ) in account
    assert "Пара важных вещей" not in account
    assert "Полные тексты можно открыть" not in account
    assert ">Принять и продолжить</button>" in account
    assert ">Принимаю и продолжаю</button>" not in account
    assert ".legal-copy>strong,.legal-copy>span{display:block}" in account
    assert ".legal-copy>.legal-paragraph+.legal-paragraph{margin-top:12px}" in account
    assert "function accountSession" not in account
    application_renderer = account[
        account.index("function applicationCard") : account.index("function legacyPortal")
    ]
    assert "account-state" not in application_renderer
    assert (
        "action=canOpen?'<button class=\"account-open available\" data-app=\"'+esc(item.app)"
        "+'\">Открыть</button>':'<button class=\"account-open\" disabled>'+esc(label)+'</button>'"
        in application_renderer
    )
    assert "applicationIcon(item.code)" in application_renderer
    assert "application-icon-" in account
    icons = dict(re.findall(r"(dqs|strength|recipes|metabolism):'([^']+)'", account))
    assert set(icons) == {"dqs", "strength", "recipes", "metabolism"}
    assert len(set(icons.values())) == 4
    assert "item.ready?(item.owned?'Открыть':'Доступ закрыт'):'Скоро'" in account
    course_renderer = account[account.index("function card") : account.index("function applicationIcon")]
    assert "label=item.ready?(item.owned?'Доступ открыт':'Доступ закрыт'):'Скоро'" in course_renderer
    assert "item.ready?'Доступ закрыт':'Скоро'" in course_renderer
    assert "'В разработке'" not in account
    assert "'Куплен, готовится'" not in account
    assert "'Программа готовится к открытию'" not in account
    account_button_rules = re.search(r"\.account-open\{(?P<rules>[^}]*)\}", account)
    assert account_button_rules is not None
    assert "white-space:nowrap" in account_button_rules.group("rules")
    assert "Система оценки качества питания" not in account  # names come from the server catalog
    assert "Старый личный кабинет" in account
    assert "Пока доступы не подключены" in account
    assert "data.state!=='ready'" in account
    assert "tma__userbar__sendLogout" in account
    assert "/members/login?exit=y" in account
    assert "identity.source==='tilda'" in course.text
    assert "function authHeaders()" in course.text
    assert "Мастер-класс по изменению питания и пищевых привычек" in course.text
    assert ".tlk-userbar{display:none!important}" in course.text
    assert "Темы видны заранее" not in course.text
    legal_index = client.get("/legal/index.html")
    assert legal_index.status_code == 200
    assert "/legal/disclaimer" in legal_index.text
    assert "/legal/privacy" in legal_index.text
    assert "/legal/consent" in legal_index.text
    assert "/legal/messages" in legal_index.text
    assert "/legal/offer" in legal_index.text
    assert client.get("/legal/disclaimer.html").status_code == 200
    assert client.get("/legal/privacy.html").status_code == 200
    assert client.get("/legal/consent.html").status_code == 200
    assert client.get("/legal/messages.html").status_code == 200
    assert client.get("/legal/offer.html").status_code == 200
    assert client.get("/legal/legal.css").status_code == 200
    assert client.get("/legal/unknown.html").status_code == 404
    privacy = client.get("/legal/privacy.html").text
    assert privacy.index("Связанные документы") < privacy.index("Коротко:")
    assert "Согласие на получение информационных и рекламных сообщений" in privacy
    assert "«Старт» или «START»" in privacy
    assert "/stop прекращает все сообщения" in privacy
    assert "https://похудение-это-есть.рф/lk" in privacy
    assert "платёжная система «Робокасса»" in privacy
    assert "Telegram, MAX, сервис электронной почты" not in privacy
    assert "Редакция от" not in privacy
    consent = client.get("/legal/consent.html").text
    assert "отдельное согласие" in consent.lower()
    assert "не разрешает публично размещать отзыв" in consent
    offer = client.get("/legal/offer.html").text
    assert "не менее 90 календарных дней с даты оплаты" in offer
    assert "проходит программу медленнее" not in offer
    assert "не менее 50% предусмотренных заданий" in offer
    disclaimer = client.get("/legal/disclaimer.html").text
    assert "не является врачом или иным медицинским работником" in disclaimer
    assert "Сергей Воронцов — нутрициолог" not in disclaimer
    assert "населения различных возрастных групп" in disclaimer
    assert "инструкторской и методической работе" in disclaimer
    assert "342419695163" in disclaimer
    assert "регистрационный номер 1092" in disclaimer
    assert "№ 237н" in disclaimer
    assert "№ 273-ФЗ" in disclaimer
    assert "Пользователь отвечает за достоверность" not in disclaimer
    assert "https://go.похудение-это-есть.рф/legal/disclaimer" in loader
    masterclass = client.get("/assets/masterclass.js").text
    assert "Authorization='Bearer '" in masterclass
    assert "placement_token" in masterclass
    assert "function watchPurchase" in masterclass
    assert "setInterval(check,5000)" in masterclass
    assert "if(!still)" in masterclass


def test_masterclass_first_day_article_and_image_layout_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    first_day = manifest["days"][0]
    first_steps = first_day["steps"]

    assert first_steps[0]["id"] == "day-01-article-tutorial"
    assert first_steps[0]["contentKind"] == "text"
    assert all(step.get("title") != "Программа Мастер-класса" for step in first_steps)
    assert [
        step["title"] for step in first_steps if step.get("kind") == "article"
    ] == [
        "Как пользоваться Мастер-классом",
        "Как вести дневник питания",
        "Как надо взвешиваться",
    ]
    assert next(
        index for index, step in enumerate(first_steps)
        if step["id"] == "day-01-messenger-link"
    ) > next(
        index for index, step in enumerate(first_steps)
        if step["id"] == "day-01-questionnaire"
    )
    messenger_step = next(
        step for step in first_steps if step["id"] == "day-01-messenger-link"
    )
    assert "уведомления о новых материалах" in messenger_step["summary"]

    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")
    assert ".article p:not(.eyebrow):not(.hero-lead):not(.eyebrow-time){margin:0 0 18px}" in course_html
    assert "обязательный технический шаг" in course_html
    assert "После успешной привязки появится кнопка «Продолжить»" in course_html
    assert "messenger-links/status" in course_html
    assert "if(messengerConfirmed)advanceCourseStep" in course_html
    assert "Персональная ссылка для подключения действует 15 минут" not in course_html
    assert "var next=nextVisibleStep(d,step)" in course_html
    assert "if(next>=0)openCourseStep(d,next)" in course_html
    assert "if(!step.hidden&&step.contentAsset)" in course_html
    assert "return!step.hidden&&['messenger','offer']" in course_html
    assert "day.shortTitle||day.title" not in course_html
    assert "return day.tocSummary||generated" in course_html
    assert "esc(nextDay.title)" in course_html
    assert "d.nextTeaser" not in course_html
    assert "d.assignmentLead" not in course_html
    assert "d.assignmentText" not in course_html
    assert "d.kicker" not in course_html
    assert "afterLead" in course_html
    assert "esc(t.title)" in course_html
    assert "esc(t.summary)" in course_html
    assert "pages[step.contentPageTitle||step.title]" in course_html
    assert "videoId:step.videoId,image:step.image" in course_html
    assert "materialMedia(t)+body" in course_html
    day_four_dqs = manifest["days"][3]["steps"][1]
    assert day_four_dqs["id"] == "day-04-dqs"
    assert day_four_dqs["kind"] == "dqs"
    assert day_four_dqs["contentAsset"] == "19-dqs-access-and-print-options.md"
    assert "openDqsMaterial" in course_html
    assert "if(step.kind==='dqs'&&step.contentAsset){openDqsMaterial(d,stepIndex);return}" in course_html
    assert "else if(d.steps[stepIndex].kind==='dqs'&&d.steps[stepIndex].contentAsset){openDqsMaterial(d,stepIndex)}" in course_html
    assert "dqsTutorialRequested=true;openDqsApplication(d,stepIndex);return" in course_html
    assert "dqs/link-to-telegram" in course_html
    assert "dqs-material-actions" in course_html
    assert "DQS_for_print.png" in course_html
    assert "mobile-article-toc-button" in course_html
    assert "article-toc-button" in course_html
    assert "Содержание" in course_html
    assert "querySelectorAll('#article h2')" in course_html
    assert "articleTocHeadings.length<3" in course_html
    assert "event.key==='Escape'" in course_html
    assert "aria-current','location'" in course_html
    assert "configureArticleToc();document.querySelector('#prev')" in course_html
    assert "target.focus({preventScroll:true})" in course_html
    assert "event.target.closest('#mobile-article-toc-popover')" in course_html
    assert "atPageEnd=window.innerHeight+window.scrollY" in course_html
    assert (
        "articleTocHeadings[0].textContent.trim().toLocaleLowerCase('ru-RU')===titleText)"
        "articleTocHeadings.shift()"
    ) in course_html
    assert (
        '.article-toc-popover a::before,.mobile-article-toc-popover a::before'
        '{content:"•"'
    ) in course_html
    assert (
        ".article-toc-popover a:hover,.mobile-article-toc-popover a:hover"
        "{background:#f0ebe2;color:var(--ink)}"
    ) in course_html

    static_dir = root / "backend" / "app" / "static"
    editor_html = (static_dir / "course-structure-editor.html").read_text(encoding="utf-8")
    editor_js = (static_dir / "course-structure-editor.js").read_text(encoding="utf-8")
    assert "Сохранить и применить" in editor_html
    assert "Добавить материал" not in editor_html + editor_js
    assert "Лозунг дня" not in editor_js
    assert "Короткое название" not in editor_js
    assert "Файл материала" not in editor_js
    assert "Системный шаг" not in editor_js
    assert "Добавление, удаление и перестановка" not in editor_js
    assert "ID: " in editor_js

    fourth_day = manifest["days"][3]
    dqs_step = next(step for step in fourth_day["steps"] if step["kind"] == "dqs")
    assert dqs_step["completion"] == "tutorial_completed"
    assert "event.detail.completion!=='tutorial'" in course_html
    assert "markStep(d,currentStep).catch(showActionError)" in course_html
    assert "document.querySelectorAll('[data-dqs-tutorial-link]')" in course_html
    assert "openRequestedDqsTutorial(window)" in course_html

    dqs_html = (
        root / "backend" / "app" / "static" / "apps" / "dqs.html"
    ).read_text(encoding="utf-8")
    assert "action:'completeTutorial'" in dqs_html
    assert "completion:'tutorial'" in dqs_html
    assert "window.EdabalansDqsOpenTutorial" in dqs_html

    gallery_steps = [
        (day["number"], step["id"])
        for day in manifest["days"]
        for step in day.get("steps", [])
        if step.get("imagePresentation") == "gallery"
    ]
    assert gallery_steps == [(4, "day-04-article-01")]

    dqs_source = (root / "content" / "masterclass" / "source-current" / "13-dqs-system.txt").read_text(encoding="utf-8")
    assert [f"[[DQS_MATRIX:{kind}]]" for kind in ["all", "plants", "proteins", "fats", "garnishes", "harmful"]] == [
        marker for marker in dqs_source.splitlines() if marker.startswith("[[DQS_MATRIX:")
    ]
    assert "[[GALLERY:dqs-home]]" in dqs_source
    assert "[[GALLERY:dqs-takeout]]" in dqs_source
    assert "Код будет выполнен на опубликованной странице" not in dqs_source
    assert "XXXXXXXXXXXXXXXXXXXX" not in dqs_source
    assert dqs_source.count("[[DQS_MATRIX:") == 6
    assert dqs_source.count("[[GALLERY:") == 2
    assert (
        dqs_source.count("> **Стандартная порция:")
        + dqs_source.count("> **Стандартные порции:")
    ) == 12
    assert all(
        heading in dqs_source
        for heading in (
            "## → Фрукты и Овощи",
            "## → Мясо, птица, рыба, яйца и морепродукты",
            "## → Масло и другие добавленные жиры",
            "## → Цельные злаки",
            "## Переходим к вредным категориям!",
            "## Шпаргалка по порциям",
            "## Примеры",
        )
    )

    course = client.get("/apps/masterclass-course.html").text
    assert course.count("<style>") == 1
    assert 'src="/assets/content-gallery.js?v=source-slider"' in course
    assert "renderContentEmbeds" in course
    assert ".replace(/\\*([^*]+)\\*/g,'<em>$1</em>')" in course
    assert "function endQuote()" in course
    assert ".dqs-matrix-grid{display:grid" in course
    assert 'id="course-tutorial"' in course
    tutorial = course[course.index("function tutorialPreview"):course.index("function openTutorial")]
    slides = tutorial[tutorial.index("function tutorialSlides"):tutorial.index("function renderTutorial")]
    assert "grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr)" in course
    assert "height:100dvh" in course
    assert slides.count("{title:") == 5
    assert all(label in slides for label in ("Галочка", "стрелка", "замок"))
    assert "прогресс сохранится автоматически" in slides
    assert "contacts" not in tutorial.lower()
    assert "серге" not in tutorial.lower()
    assert "card.scrollTop=0" in tutorial
    assert "tutorialStep++;renderTutorial()" in course
    assert "tutorialStep--;renderTutorial()" in course
    assert "splitArticleHtml(t.rich_html,t.imagePresentation==='gallery')" in course
    assert "DQS_CATEGORY_ROWS" in course
    assert "COURSE_CONTENT_CACHE_VERSION='20260826-dqs-article'" in course
    assert "overflow-wrap:anywhere" in course
    assert "renderContentEmbeds(parts.body)" in course
    assert "window.EdabalansContentGallery.bind(article)" in course


def test_masterclass_second_day_contains_current_diet_questionnaire() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    step = manifest["days"][1]["steps"][2]
    assert step["id"] == "day-02-current-diet"
    assert step["kind"] == "questionnaire"
    assert step["questionnaireKind"] == "current-diet"
    assert step["label"] == "А какая у вас сейчас «диета»?"
    assert step["summary"] == (
        "Заполните небольшой опросник о ваших отношениях с разными "
        "продуктовыми категориями."
    )


def test_masterclass_day_three_order_and_cards_have_no_editorial_markers() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    assert [step["id"] for step in manifest["days"][2]["steps"]] == [
        "day-03-video-01",
        "day-03-article-02",
        "day-03-article-03",
    ]
    assert [step.get("contentAsset") for step in manifest["days"][2]["steps"]] == [
        "06-necessary-restrictions.txt",
        "08-whole-processed-ultraprocessed-food.txt",
        "07-reading-labels.txt",
    ]

    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")
    assert "Нужна редактура" not in course_html
    assert "Черновик · требуется редактура" not in course_html
    assert "draft-badge" not in course_html
    assert ".topic.draft" not in course_html


def test_emotional_hunger_guide_is_visible_but_temporarily_locked() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    guide = next(
        step
        for step in manifest["days"][8]["steps"]
        if step["id"] == "day-09-article-01"
    )
    assert guide["hidden"] is False
    assert guide["locked"] is True
    assert guide["badge"] == "Скоро"

    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")
    assert "function stepNavigable(d,i)" in course_html
    assert "!d.steps[i].locked" in course_html
    assert "step&&step.locked?(step.badge||'Скоро')" in course_html
    assert "topic-badge" in course_html


def test_masterclass_plain_images_have_no_caption_or_decorative_container() -> None:
    root = Path(__file__).resolve().parents[2]
    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")

    assert '<img class="day-media-image"' in course_html
    assert '<div class="media image"' not in course_html
    assert 'class="caption"' not in course_html
    assert ".media.image" not in course_html
    assert "box.querySelectorAll('figcaption')" in course_html
    assert "img.classList.add('article-inline-image')" in course_html


def test_masterclass_manifest_is_the_complete_canonical_program() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = normalize_seed(json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    ))

    assert manifest["schemaVersion"] == 2
    assert manifest["status"] == "current_runtime_manifest"
    assert [day["number"] for day in manifest["days"]] == list(range(1, 22))

    required_day_fields = {
        "title", "tocSummary", "lead", "media", "videoId", "image", "intro",
        "afterTitle", "afterText", "checks", "steps",
        "implementation", "publicationStatus",
    }
    step_ids: list[str] = []
    for day in manifest["days"]:
        assert required_day_fields <= day.keys(), day["number"]
        assert day["media"] in {"video", "image", "none"}
        assert day["checks"]
        for step in day["steps"]:
            assert step.get("id")
            assert step.get("kind")
            assert step.get("summary")
            step_ids.append(step["id"])
    assert len(step_ids) == len(set(step_ids))

    assert [
        step["title"] for step in manifest["days"][5]["steps"] if step["kind"] == "article"
    ] == [
        "Опорные точки в питании", "Эволюция рецепта на примере овсянки",
        "Как сделать еду вкусной", "Почему рецепт с первого раза может быть не вашим",
    ]
    assert manifest["days"][6]["steps"][2]["items"] == [
        "Как устроена база рецептов и как пользоваться каталогом",
        {
            "title": "Как выбирать готовую еду в магазинах и доставках",
            "status": "soon",
            "openable": False,
            "required": False,
        },
        "Разбор БЖУ",
        "Первая партия рецептов",
    ]
    assert [
        step["title"] for step in manifest["days"][17]["steps"]
        if not step.get("hidden", False)
    ] == [
        "Для тех, кто любит подглядывать",
    ]
    assert [
        step["title"] for step in manifest["days"][20]["steps"]
        if step["kind"] == "article"
    ] == [
        "Фазы и периодизация похудения",
    ]

    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")
    assert "d.steps[i].required!==false" in course_html
    assert "var video=String(d.videoId||'').trim()" in course_html


def test_masterclass_media_uses_present_links_and_player_route() -> None:
    course_html = client.get("/apps/masterclass-course.html").text
    assert "function directMp4(value)" in course_html
    assert "'/apps/video-player.html?src='" in course_html
    assert "'&chapters='+encodeURIComponent(JSON.stringify(d.timings))" in course_html
    assert "directMp4(String(d.videoId||''))?'':timingBlock(d)" in course_html
    assert "TBbi2ibz" not in course_html

    player = client.get("/apps/video-player.html")
    assert player.status_code == 200
    assert "runtimeParams.get('src')" in player.text
    assert "CONTENTS_ENABLED = !runtimeParams.has('src') || runtimeChapters.length > 0" in player.text
    assert "runtimeParams.get('chapters')" in player.text
    assert "video.poster = poster" in player.text


def test_legal_friendly_routes_are_public() -> None:
    assert client.get("/legal").status_code == 200
    assert client.get("/legal/").status_code == 200
    assert client.get("/legal/disclaimer").status_code == 200
    assert client.get("/legal/privacy").status_code == 200
    assert client.get("/legal/consent").status_code == 200
    assert client.get("/legal/messages").status_code == 200
    assert client.get("/legal/offer").status_code == 200
    assert client.get("/legal/legal.css").status_code == 200
    assert client.get("/legal/unknown").status_code == 404


def test_intensive_concept_pages_are_public() -> None:
    expected_titles = {
        "day-1": "Сначала увидьте своё питание",
        "day-2": "Сделайте дефицит легче",
        "day-3": "Калории и реальность похудения",
        "day-4": "Полная карта похудения",
    }
    for day_code, title in expected_titles.items():
        friendly = client.get(f"/intensive/{day_code}")
        html = client.get(f"/intensive/{day_code}.html")
        assert friendly.status_code == 200
        assert html.status_code == 200
        assert html.text == friendly.text
        assert title in friendly.text
        assert 'id="intensive-content"' in friendly.text
        assert 'id="intensive-edit"' in friendly.text
        assert ">Edit</button>" in friendly.text
        assert "Текст для видео" in friendly.text
        assert "Что нужно дописать" in friendly.text or "Что нужно дописать и обновить" in friendly.text
        assert "Короткий текст под видео" in friendly.text
        assert "/intensiv/tpost/" in friendly.text
        assert "Переход к Мастер-классу" in friendly.text
        assert "utm_source=free_intensive" in friendly.text
        assert "/legal/disclaimer" in friendly.text
        assert "video-script" not in friendly.text
        assert "cards" not in friendly.text
        assert "callout" not in friendly.text
    stylesheet = client.get("/intensive/intensive.css")
    assert stylesheet.status_code == 200
    assert ".edit-button" in stylesheet.text
    assert ".cards" not in stylesheet.text
    script = client.get("/intensive/intensive.js")
    assert script.status_code == 200
    assert "contentEditable" in script.text
    assert "localStorage" not in script.text
    assert "/admin/api/intensive/" in script.text
    assert client.get("/intensive/day-5").status_code == 404
    assert client.get("/intensive/day-5.html").status_code == 404


def test_removed_video_player_preview_routes_are_unavailable() -> None:
    assert client.get("/video-player-preview").status_code == 404
    assert client.get("/assets/video-player.css").status_code == 404
    assert client.get("/assets/video-player.js").status_code == 404


def test_masterclass_sales_fragment_uses_server_price_codes() -> None:
    response = client.get("/apps/masterclass-sales.html")
    assert response.status_code == 200
    assert 'id="masterclass-sales-app"' in response.text
    assert "/api/pricing/site" in response.text
    assert "/api/pricing/site/checkout" in response.text
    assert "data-price-code=\"'+esc(tariff.code)+'\"" in response.text
    assert "data-buy=\"'+esc(tariff.code)+'\"" in response.text
    assert "location.hash=result.cart_command" in response.text
    loader = client.get("/embed.js").text
    assert "'masterclass-sales': 'masterclass-sales-app'" in loader


def test_dqs_notifies_course_only_after_server_save() -> None:
    response = client.get("/apps/dqs.html")
    rules = client.get("/apps/dqs-category-rules.js")

    assert response.status_code == 200
    assert rules.status_code == 200
    assert "EdabalansDqsCategoryRows" in rules.text
    assert "'edabalans:app-completed'" in response.text
    assert "app:'dqs'" in response.text


def test_tilda_origin_is_allowed_for_api_preflight() -> None:
    response = client.options(
        "/api/apps/metabolism",
        headers={
            "Origin": "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_strength_new_user_can_start_and_manage_own_workouts() -> None:
    response = client.get("/apps/strength.html")
    text = response.text.replace("\r\n", "\n")

    assert response.status_code == 200
    assert "Создать первую тренировку" in text
    assert "if(!app.isAdmin){\n      return;\n    }\n\n    var catalog =\n      activeCatalog();" not in text
    assert "body.email =\n      app.email;" in text
