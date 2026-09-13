#!/usr/bin/env python3
#
# A deliberately hostile map data server for tests/mapdata/run.sh.
#
# A map names the URL of its data package and the client fetches it, so the
# URL and everything behind it are chosen by whichever server a player joins.
# This serves one honest package behind a redirect -- which is what the real
# mirror does -- and a set of packages and responses built to break the
# client: an oversized file name, path traversal with either separator, a
# decompression bomb, a redirect to file://, an error page, a lying
# Content-Length and a truncated download.
#
#   serve.py PORT GOOD_PACKAGE
#
# Prints "ready" once it is listening.

import gzip
import http.server
import sys


def package(entries):
    body = b"XPD %d\n" % len(entries)
    for name, data in entries:
        body += name + b" %d\n" % len(data) + data
    return gzip.compress(body)


def main():
    port = int(sys.argv[1])
    good = open(sys.argv[2], "rb").read()

    packages = {
        "/real/good.xpd": good,
        "/maps/longname.xpd": package([(b"A" * 1000, b"hello")]),
        "/maps/dotdot.xpd": package([(b"../escaped.txt", b"pwned")]),
        "/maps/backslash.xpd": package([(b"..\\escaped.txt", b"pwned")]),
        "/maps/bomb.xpd": package([(b"big.bin", b"\0" * (100 * 1024 * 1024))]),
        "/maps/truncated.xpd":
            gzip.compress(b"XPD 1\ntex.ppm 100000\n" + b"x" * 500)[:-12],
    }
    redirects = {
        "/maps/good.xpd": "/real/good.xpd",
        "/maps/tofile.xpd": "file:///etc/passwd",
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path
            if path in redirects:
                self.send_response(301)
                self.send_header("Location", redirects[path])
                self.end_headers()
            elif path in packages:
                data = packages[path]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path == "/maps/huge.xpd":
                self.send_response(200)
                self.send_header("Content-Length", str(100 * 1024 * 1024))
                self.end_headers()
                self.wfile.write(b"x" * 4096)
            else:
                body = b"<html>404 not found</html>"
                self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print("ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
