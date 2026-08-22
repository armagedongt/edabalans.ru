from __future__ import annotations

import argparse
import json
import re
import sys
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


def collect_comments(page: "Page") -> list[dict]:
    collected: dict[str, dict] = {}
    for _ in range(200):
        clicked = page.evaluate(
            r"""() => {
              const pattern = /^(?:раскрыть\s+\d+\s+комментар|ещё\s+[1-9]\d*(?:\s|$)|показать\s+ещё)/i;
              const buttons = [...document.querySelectorAll('button')]
                .filter(button => pattern.test(button.innerText.trim()));
              if (!buttons.length) return false;
              buttons[0].click();
              return true;
            }"""
        )
        if not clicked:
            break
        page.wait_for_timeout(300)
    comments = page.locator(".comment")
    for index in range(comments.count()):
        comment = comments.nth(index)
        comment.evaluate("element => element.scrollIntoView()")
        for _ in range(10):
            if "comment_placeholder" not in (comment.get_attribute("class") or ""):
                break
            page.wait_for_timeout(40)
        row = comment.evaluate(
                """element => {
                  const clean = value => String(value || '').replace(/\\u2060/g, '').trim();
                  const number = value => { const match = String(value || '').replace(/\\s/g, '').match(/-?\\d+/); return match ? Number(match[0]) : null; };
                  const meta = Object.fromEntries(String(element.dataset.meta || '').split(';').map(row => row.split('=', 2)).filter(row => row.length === 2));
                  const externalId = element.dataset.id || element.dataset.commentId || null;
                  const authorNode = element.querySelector('.comment__user, .comment__username');
                  const ratingNode = element.querySelector('.comment__rating-count, .comment__rating');
                  const textNode = element.querySelector('.comment__content, .comment__text');
                  let depth = 0;
                  for (let node = element.parentElement; node; node = node.parentElement) {
                    if (node.classList?.contains('comment__children')) depth += 1;
                  }
                  return {
                    external_id: externalId,
                    parent_external_id: meta.pid && meta.pid !== '0' ? meta.pid : null,
                    depth,
                    author_name: clean(authorNode?.textContent),
                    author_external_id: element.dataset.authorId || meta.aid || null,
                    is_owner_comment: Boolean(meta.aid && meta.said && meta.aid === meta.said) || clean(authorNode?.textContent).toLowerCase() === 'armagedongt',
                    published_at: element.querySelector('time[datetime]')?.getAttribute('datetime') || meta.d || null,
                    text: clean(textNode?.innerText || textNode?.textContent),
                    permalink: externalId ? `${location.href.split('#')[0].split('?')[0]}?cid=${externalId}` : null,
                    rating: number(ratingNode?.textContent || meta.r),
                    pluses: null, minuses: null,
                    emotions: [...element.querySelectorAll('.comment__emotions button[data-id][data-count]')].map(button => ({id: button.dataset.id, count: number(button.dataset.count)}))
                  };
                }"""
        )
        if row.get("external_id") and row.get("text"):
            collected[str(row["external_id"])] = row
    return list(collected.values())


