"""Install the current Markdown guide and render its single original example."""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from app.article_markup import markdown_to_article_html


def install(root: Path) -> None:
    source = REPO / "content/article-components"
    folder = root / "Шпаргалка"
    folder.mkdir(parents=True, exist_ok=True)
    guide = (source / "MARKDOWN_GUIDE.md").read_text(encoding="utf-8")
    guide = guide.replace("[каталоге компонентов](../masterclass/components/README.md)", "каталоге компонентов проекта (Codex знает его)")
    guide = guide.replace("../../docs/knowledge-base/EDITORIAL_VAULT.md", "<../Правила публикации.md>")
    guide = guide.replace("examples/common.md", "Пример.md")
    (folder / "Шпаргалка.md").write_text(guide, encoding="utf-8")
    markdown = (source / "examples/common.md").read_text(encoding="utf-8")
    (folder / "Пример.md").write_text(markdown, encoding="utf-8")
    css = "\n".join((source / name).read_text(encoding="utf-8") for name in ("typography.css", "note.css"))
    html = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Пример разметки</title><style>body{margin:24px auto;padding:0 16px;max-width:760px}' + css + '</style><article id="article">' + markdown_to_article_html(markdown) + '</article></html>'
    (folder / "Пример.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    install(Path(sys.argv[1]))
