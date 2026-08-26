"""Build a reversible local working corpus from author-only JSONL exports."""
from __future__ import annotations

import argparse, hashlib, json, re
from collections import Counter
from pathlib import Path

URL = re.compile(r"https?://\S+|tg://\S+", re.I)
VAR = re.compile(r"\{\{[^}]+\}\}")
SPACE = re.compile(r"\s+")
TECHNICAL = re.compile(r"^(?:/\w+|utm\b|дата открытия|присвоение тегов|код ответа)\b", re.I)

def private(path: Path) -> Path:
    resolved = path.expanduser().resolve(); repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents: raise ValueError("corpus path must be outside Git")
    return resolved

def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

def key(text: str) -> str:
    return SPACE.sub(" ", VAR.sub("{{var}}", URL.sub("<url>", text))).strip().lower()

def digest(value: str) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None

def write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True)+"\n" for x in items), encoding="utf-8")

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--originals", type=Path, required=True); p.add_argument("--working", type=Path, required=True); a=p.parse_args()
    originals, working = private(a.originals), private(a.working)
    published=rows(originals/"published-content.jsonl"); bot=rows(originals/"bot-constructor.jsonl")
    telegram=[x for x in published if x.get("platform")=="telegram"]
    write(working/"telegram-channel.jsonl", telegram)
    kept=[]; excluded=[]; seen={}
    for item in bot:
        title=str(item.get("title") or "").strip()
        text=str(item.get("body_source") or "").strip()
        normalized=key(text)
        reason = "empty" if not normalized else "technical" if TECHNICAL.match(normalized) else None
        # A different title is a different hook.  Keep it even if the body repeats.
        # URL targets and template variables do not make a new text version.
        full_key=key(title+"\n"+text)
        full_digest=digest(full_key)
        if not reason and full_digest in seen: reason="duplicate_or_link_only"; item={**item,"duplicate_of":seen[full_digest]}
        if reason: excluded.append({**item,"working_status":"excluded","exclusion_reason":reason})
        else: seen[full_digest]=item["code"]; kept.append({**item,"working_status":"candidate","normalized_hash":full_digest,"normalized_title":key(title),"normalized_body":normalized})

    # Do not merge meaningful variants.  Connect candidates that share a title
    # (same topic, different ending/CTA) or a body (same text, different hook).
    groups: dict[str, list[str]]={}
    for item in kept:
        for marker in ("title:"+item["normalized_title"], "body:"+item["normalized_body"]):
            if marker not in ("title:", "body:"): groups.setdefault(marker,[]).append(item["code"])
    related={code: sorted(set(codes)) for codes in groups.values() if len(set(codes))>1 for code in codes}
    kept=[{k:v for k,v in item.items() if k not in {"normalized_title","normalized_body"}} | ({"related_versions":related[item["code"]]} if item["code"] in related else {}) for item in kept]
    write(working/"bot-candidates.jsonl", kept); write(working/"bot-excluded.jsonl", excluded)
    report={"telegram_posts":len(telegram),"bot_candidates":len(kept),"bot_excluded":len(excluded),"exclusion_reasons":dict(Counter(x["exclusion_reason"] for x in excluded))}
    (working/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
