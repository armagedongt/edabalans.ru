"""Read-only public SEO snapshot. Refuse to overwrite an existing archive."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.h1 = ""
        self.description = None
        self.canonical = None
        self.mode = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("title", "h1"):
            self.mode = tag
        if tag == "meta" and attrs.get("name") == "description":
            self.description = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href")

    def handle_endtag(self, tag):
        if tag == self.mode:
            self.mode = None

    def handle_data(self, data):
        if self.mode == "title":
            self.title += data
        elif self.mode == "h1":
            self.h1 += data


def capture(article, origin):
    url = origin + "/articles/" + article["slug"]
    record = {key: article[key] for key in ("source_id", "slug", "title", "category")}
    record.update(url=url, source_provenance=article.get("source_provenance", {}))
    try:
        request = Request(url, headers={"User-Agent": "EdabalansEditorialAudit/1.0"})
        with urlopen(request, timeout=25) as response:
            body = response.read()
            record["status"] = response.status
        parser = MetadataParser()
        parser.feed(body.decode("utf-8"))
        record.update(search_title=parser.title, h1=parser.h1,
                      description=parser.description, canonical=parser.canonical,
                      html_sha256=hashlib.sha256(body).hexdigest())
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Archive already exists: choose a new snapshot filename")
    articles = json.loads(args.manifest.read_text(encoding="utf-8"))["articles"]
    articles = [article for article in articles if article["status"] == "published"]
    origin = "https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda article: capture(article, origin), articles))
    payload = {"captured_at": datetime.now(timezone.utc).isoformat(), "records": records}
    # No credentials, cookies, private drafts or external writes are involved.
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)
        target.write("\n")
    errors = sum("error" in record for record in records)
    print(json.dumps({"articles": len(records), "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
