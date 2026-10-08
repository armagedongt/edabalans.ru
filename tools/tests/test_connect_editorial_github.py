import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import stat
from types import SimpleNamespace

import pytest

from tools import connect_editorial_github as relay


TOKEN = "github_pat_" + "fictional_only_fixture_" * 3


@pytest.mark.parametrize("original,expected", [
    (b"A=one\nGITHUB_CONTENTS_TOKEN=\nB='two'\n", b"A=one\nGITHUB_CONTENTS_TOKEN=" + TOKEN.encode() + b"\nB='two'\n"),
    (b"# comment\r\nexport GITHUB_CONTENTS_TOKEN = ''\r\nB=two", b"# comment\r\nexport GITHUB_CONTENTS_TOKEN =" + TOKEN.encode() + b"\r\nB=two"),
    (b"A=one", b"A=one\nGITHUB_CONTENTS_TOKEN=" + TOKEN.encode() + b"\n"),
    (b"A=one\r\n", b"A=one\r\nGITHUB_CONTENTS_TOKEN=" + TOKEN.encode() + b"\r\n"),
    (b"", b"GITHUB_CONTENTS_TOKEN=" + TOKEN.encode() + b"\n"),
])
def test_only_empty_key_changes_other_bytes_are_exact(original, expected):
    assert relay.replace_empty_credential(original, TOKEN) == expected


@pytest.mark.parametrize("original", [
    b"GITHUB_CONTENTS_TOKEN=existing_other_owner\n",
    b'GITHUB_CONTENTS_TOKEN="existing_other_owner"\n',
    b"GITHUB_CONTENTS_TOKEN=\n export GITHUB_CONTENTS_TOKEN=\n",
    b"GITHUB_CONTENTS_TOKEN= # ambiguous comment\n",
])
def test_occupied_duplicate_or_ambiguous_key_refused(original):
    with pytest.raises(ValueError):
        relay.replace_empty_credential(original, TOKEN)


@pytest.mark.parametrize("token", ["ghp_fictional", TOKEN + "\nINJECT=value", TOKEN + "'", "", None])
def test_only_bounded_fine_grained_token_is_accepted(token):
    with pytest.raises(ValueError):
        relay.validate_token(token)


def test_relay_fixed_destination_token_only_in_stdin():
    calls = []

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'{"status":"connected_readable","saved":true}', stderr=TOKEN.encode())

    assert relay.connect(TOKEN, runner=runner) == {"status": "connected_readable", "saved": True}
    arguments, options = calls[0]
    assert arguments[:6] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "edabalans-prod"]
    assert TOKEN not in " ".join(arguments)
    assert json.loads(options["input"]) == {"token": TOKEN}
    assert options["timeout"] == 90 and options["capture_output"] is True
    assert relay.ENV_PATH in arguments[-1]
    assert "--no-deps" in arguments[-1] and "--pull" in arguments[-1]


