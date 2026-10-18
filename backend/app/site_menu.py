"""Shared public header/menu shell; each surface owns only links and outline."""
from html import escape
import re

MENU_TEMPLATE = r'''  <button class="site-menu-toggle{toggle_class}" data-site-menu-toggle type="button" aria-label="{open_label}" data-menu-label="{open_label}" aria-expanded="false" aria-controls="{menu_id}">
    <span class="site-menu-toggle__label">{label}</span><span class="site-menu-bars" aria-hidden="true"><span></span><span></span><span></span></span>
  </button>
  <aside class="site-menu-panel" data-site-menu role="dialog" aria-modal="true" aria-label="Меню сайта" id="{menu_id}" aria-hidden="true" inert>
    <a class="site-menu-brand" href="/" aria-label="Похудение — это есть.рф, главная"><img class="desktop-brand-icon" src="/preview/homepage-mobile/favicon-no-outline.png" alt=""><span>ПОХУДЕНИЕ — ЭТО ЕСТЬ.РФ</span></a>
    <nav class="site-menu-links" aria-label="Навигация">
      <div class="site-menu-quick-links">
      {quick_links}
      <div class="site-menu-disclosure">
        <button class="site-menu-disclosure-trigger" type="button" aria-expanded="false" aria-haspopup="true" aria-controls="mobile-contact-panel">Контакты</button>
        <div class="site-menu-disclosure-panel" id="mobile-contact-panel" hidden>
          <a href="https://t.me/FitnessSergey" target="_blank" rel="noopener">Написать в ЛС в Telegram</a>
          <a href="https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw" target="_blank" rel="noopener">Написать в ЛС в MAX</a>
          <a href="https://t.me/Fitness_Talks" target="_blank" rel="noopener">Telegram-канал</a>
          <a href="https://max.ru/id230409966750_biz" target="_blank" rel="noopener">Канал в MAX</a>
        </div>
      </div>
      <div class="site-menu-disclosure"><button class="site-menu-disclosure-trigger" type="button" aria-expanded="false" aria-haspopup="true" aria-controls="mobile-account-panel">Личный кабинет</button><div class="site-menu-disclosure-panel" id="mobile-account-panel" hidden><a href="/lk">Войти</a><a href="/lk?mode=register">Зарегистрироваться</a></div></div>
      </div>
      <div class="site-menu-disclosure">
        <button class="site-menu-disclosure-trigger" type="button" aria-expanded="false" aria-haspopup="true" data-site-menu-contents aria-controls="mobile-toc-panel">{outline_label}</button>
        <div class="site-menu-disclosure-panel site-menu-contents" id="mobile-toc-panel" hidden>
{outline}        </div>
      </div>
    </nav>
  </aside>'''


def render_site_menu(quick_links: str, outline: str, *, article: bool = False) -> str:
    """The two HTML fragments come from trusted page renderers, never user input."""
    label = 'Содержание' if article else 'Меню'
    return MENU_TEMPLATE.format(
        quick_links=quick_links, outline=outline,
        toggle_class=' site-menu-toggle--article toc-trigger' if article else '',
        label=escape(label), open_label=escape('Открыть содержание' if article else 'Открыть меню'),
        outline_label='Содержание статьи' if article else 'Содержание',
        menu_id='contents' if article else 'mobile-menu',
    )


def render_homepage_menu(source: str) -> str:
    return re.sub(
        r'<!-- site-menu:start -->(.*?)<!-- site-menu:outline -->(.*?)<!-- site-menu:end -->',
        lambda match: render_site_menu(match[1], match[2]), source, flags=re.S,
    )
