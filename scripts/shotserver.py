# Tiny helper for headless screenshots: serves a wrapper page that iframes the
# dashboard and holds the page "load" event open with a slow image, so Firefox
# --screenshot captures after the dashboard's data and icons have arrived.
import http.server, time, sys

DELAY = 9  # seconds to wait before the wrapper finishes loading
URL = sys.argv[2] if len(sys.argv) > 2 else "http://192.168.1.14:3001/"  # page to capture

PAGE = f"""<!doctype html><html><head><style>
html,body{{margin:0;height:100%;overflow:hidden}}
iframe{{border:0;width:100%;height:100%}}
</style></head><body>
<iframe src="{URL}"></iframe>
<img src="/slow.gif" style="position:absolute;width:1px;height:1px;opacity:0">
</body></html>"""

GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow.gif"):
            time.sleep(DELAY)
            body, ctype = GIF, "image/gif"
        else:
            body, ctype = PAGE.encode(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


port = int(sys.argv[1]) if len(sys.argv) > 1 else 18999
http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
