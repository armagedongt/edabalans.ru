"""One-time, personally entered GitHub credential relay over existing SSH.

Importing this module performs no I/O. Never accepts a token on the command line.
"""
from __future__ import annotations

import inspect
import json
import re
import shlex
import subprocess

SSH_HOST = "edabalans-prod"
REPOSITORY = "armagedongt/edabalans.ru"
ENV_PATH = "/opt/edabalans/.env"
TOKEN_KEY = b"GITHUB_CONTENTS_TOKEN"
TOKEN_RE = re.compile(r"github_pat_[A-Za-z0-9_]{20,240}")


class ConnectionError(Exception):
    """Sanitized failure; never includes process output or the credential."""


def validate_token(token: str) -> str:
    if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
        raise ValueError("Нужен fine-grained токен GitHub, начинающийся с github_pat_.")
    return token


def replace_empty_credential(original: bytes, token: str) -> bytes:
    """Preserve every other byte; fail closed on occupied or duplicated keys."""
    value = validate_token(token).encode("ascii")
    lines = original.splitlines(keepends=True)
    pattern = re.compile(rb"^[ \t]*(?:export[ \t]+)?GITHUB_CONTENTS_TOKEN[ \t]*=")
    matches = [(index, pattern.match(line)) for index, line in enumerate(lines)]
    matches = [(index, match) for index, match in matches if match is not None]
    if len(matches) > 1:
        raise ValueError("duplicate_key")
    if matches:
        index, match = matches[0]
        line = lines[index]
        ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
        body = line[:-len(ending)] if ending else line
        if body[match.end():].strip() not in {b"", b'""', b"''"}:
            raise ValueError("credential_exists")
        lines[index] = body[:match.end()] + value + ending
        return b"".join(lines)
    ending = b"\r\n" if b"\r\n" in original else b"\n"
    separator = ending if original and not original.endswith(b"\n") else b""
    return original + separator + TOKEN_KEY + b"=" + value + ending


def _remote_main():
    # This function's source is sent as code, while the token travels only on stdin.
    import fcntl
    import os
    import stat
    import tempfile

    phase = "input"
    saved = False
    temporary = None
    try:
        payload = sys.stdin.buffer.read(1025)
        if len(payload) > 1024:
            raise ValueError("bad_input")
        token = validate_token(json.loads(payload)["token"])
        phase = "env"
        with open(ENV_PATH, "r+b") as source:
            fcntl.flock(source, fcntl.LOCK_EX | fcntl.LOCK_NB)
            initial_stat = os.fstat(source.fileno())
            if not stat.S_ISREG(initial_stat.st_mode) or os.path.islink(ENV_PATH):
                raise ValueError("unsafe_env")
            original = source.read()
            replacement = replace_empty_credential(original, token)
            fd, temporary = tempfile.mkstemp(prefix=".github-connect-", dir="/opt/edabalans")
            try:
                os.fchmod(fd, stat.S_IMODE(initial_stat.st_mode))
                os.fchown(fd, initial_stat.st_uid, initial_stat.st_gid)
                with os.fdopen(fd, "wb") as target:
                    target.write(replacement)
                    target.flush()
                    os.fsync(target.fileno())
            except BaseException:
                os.close(fd) if _fd_open(fd) else None
                raise
            source.seek(0)
            current_stat = os.stat(ENV_PATH, follow_symlinks=False)
            if ((current_stat.st_dev, current_stat.st_ino) != (initial_stat.st_dev, initial_stat.st_ino)
                    or source.read() != original):
                raise ValueError("env_changed")
            os.replace(temporary, ENV_PATH)
            temporary = None
            saved = True
            directory_fd = os.open("/opt/edabalans", os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        # No dependencies, build, image pull, migrations, or Git writes.
        phase = "restart"
        result = subprocess.run(["docker", "compose", "up", "-d", "--force-recreate",
                                 "--no-deps", "--no-build", "--pull", "never", "backend"],
                                cwd="/opt/edabalans", capture_output=True, timeout=45)
        if result.returncode:
            raise ValueError("restart_failed")
        phase = "verify"
        verification = (
            "from app.github_content_editor import GitHubContentEditor; "
            "e=GitHubContentEditor(); "
            "assert e.connected and e.repository=='armagedongt/edabalans.ru'; "
            "r=e._request('GET','contents/content/masterclass/editorial/weight-loss-roadmap.md',"
            "query={'ref':e.main_branch}); assert r.get('type')=='file'; print('connected_readable')"
        )
        result = subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c", verification],
                                cwd="/opt/edabalans", capture_output=True, timeout=30)
        if result.returncode or result.stdout.strip() != b"connected_readable":
            raise ValueError("verification_failed")
        print(json.dumps({"status": "connected_readable", "saved": True}))
    except BaseException as error:
        # Never print raw Docker/GitHub errors, exception text, or stdin.
        known = {"duplicate_key", "credential_exists", "unsafe_env", "env_changed"}
        reason = str(error) if type(error) is ValueError and str(error) in known else phase + "_failed"
        print(json.dumps({"status": reason, "saved": saved}))
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _fd_open(fd):
    import os
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


