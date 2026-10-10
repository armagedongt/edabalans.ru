import pytest

from app.article_markdown_conversion import ConversionError, Tree, convert, fingerprint, rendered


@pytest.mark.parametrize("source", [
    "## Заголовок\n\nАбзац с **выделением** и [ссылкой](https://example.org/page).\n\n- Один\n- Два\n\n3. Три\n4. Четыре\n",
    "> [!NOTE]\n> Плашка с **важным текстом**.\n>\n> - Один\n> - Два\n\n> Цитата\n> Вторая строка\n",
    '| Поле | Значение |\n| --- | --- |\n| **Вес** | 100 г |\n| Разделитель | Один \\| два |\n',
    "![Фото](https://example.org/photo.jpg)\n",
    "dqs_score_table(\nfull\n)\n\nslider(\nhttps://example.org/one.png\nhttps://example.org/two.png\n)\n",
    "spoiler(\nЗаголовок\nПервый абзац.\nВторой **абзац**.\n)\n",
    "video(\nhttps://example.org/video.mp4\nНазвание видео\n)\n",
    "audio(\nhttps://example.org/audio.mp3\nhttps://example.org/avatar.jpg\nСергей\n2:30\n)\n",
    "Обычная \\*звёздочка\\* и \\~знак\\~.\n",
])
def test_representative_article_and_unique_components_keep_their_complete_dom(source):
    original = rendered(source)
    markdown = convert(original)
    assert fingerprint(Tree(rendered(markdown)).root) == fingerprint(Tree(original).root)
    assert "<" not in markdown


@pytest.mark.parametrize("html", [
    "<p>Текст</p><script>alert(1)</script>",
    '<p>Текст</p><div class="unknown">Важный текст</div>',
    '<figure><img src="https://example.org/photo.png" alt="Фото"><span>Подпись</span></figure>',
    '<ul><li>Первый<ul><li>Вложенный</li></ul></li></ul>',
    '<p>Не закрыт',
    '<p></p>',
    '',
])
def test_unknown_or_unrepresentable_html_is_rejected_without_dropping_any_nodes(html):
    with pytest.raises(ConversionError):
        convert(html)


def test_image_decoding_hint_is_the_only_ignored_image_attribute():
    original = '<figure><img src="https://example.org/p.png" alt="" loading="lazy"></figure>'
    assert convert(original) == '![](https://example.org/p.png)\n'
    with pytest.raises(ConversionError):
        convert(original.replace('alt=""', 'alt="" width="300"'))
