import http.server, functools, sys
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.wasm':'application/wasm', '.js':'text/javascript'}
    def do_GET(self):
        if self.path.startswith('/data/__index'):
            b=b'[]'; self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        if self.path.startswith('/data/') or self.path.startswith('/ws/'):
            self.send_error(404); return
        return super().do_GET()
    def do_HEAD(self):
        if self.path.startswith('/data/'): self.send_error(404); return
        return super().do_HEAD()
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(('127.0.0.1',8091), functools.partial(H, directory=sys.argv[1])).serve_forever()
