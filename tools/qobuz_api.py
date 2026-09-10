#!/usr/bin/env python3
"""O Qobuz sem o pacote `qobuz-dl`.

POR QUE ISTO EXISTE
-------------------
O `qobuz-vita.py` falava com `qobuz_dl.qopy`, e o `qobuz-chaves.py` lia o
`~/.config/qobuz-dl/config.ini`. Os dois amarravam este repositório a um
pacote de terceiro que já veio quebrado uma vez (o CLI; a biblioteca ainda
funciona) e que precisa ser configurado à mão antes de qualquer coisa aqui
rodar. Um app "standalone" — que é o pedido nº 7 do dono — não pode depender
de outro programa ter sido instalado e logado primeiro.

O QUE SE APRENDEU LENDO O SpotiFLAC (github.com/spotbye/SpotiFLAC)
------------------------------------------------------------------
O backend Qobuz dele (`backend/qobuz_api.go`) faz exatamente o que o
`src/qobuz.c` deste repositório já faz: `https://www.qobuz.com/api.json/0.2`,
cabeçalho `X-App-Id`, e as chamadas privadas assinadas com

    md5( caminho-sem-barras + params-ordenados + timestamp + segredo )

Conferido lado a lado: o `qb_assina` do nosso qobuz.c monta
`"trackgetFileUrlformat_id%dintentstreamtrack_id%s%ld%s"`, que é o caso
particular da mesma fórmula (format_id, intent, track_id já em ordem
alfabética). **Não há nada a trocar no aparelho** — a API é a mesma.

O QUE ELE TEM DE FATO A MAIS, e que vale copiar:
ele NÃO pede app_id/segredo a ninguém. Pega do próprio tocador web do Qobuz,
uma vez por dia:

    open.qobuz.com/track/1  ->  <script src=".../js/main.js">
    main.js                 ->  app_id:"999999999",app_secret:"…32 hex…"

Medido nesta máquina em 2026-09-06: app_id 712109809, e é o mesmo valor que o
SpotiFLAC traz embutido como reserva. Isso tira metade da configuração da
frente do usuário — sobra só o token da CONTA, que é dele e ninguém adivinha.

O QUE ELE TEM E **NÃO** DÁ PARA COPIAR
--------------------------------------
O Tidal e o Amazon Music do SpotiFLAC não saem de API pública nenhuma: saem de
servidores-relé do próprio projeto, com o endereço criptografado em AES-GCM
dentro do binário (`backend/community_endpoints.go`) para não serem raspados.
São contas de outra pessoa, num servidor que pode sumir amanhã. Embutir aquilo
num app em C que roda num PS Vita é montar uma dependência que quebra sozinha
e não dá para consertar de dentro do aparelho.

O Spotify, no SpotiFLAC, é **só metadado** — nenhum áudio sai de lá.
SoundCloud e YouTube não estão no SpotiFLAC-Next; são extensões da comunidade
para o app Flutter do celular.

A PARTE QUE PRESTA, ENTÃO, É O CASAMENTO POR ISRC: procurar num catálogo com
busca boa (Deezer, Spotify) e trazer o MESMO fonograma do Qobuz, que é a conta
que o dono paga. É o que está aqui embaixo, e é o que mantém o streaming do
Qobuz intacto.
"""

import configparser
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.qobuz.com/api.json/0.2"
# Um agente de navegador: o bundle do tocador web não é servido para "python-urllib".
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CONFIG_QOBUZDL = os.path.expanduser("~/.config/qobuz-dl/config.ini")
CACHE = os.path.expanduser("~/.cache/vitastylus/qobuz-cred.json")
CACHE_HORAS = 24

