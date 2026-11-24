"""Unit tests for POST /api/v1/pick-folder route."""
import subprocess
import sys
from unittest import mock
from sv_helpers import SV, Http


class TestPickFolder(SV):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.serve()
        self.url = "/api/v1/pick-folder"

    def test_pick_folder_zenity_success(self):
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/zenity" if cmd == "zenity" else None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/user/project\n", stderr="")
                    r = self.http.post(self.url, {})
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.json, {"path": "/home/user/project"})
                    self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 600)

    def test_pick_folder_zenity_cancelled(self):
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/zenity" if cmd == "zenity" else None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
                    r = self.http.post(self.url, {})
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.json, {"path": None})
                    self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 600)

    def test_pick_folder_kdialog_fallback(self):
        def fake_which(cmd):
            return "/usr/bin/kdialog" if cmd == "kdialog" else None

        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            with mock.patch("shutil.which", side_effect=fake_which):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/user/kproj\n", stderr="")
                    r = self.http.post(self.url, {})
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.json, {"path": "/home/user/kproj"})
                    self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 600)

    def test_pick_folder_linux_no_display_gives_501(self):
        with mock.patch("sys.platform", "linux"):
            with mock.patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                with mock.patch("shutil.which", return_value="/usr/bin/zenity"):
                    with mock.patch("subprocess.run") as mock_run:
                        r = self.http.post(self.url, {})
                        self.assertEqual(r.status, 501)
                        self.assertEqual(r.code, "E_UNAVAILABLE")
                        self.assertEqual(r.json["error"]["message"], "no desktop session for a folder dialog")
                        mock_run.assert_not_called()

    def test_pick_folder_error_returncode_gives_501(self):
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/zenity" if cmd == "zenity" else None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="dialog error")
                    r = self.http.post(self.url, {})
                    self.assertEqual(r.status, 501)
                    self.assertEqual(r.code, "E_UNAVAILABLE")
                    self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 600)

    def test_pick_folder_macos_osascript(self):
        with mock.patch("sys.platform", "darwin"):
            with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/osascript" if cmd == "osascript" else None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="/Users/alice/repo/\n", stderr="")
                    r = self.http.post(self.url, {})
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.json, {"path": "/Users/alice/repo"})

    def test_pick_folder_unavailable_gives_501(self):
        with mock.patch("shutil.which", return_value=None):
            r = self.http.post(self.url, {})
            self.assertEqual(r.status, 501)
            self.assertEqual(r.code, "E_UNAVAILABLE")

    def test_pick_folder_auth_and_csrf_required(self):
        P = self.srv.port
        anon = Http(P)
        r1 = anon.post(self.url, {}, cookie=False)
        self.assertEqual(r1.status, 401)
        self.assertEqual(r1.code, "E_AUTH")

        r2 = self.http.post(self.url, {}, csrf=False)
        self.assertEqual(r2.status, 403)
        self.assertEqual(r2.code, "E_CSRF")
