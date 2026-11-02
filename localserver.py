"""Tiny localhost HTTP server for the UI (issue #5).

Why: YouTube embeds fail with Error 153 when the page sends no referrer, which is what a file:// page does.
Serving the UI from http://127.0.0.1:<random port> fixes that, and also lets the media tile show the user's own
images/videos (copied into PREFS_DIR/media) without file:// cross-origin trouble.

Bound to 127.0.0.1 only, random port, GET/HEAD only, and every path is resolved and checked to stay inside its
root (no ../ escapes).
"""
import functools
import http.server
import mimetypes
import os
import threading
import urllib.parse

mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")


def _inside(root, rel):
    """Absolute path of rel under root, or None if it would escape root."""
    root = os.path.realpath(root)
    p = os.path.realpath(os.path.join(root, rel.lstrip("/\\")))
    return p if p == root or p.startswith(root + os.sep) else None


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, ui_dir, media_dir, **kw):
        self.ui_dir, self.media_dir = ui_dir, media_dir
        super().__init__(*a, directory=ui_dir, **kw)

    def translate_path(self, path):
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if path.startswith("/media/"):
            return _inside(self.media_dir, path[len("/media/"):]) or os.path.join(self.ui_dir, ".blocked", "none")
        return _inside(self.ui_dir, path) or os.path.join(self.ui_dir, ".blocked", "none")  # -> 404

    def list_directory(self, path):  # never list folders
        self.send_error(404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always fresh UI after an update
        super().end_headers()

    def log_message(self, *a):  # quiet
        pass


class LocalServer:
    def __init__(self, ui_dir, media_dir):
        os.makedirs(media_dir, exist_ok=True)
        handler = functools.partial(_Handler, ui_dir=ui_dir, media_dir=media_dir)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="ui-server").start()

    def stop(self):
        self.httpd.shutdown()


if __name__ == "__main__":
    import tempfile
    import urllib.error
    import urllib.request

    with tempfile.TemporaryDirectory() as tmp:
        ui, media = os.path.join(tmp, "ui"), os.path.join(tmp, "media")
        os.makedirs(ui)
        open(os.path.join(ui, "index.html"), "w").write("<h1>ok</h1>")
        open(os.path.join(tmp, "secret.txt"), "w").write("nope")
        s = LocalServer(ui, media)
        open(os.path.join(media, "a.png"), "wb").write(b"\x89PNG")

        def get(path):
            try:
                with urllib.request.urlopen(s.url + path) as r:
                    return r.status, r.read(), r.headers.get("Content-Type")
            except urllib.error.HTTPError as e:
                return e.code, b"", None

        assert get("/index.html")[:2] == (200, b"<h1>ok</h1>")
        assert get("/media/a.png")[0] == 200 and get("/media/a.png")[2] == "image/png"
        for bad in ("/../secret.txt", "/%2e%2e/secret.txt", "/media/../../secret.txt", "/media/%2e%2e%2fsecret.txt", "/media/"):  # traversal + no folder listing
            assert get(bad)[0] == 404, bad
        assert get("/")[0] == 200  # root serves index.html
        assert s.httpd.server_address[0] == "127.0.0.1"
        s.stop()
    print("ok")