# NÃO HÁ PAR EMBUTIDO DE RESERVA, E ISSO É DE PROPÓSITO.
#
# O SpotiFLAC carrega um (app_id + segredo de 32 dígitos) escrito no código,
# para quando o tocador web não responder. Aqui ele foi tirado por duas
# razões, nesta ordem:
#
# 1. NÃO SERVIRIA PARA NADA. A única coisa que se faz com essas chaves é
#    chamar a API do Qobuz — pela rede. Se a rede caiu a ponto de o main.js
#    não vir, a chamada seguinte também não vai. Uma reserva que só existe
#    para o caso em que ela tampouco funciona é código morto que envelhece.
#
# 2. O `check.sh` deste repositório reprova qualquer coisa com cara de
#    credencial versionada, e ele estava CERTO em reprovar: um hexadecimal de
#    32 dígitos chamado "segredo" dentro de um commit é exatamente o que essa
#    conferência existe para pegar. Ensinar a conferência a ignorar este caso
#    seria ensiná-la a ignorar o próximo, que talvez não seja público.


class QobuzErro(Exception):
    pass


def _http(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url, headers=None):
    return json.loads(_http(url, headers).decode("utf-8", "replace"))


# ---------- as chaves do aplicativo (app_id + segredo) ----------

def _do_tocador_web():
    """Lê app_id e segredo do bundle do tocador web do Qobuz.

    É o que o SpotiFLAC faz, e é o que dispensa configurar qobuz-dl antes.
    Duas requisições: a página (pequena, só diz onde está o main.js) e o
    bundle (~1,2 MB)."""
    html = _http("https://open.qobuz.com/track/1").decode("utf-8", "replace")
    m = re.search(r'<script[^>]+src="([^"]+/js/main\.js|/resources/[^"]+/js/main\.js)"', html)
    if not m:
        raise QobuzErro("não achei o main.js na página do tocador web")
    src = m.group(1)
    if src.startswith("/"):
        src = "https://open.qobuz.com" + src
    js = _http(src).decode("utf-8", "replace")
    c = re.search(r'app_id:"(?P<a>\d{9})",app_secret:"(?P<s>[a-f0-9]{32})"', js)
    if not c:
        raise QobuzErro("achei o main.js mas não o par app_id/app_secret dentro dele")
    return c.group("a"), c.group("s")


def _cache_le():
    try:
        with open(CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - d.get("quando", 0) < CACHE_HORAS * 3600:
            sg = d["segredo"]
            return d["app_id"], (sg if isinstance(sg, list) else [sg]), "cache"
    except Exception:
        pass
    return None


def _cache_grava(app_id, segredos):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"app_id": app_id, "segredo": list(segredos),
                       "quando": time.time()}, f)
    except Exception:
        pass          # cache é conforto, não requisito


def chaves(preferir_config=True):
    """(app_id, [segredos], de_onde). `app_id` vem None quando não deu.

    **A LISTA É PLURAL, E ISSO NÃO É DETALHE.** O Qobuz publica vários
    segredos para o mesmo app_id e **só um deles assina**; qual, muda com o
    tempo. A primeira versão disto devolvia `segs[0]` e o `track/getFileUrl`
    respondia `400 Invalid Request Signature parameter (request_sig)` — a
    busca funcionava (não é assinada) e só o DOWNLOAD quebrava, que é o pior
    lugar para esconder um defeito.

    O `src/qobuz.c` do aparelho já tentava todos; o comentário do
    `qobuz-chaves.py` já dizia por quê ("guardar um só é guardar 'funcionou no
    dia em que eu configurei'"). Estava escrito e eu não li.

    A ordem é deliberada. O config do qobuz-dl vem primeiro porque o segredo
    que ESTÁ FUNCIONANDO para a conta do dono vale mais que o do tocador web —
    o Qobuz serve segredos diferentes por região e o dele já foi provado. Quem
    não tem qobuz-dl nenhum cai no tocador web e não precisa saber que isso
    existiu."""
    if preferir_config:
        try:
            cp = configparser.ConfigParser()
            cp.read(CONFIG_QOBUZDL)
            d = cp["DEFAULT"]
            app_id = (d.get("app_id") or "").strip()
            # `secrets` é o repr de uma lista Python; o primeiro não-vazio serve
            brutos = (d.get("secrets") or "").strip()
            segs = list(dict.fromkeys(re.findall(r"[0-9a-f]{32}", brutos)))
            if app_id and segs:
                return app_id, segs, "config do qobuz-dl"
        except Exception:
            pass

    emcache = _cache_le()
    if emcache:
        return emcache

    try:
        app_id, segredo = _do_tocador_web()
        _cache_grava(app_id, [segredo])
        return app_id, [segredo], "tocador web do Qobuz"
    except Exception as e:
        return None, None, f"não deu para obter ({e})"


