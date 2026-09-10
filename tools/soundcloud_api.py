#!/usr/bin/env python3
"""SoundCloud: buscar e baixar, sem conta e sem relé de ninguém.

DE ONDE VEIO
------------
Da extensão `soundcloud.sflx` do **SpotiFLAC Mobile**
(github.com/spotiflacapp/SpotiFLAC-Extension). Uma sessão anterior — esta
mesma — disse que SoundCloud e YouTube "não estão no SpotiFLAC" e que os
serviços extras dependiam de servidores-relé com endereço criptografado.
**Estava errado, e o dono estava certo: ele tem tudo isso funcionando no
celular.**

O engano foi ler o app de DESKTOP (spotbye/SpotiFLAC, em Go), onde os
endereços de Tidal e Amazon estão mesmo em AES-GCM dentro do binário, e
concluir dali sobre o app do CELULAR, que é outra coisa: extensões `.sflx`,
que são ZIPs com um `manifest.json` e um `index.js` legível. O manifesto de
cada uma DECLARA os domínios que ela usa. Lê-se em dois minutos.

E o que ele declara para o SoundCloud é: **nada de relé.**

    "network": ["soundcloud.com", "api-v2.soundcloud.com",
                "*.sndcdn.com", "on.soundcloud.com", "m.soundcloud.com"]

Só a API pública. (Para comparar: a extensão do YouTube usa
`api.zarz.moe/v1/dl/cobalt` — que é uma instância do **Cobalt**, projeto
aberto e hospedável por qualquer um; e a do Qobuz usa `api.zarz.moe/v2/qbz`
para quem NÃO tem conta, coisa que aqui não é preciso: o dono tem a dele, e o
`qobuz_api.py` fala direto com o Qobuz.)

O CAMINHO, INTEIRO
------------------
1. `client_id`: não há registro nem chave. Ele está nos bundles JS do próprio
   site. Pega-se de `soundcloud.com`, guarda-se por 24 h. **É exatamente o
   mesmo truque do app_id do Qobuz** no `qobuz_api.py` ao lado — os dois sites
   publicam a credencial do aplicativo no JavaScript que servem ao navegador.
2. buscar: `api-v2.soundcloud.com/search/tracks?q=…&client_id=…`
3. a faixa traz `media.transcodings[]`. Pega-se a de `protocol == "progressive"`
   (as `hls` são playlist, não arquivo) e que NÃO seja `snipped` (prévia de
   30 s).
4. `GET <transcoding.url>?client_id=…&track_authorization=…` devolve
   `{"url": "https://cf-media.sndcdn.com/….mp3"}`.
5. baixa esse MP3.

POR QUE ISTO SERVE AO VITA MELHOR DO QUE PARECE
-----------------------------------------------
O SoundCloud entrega **MP3 128 kbps a 44,1 kHz**. Num tocador de PS Vita isso
não é o prêmio de consolação, é quase o formato ideal:
  - 44,1 kHz passa no teto de 47999 Hz do SDL2, que é o que mantém o som vivo
    na porta BGM (ver a nota do decoder.c);
  - 128 kbps é ~1 MB por minuto, e o orçamento do cartão é 1,5 GB;
  - o `src/decoder.c` já toca MP3 — não há formato novo a suportar.
E o acervo do SoundCloud tem o que o Qobuz não tem: remix, set, demo, coisa
que nunca foi lançada.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SC = "https://api-v2.soundcloud.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CACHE = os.path.expanduser("~/.cache/vitastylus/soundcloud-cid.json")
CACHE_HORAS = 24


class ScErro(Exception):
    pass


def _http(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url, headers=None):
    return json.loads(_http(url, headers).decode("utf-8", "replace"))


# ---------- o client_id ----------

def _do_site():
    """Acha o client_id nos bundles do soundcloud.com.

    Dois caminhos, como na extensão: primeiro direto no HTML (às vezes está
    lá), senão nos `<script src>` — de trás para a frente, porque ele costuma
    estar nos últimos."""
    html = _http("https://soundcloud.com/").decode("utf-8", "replace")

    m = re.search(r'client_id[:=]["\']([a-zA-Z0-9]{32})["\']', html)
    if m:
        return m.group(1)

    bundles = re.findall(r'<script[^>]+src="(https://[^"]+\.js)"', html)
    for src in reversed(bundles):
        try:
            js = _http(src).decode("utf-8", "replace")
        except Exception:
            continue
        m = re.search(r'client_id[:=]["\']([a-zA-Z0-9]{32})["\']', js)
        if m:
            return m.group(1)
    raise ScErro("não achei o client_id nos bundles do soundcloud.com")


def client_id():
    """O client_id, do cache de 24 h ou do site. Levanta se não der."""
    try:
        with open(CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - d.get("quando", 0) < CACHE_HORAS * 3600 and d.get("cid"):
            return d["cid"]
    except Exception:
        pass
    cid = _do_site()
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"cid": cid, "quando": time.time()}, f)
    except Exception:
        pass          # cache é conforto, não requisito
    return cid


# ---------- a API ----------

def _get(caminho, params=None, cid=None):
    p = dict(params or {})
    p["client_id"] = cid or client_id()
    return _json(f"{SC}/{caminho.lstrip('/')}?{urllib.parse.urlencode(p)}")


def buscar(termo, limite=15, cid=None):
    """[(id, artista, título, segundos, baixável)].

    `baixável` sai da PRÓPRIA resposta da busca, e é por isso que vale a pena:
    a primeira coisa que o SoundCloud devolve para "aphex twin avril 14" é a
    faixa oficial da gravadora com `policy: SNIP` — trinta segundos de prévia.
    Descobrir isso só na hora de baixar é fazer a pessoa escolher no escuro e
    receber silêncio com nome de música."""
    d = _get("search/tracks", {"q": termo, "limit": limite}, cid)
    out = []
    for t in d.get("collection") or []:
        if t.get("kind") != "track":
            continue
        tr = ((t.get("media") or {}).get("transcodings")) or []
        ok = any((x.get("format") or {}).get("protocol") == "progressive"
                 and not x.get("snipped") for x in tr)
        out.append((t.get("id"),
                    (t.get("user") or {}).get("username") or "?",
                    t.get("title") or "?",
                    int((t.get("duration") or 0) / 1000),
                    ok and (t.get("policy") or "") != "SNIP"))
    return out


def faixa(track_id, cid=None):
    d = _get(f"tracks/{track_id}", None, cid)
    return d[0] if isinstance(d, list) else d


def _escolhe_transcodificacao(tr, prefere="mp3"):
    """A `progressive` que der: `hls` é playlist, não arquivo, e `snipped` é
    a prévia de trinta segundos — baixar qualquer uma das duas é entregar
    silêncio com nome de música."""
    cands = []
    for t in tr or []:
        if t.get("snipped"):
            continue
        fmt = t.get("format") or {}
        if (fmt.get("protocol") or "") != "progressive":
            continue
        mime = (fmt.get("mime_type") or "").lower()
        # mp3 primeiro: o decoder do Vita toca os dois, mas o opus do
        # SoundCloud vem em .ogg a 64 kbps — metade do bitrate.
        cands.append((0 if "mpeg" in mime or "mp3" in mime else 1, t))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0][1]


def url_do_audio(track_id, cid=None):
    """(url_direta, extensão). A URL do sndcdn vale poucos minutos."""
    cid = cid or client_id()
    t = faixa(track_id, cid)
    tr = ((t.get("media") or {}).get("transcodings")) or []
    auth = t.get("track_authorization") or ""
    if not tr or not auth:
        raise ScErro(f"a faixa {track_id} não expõe stream progressivo "
                     f"(faixa paga, privada ou só HLS)")
    esc = _escolhe_transcodificacao(tr)
    if not esc:
        raise ScErro(f"a faixa {track_id} só tem HLS ou prévia — sem arquivo direto")
    u = esc["url"]
    u += ("&" if "?" in u else "?") + urllib.parse.urlencode(
        {"client_id": cid, "track_authorization": auth})
    d = _json(u, {"Accept": "application/json"})
    if not d.get("url"):
        raise ScErro(f"o SoundCloud não devolveu URL para {track_id}: {d}")
    mime = ((esc.get("format") or {}).get("mime_type") or "").lower()
    ext = "mp3" if ("mpeg" in mime or "mp3" in mime) else ("opus" if "opus" in mime else "ogg")
    return d["url"], ext


if __name__ == "__main__":
    cid = client_id()
    print(f"client_id {cid[:8]}…  ({len(cid)} chars)")
    termo = " ".join(sys.argv[1:]) or "radiohead"
    print(f"\nbusca {termo!r}:")
    achadas = buscar(termo, 6, cid)
    for tid, quem, tit, seg, ok in achadas:
        print(f"  {'ok ' if ok else 'SNIP'} {tid:<12} {seg // 60}:{seg % 60:02d}  {quem} — {tit}")
    baixaveis = [a for a in achadas if a[4]]
    if baixaveis:
        tid = baixaveis[0][0]
        try:
            u, ext = url_do_audio(tid, cid)
            print(f"\nstream da primeira ({tid}): .{ext}  {u[:78]}…")
        except ScErro as e:
            print(f"\nstream da primeira: {e}")
