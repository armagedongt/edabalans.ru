from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


PROFILE_URL = "https://pikabu.ru/@armagedongt"
STORY_RE = re.compile(r"https://pikabu\.ru/story/[^?#]+_(\d+)(?:[?#].*)?$")


def ensure_private_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("collector output/profile must be outside the Git repository")
    return resolved


def save_checkpoint(
    output: Path, *, profile_url: str, discovered: int, items: list[dict], failures: list[dict]
) -> None:
    payload = {
        "source": {"platform": "pikabu", "account": "armagedongt", "profile_url": profile_url},
        "discovered": discovered,
        "items": items,
        "failures": failures,
    }
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


def discover(page: "Page", profile_url: str, *, limit: int | None) -> list[str]:
    page.goto(profile_url, wait_until="domcontentloaded")
    page.wait_for_selector("article.story")
    found: dict[str, str] = {}
    unchanged = 0
    previous = 0
    while unchanged < 8:
        for href in page.locator('article.story h2 a[href*="/story/"]').evaluate_all(
            "els => els.map(e => e.href)"
        ):
            match = STORY_RE.match(href)
            if match:
                found.setdefault(match.group(1), href.split("#", 1)[0])
        if limit and len(found) >= limit:
            break
        unchanged = unchanged + 1 if len(found) == previous else 0
        previous = len(found)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)
    rows = list(found.values())
    return rows[:limit] if limit else rows