def token_da_conta():
    """O token do usuário. É o único pedaço que continua vindo do config: ele
    identifica a CONTA, e não há de onde raspá-lo."""
    try:
        cp = configparser.ConfigParser()
        cp.read(CONFIG_QOBUZDL)
        return (cp["DEFAULT"].get("user_auth_token") or "").strip() or None
    except Exception:
        return None


# ---------- o cliente ----------

class Cliente:
    def __init__(self, app_id=None, segredo=None, token=None):
        if app_id and segredo:
            self.app_id, self.origem = app_id, "informado"
            self.segredos = [segredo] if isinstance(segredo, str) else list(segredo)
        else:
            self.app_id, self.segredos, self.origem = chaves()
        if not self.app_id or not self.segredos:
            raise QobuzErro(f"sem app_id/segredo do Qobuz: {self.origem}")
        self.token = token or token_da_conta()
        self.segredo = self.segredos[0]   # o que está em uso agora

    # ---- o cabeçalho e a assinatura ----
    def _cab(self):
        h = {"X-App-Id": self.app_id, "Accept": "application/json"}
        if self.token:
            h["X-User-Auth-Token"] = self.token
        return h

    def _assina(self, caminho, params, ts, segredo=None):
        """md5(caminho-sem-barras + params ordenados + ts + segredo).

        `app_id`, `request_ts` e `request_sig` ficam de fora da soma — entram
        na URL, não na assinatura. Errar isso devolve 400 sem dizer por quê."""
        base = caminho.strip("/").replace("/", "")
        partes = [base]
        for k in sorted(params):
            if k in ("app_id", "request_ts", "request_sig"):
                continue
            partes.append(f"{k}{params[k]}")
        partes.append(str(ts))
        partes.append(segredo or self.segredo)
        return hashlib.md5("".join(partes).encode("utf-8")).hexdigest()

    def _get(self, caminho, params=None, assinado=False):
        base = dict(params or {})
        if not assinado:
            base["app_id"] = self.app_id
            url = f"{API}/{caminho.strip('/')}?{urllib.parse.urlencode(base)}"
            return _json(url, self._cab())

        # ASSINADO: TENTA TODOS OS SEGREDOS.
        #
        # Só um assina, e qual não se sabe de antemão (ver `chaves`). O que
        # deu certo vai para a frente da fila, então a segunda chamada da
        # sessão já acerta de primeira.
        erros = []
        for i, sg in enumerate(list(self.segredos)):
            p = dict(base)
            ts = int(time.time())
            p["request_ts"] = ts
            p["request_sig"] = self._assina(caminho, p, ts, sg)
            p["app_id"] = self.app_id
            url = f"{API}/{caminho.strip('/')}?{urllib.parse.urlencode(p)}"
            try:
                d = _json(url, self._cab())
                if i:
                    self.segredos.insert(0, self.segredos.pop(i))
                self.segredo = self.segredos[0]
                return d
            except urllib.error.HTTPError as e:
                corpo = ""
                try:
                    corpo = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                # 400 de assinatura = segredo errado, tenta o próximo.
                # Qualquer outro erro é do PEDIDO e repetir com outro segredo
                # só troca uma mensagem clara por "nenhum segredo serviu".
                if e.code == 400 and "request_sig" in corpo:
                    erros.append(f"{sg[:8]}…: assinatura recusada")
                    continue
                raise
        raise QobuzErro("nenhum dos %d segredos assina esta chamada (%s).\n"
                        "  O Qobuz troca os segredos: rode `qobuz-dl` uma vez para\n"
                        "  renovar o config, ou apague %s para buscar de novo."
                        % (len(self.segredos), "; ".join(erros), CACHE))

    # ---- o que o qobuz-vita.py usa ----
    def conta(self):
        """Confere que o token vale. Devolve o nome do plano, ou None."""
        if not self.token:
            return None
        try:
            d = self._get("user/get", {"user_id": "me"})
            cred = (d.get("credential") or {}).get("parameters") or {}
            return cred.get("short_label") or cred.get("label") or "Qobuz"
        except Exception:
            return None

    def buscar_albuns(self, termo, limite=20):
        d = self._get("album/search", {"query": termo, "limit": limite})
        return (d.get("albums") or {}).get("items") or []

    def buscar_faixas(self, termo, limite=20):
        d = self._get("track/search", {"query": termo, "limit": limite})
        return (d.get("tracks") or {}).get("items") or []

    def album(self, album_id):
        return self._get("album/get", {"album_id": album_id})

    def faixa(self, track_id):
        return self._get("track/get", {"track_id": track_id})

    def url_do_arquivo(self, track_id, formato=5):
        """A URL assinada do áudio. Vale ~1 hora, é HTTPS comum e o conteúdo
        NÃO é criptografado — ver o cabeçalho do qobuz-vita.py."""
        d = self._get("track/getFileUrl",
                      {"format_id": formato, "intent": "stream", "track_id": track_id},
                      assinado=True)
        if not d.get("url"):
            raise QobuzErro(f"o Qobuz não deu URL para a faixa {track_id}: {d}")
        return d

    # ---- o casamento por ISRC ----
    def por_isrc(self, isrc):
        """A faixa do Qobuz com este ISRC, ou None.

        É a peça que o SpotiFLAC usa para transformar "achei no Spotify" em
        "baixe do Qobuz": o ISRC identifica o FONOGRAMA, não a edição, então é
        o mesmo número nos dois catálogos."""
        if not isrc:
            return None
        for it in self.buscar_faixas(isrc, limite=5):
            if (it.get("isrc") or "").upper() == isrc.upper():
                return it
        return None