@pytest.mark.parametrize("failure", ["exit", "timeout", "malformed", "untrusted_status"])
def test_process_failures_never_surface_stdout_stderr_or_token(failure):
    def runner(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(TOKEN, 90, output=TOKEN.encode(), stderr=TOKEN.encode())
        stdout = {"malformed": TOKEN.encode(), "untrusted_status": json.dumps({"status":TOKEN,"saved":True}).encode()}.get(failure,b"{}")
        return SimpleNamespace(returncode=1 if failure == "exit" else 0, stdout=stdout, stderr=TOKEN.encode())
    with pytest.raises(relay.ConnectionError) as captured:
        relay.connect(TOKEN, runner=runner)
    assert TOKEN not in str(captured.value)
    assert captured.value.__suppress_context__


def test_remote_code_compiles_and_is_idle_until_explicit_connect():
    script = relay.remote_script()
    compile(script, "credential-relay", "exec")
    assert TOKEN not in script
    assert "os.replace(temporary, ENV_PATH)" in script
    assert "initial_stat.st_uid" in script and "stat.S_IMODE" in script
    assert "print(json.dumps" in script
    assert "Contents: write" not in script  # Read verification is not a fake write test.


@pytest.mark.parametrize("status,saved", [("credential_exists",False),("duplicate_key",False),
                                            ("restart_failed",True),("verify_failed",True)])
def test_sanitized_partial_result_is_retained(status,saved):
    result = relay.connect(TOKEN, runner=lambda *args, **kwargs: SimpleNamespace(returncode=0,
        stdout=json.dumps({"status":status,"saved":saved}).encode(), stderr=b""))
    assert result == {"status":status,"saved":saved}


@pytest.mark.parametrize("case", ["success", "occupied", "duplicate", "restart_error", "read_error"])
def test_remote_protocol_only_fictional_local_fixture(monkeypatch,tmp_path,capsys,case):
    """Simulate remote Linux file operations without any SSH, Docker, or live token."""
    env = tmp_path / ".env"
    initial = b"OTHER=unchanged\r\nGITHUB_CONTENTS_TOKEN=\r\nFINAL=value\r\n"
    if case == "occupied":
        initial = initial.replace(b"TOKEN=", b"TOKEN=another_owner")
    if case == "duplicate":
        initial += b"GITHUB_CONTENTS_TOKEN=\r\n"
    env.write_bytes(initial)
    # Model the restricted Linux secret file, irrespective of Windows ACL mode.
    original_fstat = os.fstat
    def restricted_stat(fd):
        current = original_fstat(fd)
        return os.stat_result((stat.S_IFREG | 0o600, *current[1:]))
    monkeypatch.setattr(os, "fstat", restricted_stat)
    original_stat = os.stat_result((stat.S_IFREG | 0o600, *env.stat()[1:]))
    namespace = {}
    exec(relay.remote_script().rsplit("\n_remote_main()",1)[0],namespace)
    namespace["ENV_PATH"] = str(env)
    monkeypatch.setitem(sys.modules,"fcntl",SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *args:None))
    monkeypatch.setattr(sys,"stdin",SimpleNamespace(buffer=io.BytesIO(json.dumps({"token":TOKEN}).encode())))
    original_mkstemp = tempfile.mkstemp
    monkeypatch.setattr(tempfile,"mkstemp",lambda prefix,dir: original_mkstemp(prefix=prefix,dir=tmp_path))
    permissions = []
    monkeypatch.setattr(os,"fchmod",lambda fd,mode:permissions.append(("mode",mode)),raising=False)
    monkeypatch.setattr(os,"fchown",lambda fd,uid,gid:permissions.append(("owner",uid,gid)),raising=False)
    monkeypatch.setattr(os,"O_DIRECTORY",0,raising=False)
    monkeypatch.setattr(os,"fsync",lambda fd:None)
    original_open = os.open
    directory_fixture = tmp_path / "directory-fixture"
    directory_fixture.write_bytes(b"")
    monkeypatch.setattr(os,"open",lambda path,flags,*args,**kwargs:
        original_open(directory_fixture if path=="/opt/edabalans" else path,flags,*args,**kwargs))
    replaced = []
    def replace(source,destination):
        assert destination==str(env)
        replaced.append((source,destination))
        # Windows denies real replace of a held-open file; simulate this Linux primitive.
        env.write_bytes(Path(source).read_bytes())
        Path(source).unlink()
    monkeypatch.setattr(os,"replace",replace)
    calls = []
    def run(arguments,**kwargs):
        calls.append((arguments,kwargs))
        assert kwargs["cwd"]=="/opt/edabalans"
        assert TOKEN not in " ".join(arguments)
        if "up" in arguments:
            return SimpleNamespace(returncode=int(case=="restart_error"),stdout=b"",stderr=TOKEN.encode())
        return SimpleNamespace(returncode=int(case=="read_error"),stdout=b"connected_readable\n",stderr=TOKEN.encode())
    monkeypatch.setattr(subprocess,"run",run)
    namespace["_remote_main"]()
    output=capsys.readouterr().out
    assert TOKEN not in output
    result=json.loads(output)
    if case in {"occupied","duplicate"}:
        assert env.read_bytes()==initial and not calls and not replaced
        assert result=={"status":"credential_exists" if case=="occupied" else "duplicate_key","saved":False}
    else:
        assert env.read_bytes()==relay.replace_empty_credential(initial,TOKEN)
        assert len(replaced)==1
        assert permissions == [("mode", stat.S_IMODE(original_stat.st_mode)),
                               ("owner", original_stat.st_uid, original_stat.st_gid)]
        assert result=={"status":{"success":"connected_readable","restart_error":"restart_failed","read_error":"verify_failed"}[case],"saved":True}
        assert all(call[1]["timeout"]<=45 for call in calls)
    assert not list(tmp_path.glob(".github-connect-*"))