def extract_story(page: "Page", url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("main article.story[data-page='true']")
    for _ in range(5):
        label = page.locator("main article.story .story__views").get_attribute("aria-label")
        if label and re.search(r"\d", label):
            break
        page.wait_for_timeout(400)
    return page.locator("main article.story").evaluate(
        """
        article => {
          const number = value => {
            const match = String(value || '').replace(/\\s/g, '').match(/-?\\d+/);
            return match ? Number(match[0]) : null;
          };
          const clean = value => String(value || '').replace(/\\u2060/g, '').trim();
          const ratingLabel = article.querySelector('.story__rating-count')?.getAttribute('aria-label') || '';
          const votes = ratingLabel.match(/([\\d\\s]+)\\s+плюс\\S*\\s*\\/\\s*([\\d\\s]+)\\s+минус/);
          const content = article.querySelector('.story__content-inner');
          const blocks = [...content.children].map((element, position) => ({
            position,
            type: element.tagName.toLowerCase(),
            text: clean(element.innerText || element.textContent)
          })).filter(block => block.text || block.type === 'figure');
          const decode = href => {
            try { return new URL(href).searchParams.get('u') || href; } catch { return href; }
          };
          const links = [...content.querySelectorAll('a[href]')].map((element, position) => ({
            position,
            text: clean(element.textContent),
            wrapped_url: element.href,
            target_url: decode(element.href)
          }));
          const mediaSeen = new Set();
          const media = [];
          const addMedia = (type, source_url, preview_url = null) => {
            if (!source_url || mediaSeen.has(`${type}:${source_url}`)) return;
            mediaSeen.add(`${type}:${source_url}`);
            media.push({media_type: type, source_url, preview_url, position: media.length});
          };
          content.querySelectorAll('img').forEach(img => addMedia('image', img.currentSrc || img.src || img.dataset.src));
          content.querySelectorAll('video').forEach(video => {
            addMedia('video', video.currentSrc || video.src || video.querySelector('source')?.src, video.poster || null);
          });
          content.querySelectorAll('a[href]').forEach(link => {
            if (/\\.(?:jpe?g|png|gif|webp)(?:$|\\?)/i.test(link.href)) addMedia('image', link.href);
            if (/\\/video\\//i.test(link.href)) addMedia('video', link.href);
          });
          const finalText = clean(content.innerText);
          const ending = blocks.slice(-2).map(block => block.text).filter(Boolean).join('\\n\\n');
          const telegramLinks = links.filter(link => /^(?:https?:\\/\\/)?(?:t|telegram)\\.me\\//i.test(link.target_url));
          const internalLinks = links.filter(link => /pikabu\\.ru\\/story\\//i.test(link.target_url));
          const mentionsRecommendations = /подборк|друг(?:их|ие) пост/i.test(ending);
          const structuredDates = [...document.querySelectorAll('script[type="application/ld+json"]')]
            .map(script => { try { return JSON.parse(script.textContent); } catch { return null; } })
            .flatMap(value => Array.isArray(value) ? value : [value])
            .filter(Boolean);
          const published = article.querySelector('time[datetime]')?.getAttribute('datetime')
            || document.querySelector('meta[property="article:published_time"]')?.content
            || structuredDates.find(value => value.datePublished)?.datePublished || null;
          return {
            external_id: article.dataset.storyId,
            canonical_url: location.href.split('#')[0].split('?')[0],
            title: clean(article.querySelector('.story__title')?.textContent),
            author_name: article.dataset.authorName,
            published_at: published,
            text: finalText,
            blocks,
            tags: [...article.querySelectorAll('.story__tags a')].map(tag => clean(tag.textContent)).filter(Boolean),
            ending_text: ending || null,
            ending_kind: telegramLinks.length ? 'telegram' : 'other',
            cta_text: telegramLinks.at(-1)?.text || null,
            cta_url: telegramLinks.at(-1)?.target_url || null,
            recommendations_status: internalLinks.length ? 'present' : (mentionsRecommendations ? 'mentioned_without_links' : 'absent'),
            links,
            media,
            metrics: {
              views: number(article.querySelector('.story__views')?.getAttribute('aria-label')),
              rating: number(article.dataset.rating || article.querySelector('.story__rating-count')?.textContent),
              pluses: votes ? number(votes[1]) : null,
              minuses: votes ? number(votes[2]) : null,
              saves: number(article.querySelector('.story__save')?.getAttribute('aria-label')),
              comments_reported: number(article.dataset.comments),
              emotions: [...article.querySelectorAll('.story__emotions button[data-id][data-count]')]
                .map(button => ({id: button.dataset.id, count: number(button.dataset.count)}))
            }
          };
        }
        """
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect text-first Pikabu posts without downloading media")
    parser.add_argument("--profile-url", default=PROFILE_URL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-profile", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--pause", type=float, default=1.2)
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    output = ensure_private_path(args.output)
    browser_profile = ensure_private_path(args.browser_profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    browser_profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_profile), headless=args.headless, viewport={"width": 1440, "height": 1000}
        )
        page = context.pages[0] if context.pages else context.new_page()
        urls = discover(page, args.profile_url, limit=args.limit)
        existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        if not isinstance(existing, dict):
            existing = {}
        items = existing.get("items") if isinstance(existing.get("items"), list) else []
        failures = existing.get("failures") if isinstance(existing.get("failures"), list) else []
        completed_ids = {str(item.get("external_id")) for item in items if item.get("external_id")}
        failures_by_url = {item.get("url"): item for item in failures if item.get("url")}
        for index, url in enumerate(urls, start=1):
            match = STORY_RE.match(url)
            if match and match.group(1) in completed_ids:
                print(f"[{index}/{len(urls)}] SKIP {match.group(1)}")
                continue
            try:
                item = extract_story(page, url)
                if item.get("author_name") != "armagedongt":
                    print(f"[{index}/{len(urls)}] SKIP foreign author {url}")
                    continue
                items.append(item)
                completed_ids.add(str(item["external_id"]))
                failures_by_url.pop(url, None)
                print(f"[{index}/{len(urls)}] {item['external_id']} {item['title']}")
            except Exception as exc:  # collector must continue and report exact failed URL
                failures_by_url[url] = {"url": url, "error": str(exc)}
                print(f"[{index}/{len(urls)}] FAILED {url}: {exc}")
            failures = list(failures_by_url.values())
            save_checkpoint(
                output,
                profile_url=args.profile_url,
                discovered=len(urls),
                items=items,
                failures=failures,
            )
            time.sleep(max(args.pause, 0))
        context.close()

    save_checkpoint(
        output,
        profile_url=args.profile_url,
        discovered=len(urls),
        items=items,
        failures=failures,
    )
    print(f"Saved {len(items)} items to {output}; failures: {len(failures)}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