def remote_script() -> str:
    return ("import json,re,subprocess,sys\n" +
            f"ENV_PATH={ENV_PATH!r}\nTOKEN_KEY={TOKEN_KEY!r}\nTOKEN_RE=re.compile({TOKEN_RE.pattern!r})\n" +
            inspect.getsource(validate_token) + "\n" + inspect.getsource(replace_empty_credential) + "\n" +
            inspect.getsource(_fd_open) + "\n" + inspect.getsource(_remote_main) + "\n_remote_main()\n")


def connect(token: str, *, runner=subprocess.run) -> dict:
    token = validate_token(token)
    command = "python3 -c " + shlex.quote(remote_script())
    try:
        result = runner(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH_HOST, command],
                        input=json.dumps({"token": token}).encode("ascii"),
                        capture_output=True, timeout=90)
    except Exception:
        raise ConnectionError("Результат подключения неизвестен. Проверьте сервер через Codex; не повторяйте ввод токена.") from None
    if result.returncode:
        raise ConnectionError("SSH не подтвердил результат. Проверьте сервер через Codex; не повторяйте ввод токена.") from None
    try:
        payload = json.loads(result.stdout)
        statuses = {"connected_readable", "duplicate_key", "credential_exists", "unsafe_env", "env_changed",
                    "input_failed", "env_failed", "restart_failed", "verify_failed"}
        if (not isinstance(payload, dict) or payload.keys() != {"status", "saved"}
                or payload["status"] not in statuses or type(payload["saved"]) is not bool):
            raise ValueError()
        return payload
    except Exception:
        raise ConnectionError("Не удалось подтвердить результат. Проверьте сервер через Codex; не повторяйте ввод токена.") from None


def main():
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    window = tk.Tk()
    window.withdraw()
    try:
        entered = simpledialog.askstring("Подключить редактор GitHub",
            "Вставьте созданный вами fine-grained токен для armagedongt/edabalans.ru.\n"
            "Он уйдёт через SSH только в серверный GITHUB_CONTENTS_TOKEN.\n"
            "Backend будет перезапущен; существующий непустой токен не заменяется.",
            show="*", parent=window)
        if entered is None:
            return
        token = entered.strip()
        entered = None
        result = connect(token)
        token = None
        if result["status"] == "connected_readable":
            messagebox.showinfo("Подключено", "Сервер читает GitHub с новым токеном.\n"
                "Право записи не проверялось записью; материалы не менялись.", parent=window)
        else:
            messagebox.showerror("Нужна проверка Codex", "Подключение не завершено. "
                + ("Токен уже сохранён на сервере; повторно его не вводите." if result["saved"]
                   else "Сервер не подтвердил сохранение токена; проверьте причину через Codex.")
                + "\nКод результата: " + result["status"], parent=window)
    except (ValueError, ConnectionError) as error:
        messagebox.showerror("Подключение", str(error), parent=window)
    finally:
        window.destroy()


if __name__ == "__main__":
    main()