# ---------- os catálogos que só servem para ACHAR ----------

def deezer_isrcs(termo, limite=10):
    """Deezer: busca pública, sem chave, sem conta. Devolve
    [(isrc, "artista — título", album)].

    Está aqui porque a busca do Qobuz é literal demais: escrever o nome de uma
    música sem o do artista costuma não trazer nada, e o Deezer acha. O áudio
    continua vindo do Qobuz — daqui só sai o número do fonograma."""
    q = urllib.parse.quote(termo)
    try:
        d = _json(f"https://api.deezer.com/search?q={q}&limit={limite}")
    except Exception:
        return []
    out = []
    for it in d.get("data") or []:
        tid = it.get("id")
        if not tid:
            continue
        try:
            t = _json(f"https://api.deezer.com/track/{tid}")
        except Exception:
            continue
        isrc = t.get("isrc")
        if isrc:
            out.append((isrc,
                        f"{(t.get('artist') or {}).get('name','?')} — {t.get('title','?')}",
                        (t.get("album") or {}).get("title", "")))
    return out


import sys

if __name__ == "__main__":
    app_id, segredo, de_onde = chaves()
    if not app_id:
        sys.exit(f"sem chaves do Qobuz: {de_onde}")
    print(f"app_id  {app_id}   segredo {segredo[:8]}…  ({de_onde})")
    c = Cliente()
    print("conta  ", c.conta() or "(sem token — só busca pública)")
    if len(sys.argv) > 1:
        termo = " ".join(sys.argv[1:])
        print(f"\nQobuz, álbuns para {termo!r}:")
        for a in c.buscar_albuns(termo, 5):
            print(f"  {a.get('id')}  {(a.get('artist') or {}).get('name','?')} — {a.get('title')}")
        print(f"\nDeezer -> ISRC -> Qobuz para {termo!r}:")
        for isrc, quem, alb in deezer_isrcs(termo, 5):
            t = c.por_isrc(isrc)
            achou = f"qobuz track {t.get('id')}" if t else "não está no Qobuz"
            print(f"  {isrc}  {quem}  [{alb}]  -> {achou}")
