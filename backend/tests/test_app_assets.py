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


client = TestClient(app)


def test_stable_embed_loader_is_public() -> None:
    response = client.get("/embed.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "data-edabalans-app" in response.text


def test_course_footer_contract_is_shared_and_minimal() -> None:
    loader = client.get("/embed.js").text
    assert "data-edabalans-legal-footer" in loader
    assert "data-edabalans-footer-owner" in loader
    assert "mount.parentElement.closest('[data-edabalans-footer-owner]')" in loader
    assert "ensureLegalFooter(mount);" in loader
    footer = loader[loader.index("function legalFooterHtml"):loader.index("function ensureLegalFooter")]
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

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "data-edabalans-site-footer" in response.text
    assert "new Date().getFullYear()" in response.text
    assert "ИП Воронцов Сергей Сергеевич" in response.text
    assert "ИНН 230409966750" in response.text
    assert "Все права защищены" in response.text
    assert "Копирование материалов запрещено" in response.text
    assert "root.innerHTML = markup(index)" in response.text
    assert "roots.forEach(mount)" in response.text
    assert "document.addEventListener('DOMContentLoaded', boot)" in response.text
    close_all = re.search(
        r"    function closeAll\(\) \{\n(?P<body>.*?)\n    \}\n\n    buttons\.forEach",
        response.text,
        re.DOTALL,
    )
    assert close_all is not None
    assert "item.setAttribute('aria-expanded', 'false')" in close_all.group("body")
    assert "item.hidden = false" in close_all.group("body")
    assert "item.hidden = true" in close_all.group("body")
    assert "panel.hidden = false" in response.text
    click_handler = re.search(
        r"button\.addEventListener\('click', function \(\) \{(?P<body>.*?)\n\s*\}\);",
        response.text,
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
    assert "Пока недоступно" in response.text
    assert "optionLink(LINKS.telegramChannel, 'Telegram-канал')" in response.text
    assert "optionLink(LINKS.telegram, 'Написать в Telegram')" in response.text
    assert "optionLink(LINKS.max, 'Написать в MAX')" in response.text
    assert "MAX-канал" in response.text
    assert "В разработке" in response.text
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


def test_production_admin_assets_do_not_name_legacy_storage() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    for asset in ("admin.js", "crm.js"):
        lowered = (static_dir / asset).read_text(encoding="utf-8").lower()
        assert "google" not in lowered
        assert "apps script" not in lowered


def test_unknown_application_fragment_is_404() -> None:
    assert client.get("/apps/unknown.html").status_code == 404


def test_masterclass_fragments_and_shared_assets_are_public() -> None:
    account = client.get("/apps/account.html")
    assert account.status_code == 200
    assert 'id="account-app"' in account.text
    assert "/api/account" in account.text
    assert 'data-edabalans-app="' in account.text
    for app_code in ("onboarding-questionnaire", "masterclass-offers", "recipes-part-1", "recipes-part-2", "closing-review"):
        response = client.get(f"/apps/{app_code}.html")
        assert response.status_code == 200
        assert f'id="{app_code}-app"' in response.text
        assert "masterclass.js" in response.text
    assert client.get("/assets/masterclass.js").status_code == 200
    assert client.get("/assets/masterclass.css").status_code == 200
    assert client.get("/assets/max-logo.png").status_code == 200
    course = client.get("/apps/masterclass-course.html")
    assert course.status_code == 200
    assert 'id="masterclass-course-app"' in course.text
    assert "api/masterclass/course" in course.text
    assert "code==='dqs'||code==='closing-review'" in course.text
    loader = client.get("/embed.js").text
    assert "data-edabalans-placement" in loader
    assert "data-edabalans-placement-token" in loader
    assert "onboarding-questionnaire" in loader
    assert "tildaIdentityRequired" in loader
    assert "tma__getProfileObjFromLS" in loader
    assert "detectTildaMemberEmail" in loader
    assert "waitForTildaEmail" in loader
    assert "protectedApps ? detectTildaMemberEmail() : detectTildaEmail()" in loader
    assert "remembered.source === 'tilda'" not in loader
    assert "remember(detected, '', 0, 'tilda')" in loader
    assert "Откройте приложение из личного кабинета" in loader
    assert "masterclass-course" in loader
    assert "'account': true" in loader
    assert "hideTildaUserbar" in loader
    assert "data-edabalans-account-url" in loader
    assert "source: identitySource" in loader
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


def test_masterclass_first_day_tutorial_and_image_layout_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    first_day = manifest["days"][0]
    first_steps = first_day["steps"]

    assert first_steps[0]["id"] == "day-01-article-tutorial"
    assert first_steps[0]["contentKind"] == "tutorial"
    assert all(step.get("title") != "Программа Мастер-класса" for step in first_steps)
    assert [
        step["title"] for step in first_steps if step.get("kind") == "article"
    ] == [
        "Как пользоваться Мастер-классом",
        "Как вести дневник питания",
        "Как необходимо взвешиваться",
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
    assert "уведомления об обновлениях" in messenger_step["summary"]

    course_html = (
        root / "backend" / "app" / "static" / "masterclass-first-days-preview.html"
    ).read_text(encoding="utf-8")
    assert "напоминания по Мастер-классу и другим вашим программам" in course_html
    assert "Старая рассылка с предложением купить Мастер-класс отключится" in course_html
    assert "отправьте боту <code>/stop</code>" in course_html
    assert "Персональная ссылка для подключения действует 15 минут" in course_html

    gallery_steps = [
        (day["number"], step["id"])
        for day in manifest["days"]
        for step in day.get("steps", [])
        if step.get("imagePresentation") == "gallery"
    ]
    assert gallery_steps == [(4, "day-04-article-01")]

    course = client.get("/apps/masterclass-course.html").text
    assert 'id="course-tutorial"' in course
    assert "if(!useGallery)return{body:box.innerHTML,images:images}" in course
    assert "splitArticleHtml(t.rich_html,t.imagePresentation==='gallery')" in course


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
        assert "Концептуальный каркас" in friendly.text
        assert 'class="video-script"' in friendly.text
        assert "video-placeholder" not in friendly.text
        video_script = re.search(
            r'<section class="video-script".*?</section>', friendly.text, re.DOTALL
        )
        assert video_script is not None
        assert len(re.findall(r"<p(?: [^>]*)?>.*?</p>", video_script.group(), re.DOTALL)) >= 4
        video_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", video_script.group()))
        assert len(video_text) >= 700
        assert "Нужно дописать Сергею" in friendly.text
        assert "Короткий текст под видео" in friendly.text
        bot_copy = re.search(
            r'<div class="bot-copy">(.*?)</div>', friendly.text, re.DOTALL
        )
        assert bot_copy is not None
        assert len(re.findall(r"<p>.*?</p>", bot_copy.group(), re.DOTALL)) >= 3
        bot_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bot_copy.group()))
        assert len(bot_text) >= 180
        assert "/intensiv/tpost/" in friendly.text
        assert "Как подвести к Мастер-классу" in friendly.text
        cta = re.search(r'<section class="cta">(.*?)</section>', friendly.text, re.DOTALL)
        assert cta is not None
        assert re.search(
            r'<a href="[^"]*utm_source=free_intensive[^"]*">(?=[^<]*\S)[^<]+</a>',
            cta.group(),
        )
        assert "/legal/disclaimer" in friendly.text
    stylesheet = client.get("/intensive/intensive.css")
    assert stylesheet.status_code == 200
    assert ".video-script" in stylesheet.text
    assert ".video-placeholder" not in stylesheet.text
    script = client.get("/intensive/intensive.js")
    assert script.status_code == 200
    assert "contentEditable" in script.text
    assert "localStorage.setItem" in script.text
    assert "fetch(" not in script.text
    assert client.get("/intensive/day-5").status_code == 404
    assert client.get("/intensive/day-5.html").status_code == 404


def test_masterclass_sales_fragment_uses_server_price_codes() -> None:
    response = client.get("/apps/masterclass-sales.html")
    assert response.status_code == 200
    assert 'id="masterclass-sales-app"' in response.text
    assert "/api/pricing/site" in response.text
    assert "/api/pricing/site/checkout" in response.text
    assert "site.masterclass.basic" in response.text
    assert "site.masterclass.recipes" in response.text
    assert "site.masterclass.consult" in response.text
    assert "location.hash=result.cart_command" in response.text
    loader = client.get("/embed.js").text
    assert "'masterclass-sales': 'masterclass-sales-app'" in loader


def test_dqs_notifies_course_only_after_server_save() -> None:
    response = client.get("/apps/dqs.html")

    assert response.status_code == 200
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

    assert response.status_code == 200
    assert "Создать первую тренировку" in response.text
    assert "if(!app.isAdmin){\n      return;\n    }\n\n    var catalog =\n      activeCatalog();" not in response.text
    assert "body.email =\n      app.email;" in response.text
