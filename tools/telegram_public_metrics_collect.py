import argparse
import json
import re
import sys
from pathlib import Path


def ensure_private_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("collector output/profile must be outside the Git repository")
    return resolved


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Collect public Telegram views and reactions")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-profile", type=Path, required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()

    output = ensure_private_path(args.output)
    profile = ensure_private_path(args.browser_profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    channel = args.channel.strip().lstrip("@")

    from playwright.sync_api import sync_playwright

    rows: dict[int, dict] = {}
    before: int | None = None
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), headless=args.headless, viewport={"width": 1280, "height": 900}
        )
        page = context.pages[0] if context.pages else context.new_page()
        for page_no in range(1, args.max_pages + 1):
            url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
            page.goto(url, wait_until="domcontentloaded")
            batch = page.locator(".tgme_widget_message[data-post]").evaluate_all(
                r"""elements => elements.map(element => {
                  const compact = value => String(value || '').trim().toUpperCase().replace(',', '.');
                  const number = value => {
                    const match = compact(value).match(/^([\d.]+)\s*([KMBКМ]?)$/);
                    if (!match) return null;
                    const scale = {K: 1e3, 'К': 1e3, M: 1e6, 'М': 1e6, B: 1e9}[match[2]] || 1;
                    return Math.round(Number(match[1]) * scale);
                  };
                  const post = element.dataset.post || '';
                  const id = Number(post.split('/').at(-1));
                  const reactions = [...element.querySelectorAll('.tgme_widget_message_reactions .tgme_reaction')]
                    .map(node => ({emoji: node.querySelector('b')?.textContent || null, count: number(node.textContent.replace(node.querySelector('b')?.textContent || '', ''))}))
                    .filter(row => row.emoji && row.count !== null);
                  return {
                    message_id: id,
                    canonical_url: `https://t.me/${post}`,
                    published_at: element.querySelector('time[datetime]')?.getAttribute('datetime') || null,
                    views: number(element.querySelector('.tgme_widget_message_views')?.textContent),
                    reactions
                  };
                }).filter(row => Number.isInteger(row.message_id))"""
            )
            fresh = 0
            for row in batch:
                message_id = int(row["message_id"])
                if message_id not in rows:
                    fresh += 1
                rows[message_id] = row
            print(f"page {page_no}: {len(batch)} messages, {fresh} new")
            if not batch or not fresh:
                break
            minimum = min(int(row["message_id"]) for row in batch)
            if before is not None and minimum >= before:
                break
            before = minimum
        context.close()

    payload = {
        "source": {"platform": "telegram_public", "channel": channel},
        "items": [rows[key] for key in sorted(rows)],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} message metrics to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
