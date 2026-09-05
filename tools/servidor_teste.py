#!/usr/bin/env python3
"""Servidor de mentira para o teste de tocar pela rede.

Serve as fixtures normalmente E, no caminho /cai/<arquivo>, promete um
Content-Length inteiro e FECHA no meio. Isso existe porque a diferenca entre
"a faixa acabou" e "a rede caiu" e a coisa mais facil de confundir num
tocador que le da rede — e confundir faz um disco "terminar" sozinho quando
o Wi-Fi pisca, que e o jeito mais confuso possivel de falhar.
"""
import os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = sys.argv[2] if len(sys.argv) > 2 else "/tmp/vitastylus_fixtures"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        cai = self.path.startswith("/cai/")
        nome = os.path.basename(self.path)
        caminho = os.path.join(RAIZ, nome)
        if not os.path.isfile(caminho):
            self.send_error(404)
            return
        dados = open(caminho, "rb").read()

        faixa = self.headers.get("Range")
        inicio = 0
        if faixa and faixa.startswith("bytes="):
            try:
                inicio = int(faixa[6:].split("-")[0])
            except ValueError:
                inicio = 0

        corpo = dados[inicio:]
        self.send_response(206 if inicio else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(corpo)))
        if inicio:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (inicio, len(dados) - 1, len(dados)))
        self.end_headers()
        if cai:
            # promete tudo, entrega um terco, e some
            self.wfile.write(corpo[: len(corpo) // 3])
            self.wfile.flush()
            self.close_connection = True
            try:
                self.connection.close()
            except OSError:
                pass
            return
        self.wfile.write(corpo)


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8731
    srv = ThreadingHTTPServer(("127.0.0.1", porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("servindo %s em %d" % (RAIZ, porta), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
