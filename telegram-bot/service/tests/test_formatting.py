from app.formatting import to_telegram_html


def test_leadteh_markup_is_converted_and_unsafe_html_is_escaped():
    source = "Привет *жирный* _курсив_ [ссылка](https://example.com) <script>x</script> <b>готово</b>"
    rendered = to_telegram_html(source)
    assert "<b>жирный</b>" in rendered
    assert "<i>курсив</i>" in rendered
    assert '<a href="https://example.com">ссылка</a>' in rendered
    assert "&lt;script&gt;" in rendered
    assert "<b>готово</b>" in rendered
