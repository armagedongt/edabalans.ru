import hashlib
from unittest.mock import Mock

import pytest

from tools import editorial_email_adapter as email
from tools import editorial_git_adapter as git


def test_catalog_links_real_originals_and_shared_git_publisher():
    api = Mock()
    api.request.return_value = {"templates": [{"code": "login-code",
        "path": "content/service-messages/email/login-code.md", "sections": {"subject": [], "text": ["code"]}}]}
    item = email.discover(api)["email:login-code"]
    assert item["kind"] == "git"
    assert item["path"] == "Письма/login-code.md"
    assert item["sections"]["text"] == ["code"]
    api.request.assert_called_once_with("GET", "/admin/api/editorial/service-emails")


def test_catalog_accepts_all_current_server_templates():
    from app.service_email_templates import SCHEMAS, source_path
    api = Mock()
    api.request.return_value = {"templates": [{"code": code, "path": source_path(code),
        "sections": {name: sorted(variables) for name, variables in sections.items()}}
        for code, sections in SCHEMAS.items()]}
    items = email.discover(api)
    assert set(items) == {"email:" + code for code in SCHEMAS}
    assert items["email:tilda-transfer"]["source_path"] == "content/service-messages/email/tilda-transfer.md"
    assert items["email:tilda-transfer"]["sections"]["text"] == sorted(SCHEMAS["tilda-transfer"]["text"])


@pytest.mark.parametrize("code,path", [("unknown", "content/service-messages/email/unknown.md"),
                                      ("login-code", "../../other.md")])
def test_discovery_rejects_unknown_or_misrouted_originals(code, path):
    api = Mock()
    api.request.return_value = {"templates": [{"code": code, "path": path, "sections": {}}]}
    with pytest.raises(ValueError):
        email.discover(api)


def test_email_git_read_verifies_actual_runtime_not_just_github_acceptance():
    api = Mock()
    source = "Оригинал письма"
    item = {"api_path": "/admin/api/editorial/service-emails/login-code", "title": "Письмо"}
    api.request.return_value = {"main": {"sha": "a" * 40, "content": source},
        "draft": None, "runtime_source": {"sha256": hashlib.sha256(source.encode()).hexdigest()}}
    remote = git.read(api, item)
    assert git.runtime_matches(remote)
    api.request.return_value["runtime_source"]["sha256"] = "old-runtime-hash"
    assert not git.runtime_matches(git.read(api, item))
