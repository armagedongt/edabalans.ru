import pytest
from app.message_markdown import compile_message_markdown


def test_compile_preserves_message_formatting_and_template_links():
    result = compile_message_markdown('**Привет**\n\n*Начните* с [статьи]({{personal_intensive_url}}).\n\n> Первая строка\n> Вторая строка')
    assert "<b>Привет</b>" in result
    assert '<a href="{{personal_intensive_url}}">статьи</a>' in result
    assert "<blockquote>" in result and "Первая строка\nВторая строка" in result


@pytest.mark.parametrize("source", ['[жми](javascript:alert)', '<script>bad</script>',
                                         '![Фото](../secret.png)', '| a | b |\n|---|---|\n| x | y |\n\n<img src="x">'])
def test_compile_rejects_unsafe_links_and_unsupported_media(source):
    with pytest.raises(ValueError):
        compile_message_markdown(source)


def test_entities_lists_and_literal_angle_brackets():
    result = compile_message_markdown("Еда & спорт\n\n1. Один\n2. Два\n\n`x < y`")
    assert "Еда &amp; спорт" in result
    assert "1. Один" in result and "2. Два" in result
    assert "<code>x &lt; y</code>" in result


def test_spoiler_and_strike_preserve_code_literals():
    result = compile_message_markdown("~~Шутка~~ ||Секрет|| `~~код~~` `||код||`")
    assert "<s>Шутка</s>" in result
    assert "<tg-spoiler>Секрет</tg-spoiler>" in result
    assert "<code>~~код~~</code>" in result and "<code>||код||</code>" in result


def test_invalid_raw_list_rejected_with_validation_error():
    with pytest.raises(ValueError):
        compile_message_markdown("<li>Без списка</li>")


def test_ordered_list_preserves_author_start_number():
    result = compile_message_markdown("3. Третий\n4. Четвёртый")
    assert "3. Третий" in result and "4. Четвёртый" in result