def extract_story(page: "Page", url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded")
    story = page.locator("main article.story[data-page='true']")
    story.wait_for()
    for _ in range(5):
        label = story.locator(".story__views").get_attribute("aria-label")
        if label and re.search(r"\d", label):
            break
        page.wait_for_timeout(400)
    comments = collect_comments(page)
    result = story.evaluate(
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
          const decode = href => {
            try { return new URL(href).searchParams.get('u') || href; } catch { return href; }
          };
          const segments = element => {
            const rows = [];
            const walk = (node, inherited = 'plain') => {
              if (node.nodeType === Node.TEXT_NODE) {
                if (node.textContent) rows.push({type: inherited, text: node.textContent});
                return;
              }
              if (!(node instanceof HTMLElement)) return;
              if (node.tagName === 'BR') { rows.push({type: 'plain', text: '\\n'}); return; }
              let type = inherited;
              if (['B', 'STRONG'].includes(node.tagName)) type = 'bold';
              else if (['I', 'EM'].includes(node.tagName)) type = 'italic';
              else if (node.tagName === 'U') type = 'underline';
              else if (['S', 'DEL', 'STRIKE'].includes(node.tagName)) type = 'strikethrough';
              if (node.tagName === 'A' && node.href) {
                rows.push({type: 'link', text: node.innerText || node.textContent || node.href, href: decode(node.href)});
                return;
              }
              node.childNodes.forEach(child => walk(child, type));
            };
            element.childNodes.forEach(node => walk(node));
            return rows.filter(row => row.text);
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
            if (!source_url || mediaSeen.has(`${type}:${source_url}`)) return null;
            mediaSeen.add(`${type}:${source_url}`);
            const position = media.length;
            media.push({media_type: type, source_url, preview_url, position});
            return position;
          };
          const blocks = [...content.children].map((element, position) => {
            const mediaPositions = [];
            const remember = value => { if (value !== null) mediaPositions.push(value); };
            element.querySelectorAll('img').forEach(img => remember(addMedia('image', img.currentSrc || img.src || img.dataset.src)));
            element.querySelectorAll('video').forEach(video => remember(addMedia('video', video.currentSrc || video.src || video.querySelector('source')?.src, video.poster || null)));
            element.querySelectorAll('a[href]').forEach(link => {
              if (/\\.(?:jpe?g|png|gif|webp)(?:$|\\?)/i.test(link.href)) remember(addMedia('image', link.href));
              if (/\\/video\\//i.test(link.href)) remember(addMedia('video', link.href));
            });
            return {position, type: element.tagName.toLowerCase(), text: clean(element.innerText || element.textContent), segments: segments(element), media_positions: mediaPositions};
          }).filter(block => block.text || block.media_positions.length);
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
          const comments = [...document.querySelectorAll('.comment')].map(element => {
            let depth = 0;
            for (let node = element.parentElement; node; node = node.parentElement) {
              if (node.classList?.contains('comment__children')) depth += 1;
            }
            const meta = Object.fromEntries(String(element.dataset.meta || '').split(';').map(row => row.split('=', 2)).filter(row => row.length === 2));
            const linkNode = element.querySelector('a[href*="cid="], a.comment__datetime, a.comment__link');
            let externalId = element.dataset.id || element.dataset.commentId || null;
            const permalink = linkNode?.href || (externalId ? `${location.href.split('#')[0].split('?')[0]}?cid=${externalId}` : null);
            if (!externalId && permalink) { try { externalId = new URL(permalink).searchParams.get('cid'); } catch {} }
            const parent = element.parentElement?.closest('.comment');
            const parentLink = parent?.querySelector('a[href*="cid="], a.comment__datetime, a.comment__link')?.href;
            let parentId = meta.pid && meta.pid !== '0' ? meta.pid : parent?.dataset.id || parent?.dataset.commentId || null;
            if (!parentId && parentLink) { try { parentId = new URL(parentLink).searchParams.get('cid'); } catch {} }
            const authorNode = element.querySelector('.comment__user, .comment__username, [data-role="comment-user"]');
            const authorLink = authorNode?.closest('a') || element.querySelector('.comment__header a[href*="/profile/"]');
            const textNode = element.querySelector('.comment__content, .comment__text, .comment__body [itemprop="text"], .comment__body');
            const ratingNode = element.querySelector('.comment__rating-count, .comment__rating');
            const ratingLabel = ratingNode?.getAttribute('aria-label') || '';
            const plusMinus = ratingLabel.match(/([\\d\\s]+)\\s+плюс\\S*\\s*\\/\\s*([\\d\\s]+)\\s+минус/);
            return {
              external_id: externalId,
              parent_external_id: parentId,
              depth,
              author_name: clean(authorNode?.textContent),
              author_external_id: element.dataset.authorId || meta.aid || authorLink?.getAttribute('href') || null,
              is_owner_comment: (meta.aid && meta.said && meta.aid === meta.said) || clean(authorNode?.textContent).toLowerCase() === 'armagedongt',
              published_at: element.querySelector('time[datetime]')?.getAttribute('datetime') || meta.d || null,
              text: clean(textNode?.innerText || textNode?.textContent),
              permalink,
              rating: number(ratingNode?.textContent || ratingLabel || meta.r),
              pluses: plusMinus ? number(plusMinus[1]) : null,
              minuses: plusMinus ? number(plusMinus[2]) : null,
              emotions: []
            };
          }).filter(comment => comment.external_id && comment.text);
          const commentsReported = number(article.dataset.comments);
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
            comments,
            metrics: {
              views: number(article.querySelector('.story__views')?.getAttribute('aria-label')),
              rating: number(article.dataset.rating || article.querySelector('.story__rating-count')?.textContent),
              pluses: votes ? number(votes[1]) : null,
              minuses: votes ? number(votes[2]) : null,
              saves: number(article.querySelector('.story__save')?.getAttribute('aria-label')),
              comments_reported: commentsReported,
              details_json: {comments_loaded: comments.length, comments_partial: commentsReported !== null && comments.length < commentsReported},
              emotions: [...article.querySelectorAll('.story__emotions button[data-id][data-count]')]
                .map(button => ({id: button.dataset.id, count: number(button.dataset.count)}))
            }
          };
        }
        """
    )
    result["comments"] = comments
    result["metrics"]["details_json"] = {
        "comments_loaded": len(comments),
        "comments_partial": (
            result["metrics"].get("comments_reported") is not None
            and len(comments) < result["metrics"]["comments_reported"]
        ),
    }
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Collect text-first Pikabu posts without downloading media")
    parser.add_argument("--profile-url", default=PROFILE_URL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-profile", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="recollect items already in output")
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
        if args.refresh:
            items = []
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
