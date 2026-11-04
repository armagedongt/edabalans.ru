import json
import io
import os
import socket
import struct
import subprocess
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import Mock, patch

from tools import edabalans_direct_ssh as direct
from tools.editorial_vault import API


class DirectSocketTests(unittest.TestCase):
    def test_proxy_relays_binary_stream_both_directions_and_half_closes_upload(self):
        local, peer = socket.socketpair()
        peer.settimeout(3)
        read_fd, write_fd = os.pipe()
        received_output = threading.Condition()

        class Output(io.BytesIO):
            def write(self, data):
                with received_output:
                    written = super().write(data)
                    received_output.notify_all()
                    return written

        output = Output()
        banner = b"SSH-2.0-peer\r\n"
        upload = bytes(range(256)) * 16
        download = b"\x00\xff\r\n" + bytes(reversed(range(256))) * 24
        errors = []

        def run_proxy():
            try:
                direct.proxy("server.example", 22)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_proxy, daemon=True)
        try:
            with patch.object(direct, "direct_socket", return_value=local), \
                 patch.object(direct.sys, "stdin", SimpleNamespace(fileno=lambda: read_fd)), \
                 patch.object(direct.sys, "stdout", SimpleNamespace(buffer=output)):
                worker.start()
                # An SSH peer must answer while client stdin is still open.
                peer.sendall(banner)
                with received_output:
                    self.assertTrue(received_output.wait_for(lambda: len(output.getvalue()) >= len(banner), timeout=3))
                self.assertEqual(output.getvalue(), banner)
                self.assertEqual(os.write(write_fd, upload), len(upload))
                received = bytearray()
                while len(received) < len(upload):
                    chunk = peer.recv(65536)
                    self.assertTrue(chunk)
                    received.extend(chunk)
                self.assertEqual(bytes(received), upload)
                peer.sendall(download)
                with received_output:
                    self.assertTrue(received_output.wait_for(lambda: len(output.getvalue()) >= len(banner + download), timeout=3))
                os.close(write_fd)
                write_fd = None
                self.assertEqual(peer.recv(1), b"")
                peer.shutdown(socket.SHUT_WR)
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive(), "Proxy did not finish after server EOF")
                self.assertEqual(errors, [])
                self.assertEqual(output.getvalue(), banner + download)
        finally:
            if write_fd is not None:
                os.close(write_fd)
            peer.close()
            local.close()
            worker.join(timeout=3)
            os.close(read_fd)

    def test_connection_selects_physical_interface_and_source(self):
        connection = Mock()
        with patch.object(direct, "physical_interface", return_value=(16, "192.0.2.2")), \
             patch.object(direct.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("192.0.2.10", 22))]), \
             patch.object(direct.socket, "socket", return_value=connection):
            self.assertIs(direct.direct_socket("server.example", 22), connection)
        connection.setsockopt.assert_called_once_with(socket.IPPROTO_IP, 31, struct.pack("!I", 16))
        connection.bind.assert_called_once_with(("192.0.2.2", 0))
        connection.connect.assert_called_once_with(("192.0.2.10", 22))

    def test_interface_binding_failure_closes_without_vpn_fallback(self):
        connection = Mock()
        connection.setsockopt.side_effect = OSError("interface unavailable")
        with patch.object(direct, "physical_interface", return_value=(16, "192.0.2.2")), \
             patch.object(direct.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("192.0.2.10", 22))]), \
             patch.object(direct.socket, "socket", return_value=connection):
            with self.assertRaisesRegex(OSError, "interface unavailable"):
                direct.direct_socket("server.example", 22)
        connection.close.assert_called_once()
        connection.connect.assert_not_called()

    def test_missing_physical_interface_does_not_attempt_normal_socket(self):
        with patch.object(direct, "physical_interface", side_effect=RuntimeError("no physical interface")), \
             patch.object(direct.socket, "socket") as create:
            with self.assertRaisesRegex(RuntimeError, "no physical interface"):
                direct.direct_socket("server.example", 22)
        create.assert_not_called()

    def test_windows_discovery_failure_is_not_silently_ignored(self):
        with patch.object(direct, "os", SimpleNamespace(name="nt")), \
             patch.object(direct.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "powershell")):
            with self.assertRaises(subprocess.CalledProcessError):
                direct.physical_interface()

    def test_https_rejects_embedded_credentials_before_network(self):
        with patch.object(direct, "direct_socket") as connect:
            with self.assertRaisesRegex(ValueError, "without embedded credentials"):
                direct.https_get("https://user:example@server.example/health")
        connect.assert_not_called()


class EditorialTransportTests(unittest.TestCase):
    def invoke(self, direct_enabled):
        environment = {"EDABALANS_SSH_DIRECT": "1"} if direct_enabled else {}
        with patch.dict(os.environ, environment, clear=True), \
             patch("tools.editorial_vault.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout='{"status":"ok"}')) as run:
            result = API().request("GET", "/admin/api/library/summary")
        self.assertEqual(result, {"status": "ok"})
        return run.call_args

    def test_normal_ssh_transport_is_unchanged_without_flag(self):
        call = self.invoke(False)
        self.assertEqual(call.args[0][:4], ["ssh", "-o", "BatchMode=yes", "edabalans-prod"])
        self.assertNotIn("ProxyCommand=", " ".join(call.args[0]))

    def test_direct_transport_keeps_alias_and_host_verification(self):
        call = self.invoke(True)
        command = call.args[0]
        self.assertEqual(command[-2], "edabalans-prod")
        self.assertTrue(any(arg.startswith("ProxyCommand=") and "edabalans_direct_ssh.py" in arg for arg in command))
        self.assertNotIn("StrictHostKeyChecking=no", " ".join(command))
        request = json.loads(call.kwargs["input"])
        self.assertEqual(request, {"method": "GET", "path": "/admin/api/library/summary", "payload": None})

    def test_direct_flag_uses_ssh_even_if_basic_environment_exists(self):
        with patch.dict(os.environ, {"EDABALANS_SSH_DIRECT": "1", "EDABALANS_ADMIN_USERNAME": "example", "EDABALANS_ADMIN_PASSWORD": "example"}, clear=True), \
             patch("tools.editorial_vault.urlopen") as https, \
             patch("tools.editorial_vault.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout='{"status":"ok"}')) as run:
            API().request("GET", "/admin/api/library/summary")
        https.assert_not_called()
        self.assertEqual(run.call_args.args[0][-2], "edabalans-prod")


if __name__ == "__main__":
    unittest.main()
