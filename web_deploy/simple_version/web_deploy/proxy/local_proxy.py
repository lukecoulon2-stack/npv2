import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _ProxyHandler(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 8000

    def _forward(self):
        connection = http.client.HTTPConnection(
            self.upstream_host, self.upstream_port, timeout=10
        )
        body = None
        length = self.headers.get("Content-Length")
        if length:
            try:
                size = int(length)
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return
            if size > 16 * 1024 * 1024:
                self.send_error(413, "Request body too large")
                return
            body = self.rfile.read(size)

        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "content-length")
        }
        headers["Host"] = f"{self.upstream_host}:{self.upstream_port}"

        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()

            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
        except (OSError, ConnectionError, TimeoutError) as exc:
            try:
                self.send_error(502, "Upstream server unavailable")
            except OSError:
                pass
        finally:
            connection.close()

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_PATCH(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def do_HEAD(self):
        self._forward()

    def log_message(self, fmt, *args):
        # Le proxy reste silencieux par défaut.
        pass


class LocalProxy:
    def __init__(self, listen_host, listen_port, target_host, target_port, log=print):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.log = log
        self.server = None

    def start(self):
        handler = type(
            "ConfiguredProxyHandler",
            (_ProxyHandler,),
            {
                "upstream_host": self.target_host,
                "upstream_port": self.target_port,
            }
        )
        self.server = ThreadingHTTPServer(
            (self.listen_host, self.listen_port), handler
        )
        self.server.daemon_threads = True
        self.server.allow_reuse_address = True

        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True, name="web-deployer-proxy").start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
