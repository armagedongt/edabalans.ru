import pytest
from tools.editorial_media import local_images, rendered_source, unchanged, working_source


def test_packaged_git_asset_is_kept_but_actual_local_replacement_is_uploaded(tmp_path):
    file = tmp_path / "Course" / "Lesson.md"
    file.parent.mkdir()
    source = "![Фото](../assets/photo.png)"
    with pytest.raises(ValueError, match="не найдена"):
        local_images(tmp_path, file, source)
    assert local_images(tmp_path, file, source, server_prefixes=("../assets/",)) == []
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "photo.png").write_bytes(b"replacement")
    assert len(local_images(tmp_path, file, source, server_prefixes=("../assets/",))) == 1


def test_obsidian_attachment_and_byte_replacement_keep_local_original(tmp_path):
    file = tmp_path / "Course" / "Lesson.md"
    file.parent.mkdir()
    image = file.parent / "Фото обеда.png"
    image.write_bytes(b"first image")
    source = "Текст\n\n![[Фото обеда.png|Обед]]\n"
    found = local_images(tmp_path, file, source)
    first = rendered_source(source, found, "course:masterclass-21:day-01-article-01")
    assert first.startswith("Текст\n\n![Обед](https://edabalans.ru/editorial-media/")
    assert working_source(first, source, found, "course:masterclass-21:day-01-article-01") == source
    image.write_bytes(b"replacement")
    assert not unchanged(found)
    assert rendered_source(source, local_images(tmp_path, file, source), "course:masterclass-21:day-01-article-01") != first


def test_identical_bytes_keep_distinct_local_originals(tmp_path):
    file = tmp_path / "Lesson.md"
    (tmp_path / "first.png").write_bytes(b"same picture")
    (tmp_path / "second.png").write_bytes(b"same picture")
    source = '![[first.png|Фото]]\n\n![[second.png|Фото]]\n'
    images = local_images(tmp_path, file, source)
    remote = rendered_source(source, images, "public:program")
    assert working_source(remote, source, images, "public:program") == source


def test_standard_markdown_space_path_and_fenced_examples(tmp_path):
    file = tmp_path / "Lesson.md"
    (tmp_path / "Фото.png").write_bytes(b"image")
    source = '```md\n![[missing.png]]\n```\n`![[missing.png]]`\n![Фото](<Фото.png> "Подпись")\n![Remote](https://example.org/a.png)\n'
    images = local_images(tmp_path, file, source)
    assert len(images) == 1 and images[0].alt == "Фото"
    rendered = rendered_source(source, images, "public:program")
    assert rendered.count("missing.png") == 2 and ' "Подпись")' in rendered
    assert "https://example.org/a.png" in rendered


@pytest.mark.parametrize("fence", ["~~~md\n![[missing.png]]\n~~~~\n", "```md\n![[missing.png]]\n````\n", "~~~md\n![[missing.png]]"])
def test_longer_closing_or_unclosed_code_fences_keep_attachment_examples_literal(tmp_path, fence):
    assert local_images(tmp_path, tmp_path / "Lesson.md", fence) == []


@pytest.mark.parametrize("target", ["../outside.png", "C:/secret.png", "//server/share.png", "file:///private.png"])
def test_paths_outside_vault_cannot_be_uploaded(tmp_path, target):
    with pytest.raises(ValueError):
        local_images(tmp_path, tmp_path / "Lesson.md", f"![[{target}]]")


def test_duplicate_basename_reports_ambiguity_instead_of_picking_file(tmp_path):
    for folder in ("one", "two"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "same.png").write_bytes(b"image")
    with pytest.raises(ValueError, match="неоднозначно"):
        local_images(tmp_path, tmp_path / "Lesson.md", "![[same.png]]")


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside-image.png"
    outside.write_bytes(b"image")
    try:
        (tmp_path / "image.png").symlink_to(outside)
    except OSError:
        pytest.skip("OS account lacks symlink creation permission")
    with pytest.raises(ValueError):
        local_images(tmp_path, tmp_path / "Lesson.md", "![[image.png]]")
