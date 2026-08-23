#!/usr/bin/env python3
"""Render ritual mode's composition to a PNG without OpenGL, audio, or a window.

Same reasoning as offline_render.py: "does this look right" is a question you
have to actually look at, and looking at it should not require taking over
Davi's real desktop or him being at it. This drives the REAL geometry
builders in vinyl.py (disc_body, groove_rings, tonearm, wear_marks, ...) so
the picture here and the picture on the GPU come from one source.

What it approximates rather than reproduces: the GPU's Gaussian beam
cross-section, additive phosphor accumulation, the bloom chain, and the CRT
composite (barrel, scanlines, grain). It is a composition and colour check —
where things sit, how big they are, whether the record reads as an object —
not a pixel-accurate preview.

  ./venv/bin/python tools/vinyl_preview.py --album "~/Music/…" --at 0.42
  ./venv/bin/python tools/vinyl_preview.py --album ... --contact   # phase strip
"""
import argparse
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vinyl  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vinyl-out")
SS = 2  # supersample factor for cheap anti-aliasing


def _to_px(pts, W, H):
    """NDC -> pixel coords for PIL (y flipped)."""
    p = np.asarray(pts, dtype=np.float64)
    x = (p[:, 0] * 0.5 + 0.5) * W
    y = (1.0 - (p[:, 1] * 0.5 + 0.5)) * H
    return np.stack([x, y], axis=1)


def _c(rgb, mul=1.0):
    return tuple(int(np.clip(v * mul, 0, 1) * 255) for v in rgb[:3])


def draw_strip(dr, pts, cols, width_px, W, H, chunk=16):
    """Polyline with per-vertex colour, chunked so gradients survive."""
    px = _to_px(pts, W, H)
    n = len(px)
    if n < 2:
        return
    w = max(1, int(round(width_px * 2)))
    for i in range(0, n - 1, chunk):
        j = min(n, i + chunk + 1)
        seg = [tuple(v) for v in px[i:j]]
        if len(seg) < 2:
            continue
        col = cols[min(i + chunk // 2, n - 1)]
        dr.line(seg, fill=_c(col), width=w, joint="curve")


def draw_fill(img, verts, W, H):
    """Triangle-strip fill (the vinyl body), drawn as quads."""
    dr = ImageDraw.Draw(img)
    px = _to_px(verts[:, 0:2], W, H)
    cols = verts[:, 2:5]
    for i in range(0, len(px) - 3, 2):
        quad = [tuple(px[i]), tuple(px[i + 2]), tuple(px[i + 3]), tuple(px[i + 1])]
        dr.polygon(quad, fill=_c(cols[i]))


def draw_segments(dr, segs, cols, W, H, width_px=1.0):
    px = _to_px(segs, W, H)
    w = max(1, int(round(width_px * 2)))
    for k in range(len(cols)):
        dr.line([tuple(px[2 * k]), tuple(px[2 * k + 1])], fill=_c(cols[k]), width=w)


def label_image(cover_path, size, rotation):
    if not cover_path or not os.path.isfile(cover_path):
        return None
    try:
        im = Image.open(cover_path).convert("RGB")
    except Exception:
        return None
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                  (im.width + side) // 2, (im.height + side) // 2))
    im = im.resize((size, size), Image.LANCZOS)
    im = im.rotate(-math.degrees(rotation), resample=Image.BICUBIC)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    im.putalpha(mask)
    return im


def render(album, progress, W=2560, H=1600, rotation=None, lift=0.0, arm_radius=None,
           show_text=True, crackle=0.0):
    w, h = W * SS, H * SS
    iso = (min(1.0, H / W), min(1.0, W / H))
    # The deck is bigger than the record: the arm's pivot sits 212mm from the
    # spindle on a 152mm record, so a disc drawn to fill the frame pushes the
    # pivot and its counterweight off the corner — which is exactly what it
    # used to do, and the arm read as a stray line leaving the picture. Pull
    # back and sit the record down-left so the whole instrument is in frame,
    # with the arm sweeping in from the upper right the way you'd see it
    # standing over a turntable.
    cx, cy = -0.10, -0.10
    radius = 0.76
    light = math.radians(-38.0)
    rot = rotation if rotation is not None else (progress * 400.0) % (2 * math.pi)

    img = Image.new("RGB", (w, h), (7, 9, 13))

    side_idx, side = album.side_for(progress * album.total) if album.total else (0, None)
    if side is None:
        side = {"label": "SIDE A", "start": 0.0, "end": 1.0, "tracks": []}
    t_abs = progress * album.total if album.total else 0.0
    span = max(1e-6, side["end"] - side["start"])
    frac = float(np.clip((t_abs - side["start"]) / span, 0.0, 1.0))

    # vinyl body
    for strip in vinyl.disc_body(cx, cy, radius, iso, light):
        draw_fill(img, strip, w, h)

    dr = ImageDraw.Draw(img)

    # wear — a semente e a contagem são as DESTE disco, como no GL
    wm = vinyl.wear_marks(cx, cy, radius, iso, rot, seed=album.seed,
                          plays=album.plays, crackle=crackle)
    if wm:
        draw_segments(dr, wm[0], wm[1], w, h, width_px=0.8)

    # grooves
    side_tracks = [album.tracks[i] for i in side.get("tracks", [])]
    env = album.envelope_snapshot()
    played_ring = int(frac * (vinyl.N_RINGS - 1))
    for pts, cols, wd in vinyl.groove_rings(cx, cy, radius, iso, side, env,
                                            side_tracks, light, played_ring=played_ring):
        draw_strip(dr, pts, cols, wd, w, h)
    br = vinyl.boundary_ring(cx, cy, radius, iso, side, env, frac, light)
    if br:
        draw_strip(dr, br[0], br[1], br[2], w, h)

    # live groove (synthetic waveform for preview)
    t = np.linspace(0, 1, 900)
    mid = (np.sin(t * 90) * (0.4 + 0.6 * np.sin(t * 7)) + 0.3 * np.sin(t * 230))
    sig = 0.5 * np.sin(t * 41)
    lg = vinyl.live_groove(cx, cy, radius, iso, frac, mid, sig, rot)
    if lg:
        draw_strip(dr, lg[0], lg[1], float(np.mean(lg[2])), w, h, chunk=8)

    for pts, cols, wd in vinyl.edge_and_label_rings(cx, cy, radius, iso, light):
        draw_strip(dr, pts, cols, wd, w, h)

    # o berço, e depois o braço
    rest = vinyl.arm_rest(cx, cy, radius, iso)
    if rest is not None and len(rest[0]):
        draw_segments(dr, rest[0], rest[1], w, h, width_px=1.2)

    play_r = vinyl.R_PROG_OUT + (vinyl.R_PROG_IN - vinyl.R_PROG_OUT) * frac
    ar = arm_radius if arm_radius is not None else play_r
    segs, cols, stylus = vinyl.tonearm(cx, cy, radius, iso, ar, lift=lift)
    draw_segments(dr, segs, cols, w, h, width_px=1.6)
    spx = _to_px(np.array([stylus]), w, h)[0]
    if lift < 0.5:
        r = 7 * SS
        dr.ellipse((spx[0] - r, spx[1] - r, spx[0] + r, spx[1] + r), fill=(150, 220, 255))

    # bloom-ish
    glow = img.filter(ImageFilter.GaussianBlur(radius=10 * SS))
    img = Image.blend(img, Image.fromarray(
        np.clip(np.asarray(img, np.int16) + np.asarray(glow, np.int16) * 0.75, 0, 255).astype(np.uint8)
    ), 1.0)

    # label artwork on top (crisp — it is the physical artifact)
    lab = label_image(album.cover, int(vinyl.R_LABEL * radius * (h / 2) * 2), rot)
    if lab is not None:
        # follow the disc centre, not the frame centre
        ccx = (cx * 0.5 + 0.5) * w
        ccy = (1.0 - (cy * 0.5 + 0.5)) * h
        lx = int(ccx - lab.width / 2)
        ly = int(ccy - lab.height / 2)
        img.paste(lab, (lx, ly), lab)
        d2 = ImageDraw.Draw(img)
        hr = int(vinyl.R_SPINDLE * radius * (h / 2))
        d2.ellipse((ccx - hr, ccy - hr, ccx + hr, ccy + hr), fill=(6, 8, 12))

    img = img.resize((W, H), Image.LANCZOS)

    if show_text:
        d = ImageDraw.Draw(img)
        try:
            f_big = ImageFont.truetype(
                "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFont-Light.ttf", 34)
            f_sm = ImageFont.truetype(
                "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFont-Light.ttf", 22)
        except Exception:
            f_big = f_sm = ImageFont.load_default()
        d.text((70, 62), album.artist.upper(), font=f_big, fill=(160, 176, 196))
        d.text((70, 106), album.name.upper(), font=f_big, fill=(228, 232, 238))
        d.text((70, 152), (album.year or ""), font=f_sm, fill=(110, 124, 144))
        lbl = side["label"]
        d.text((W - 70 - len(lbl) * 20, 62), lbl, font=f_big, fill=(91, 206, 250))
    return img


def _default_album(arg):
    """Sem --album, tira um disco da estante configurada.

    O padrão antigo era a pasta de um álbum específico na casa de quem
    escreveu isto. Num sistema, o padrão tem que ser "o que houver aí".
    """
    if arg:
        return os.path.expanduser(arg)
    import vinyl as _v
    return _v.draw_record() or _v.library_root()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", default=None,
                    help="pasta do disco; sem isto, sorteia um da estante")
    ap.add_argument("--at", type=float, default=0.35, help="album progress 0..1")
    ap.add_argument("--contact", action="store_true", help="strip of ceremony phases")
    ap.add_argument("--res", default="2560x1600")
    args = ap.parse_args()

    W, H = (int(v) for v in args.res.split("x"))
    folder = _default_album(args.album)
    album = vinyl.Album(folder)
    print(f"waiting for envelope scan of {album.artist} — {album.name} ...")
    t0 = time.time()
    while not album.env_ready and time.time() - t0 < 180:
        time.sleep(0.2)
    print(f"  envelope ready={album.env_ready} in {time.time()-t0:.1f}s, "
          f"{len(album.tracks)} tracks, {album.total/60:.1f} min, "
          f"{len(album.sides)} sides")
    for s in album.sides:
        print(f"  {s['label']}: {(s['end']-s['start'])/60:.1f} min, "
              f"tracks {s['tracks'][0]+1}-{s['tracks'][-1]+1}")

    os.makedirs(OUT_DIR, exist_ok=True)
    if args.contact:
        # (nome, progresso, rotação, lift, raio do braço, estalo)
        shots = [("1-spinup", 0.0, 0.0, 1.0, vinyl.ARM_REST_RADIUS, 0.0),
                 ("2-cue", 0.0, 0.0, 1.0, vinyl.R_LEADIN, 0.0),
                 ("3-drop", 0.005, 0.0, 0.3, vinyl.R_LEADIN, 1.0),
                 ("4-early", 0.08, None, 0.0, None, 0.0),
                 ("5-mid", 0.42, None, 0.0, None, 0.0),
                 ("6-late", 0.93, None, 0.0, None, 0.0),
                 ("7-travel", 1.0, None, 1.0, 0.75, 0.0),
                 ("8-fim", 1.0, None, 1.0, vinyl.ARM_REST_RADIUS, 0.0)]
        tiles = []
        for name, prog, rot, lift, ar, crk in shots:
            im = render(album, prog, W, H, rotation=rot, lift=lift, arm_radius=ar,
                        crackle=crk)
            im.save(os.path.join(OUT_DIR, f"phase_{name}.png"))
            tiles.append(im.resize((W // 3, H // 3), Image.LANCZOS))
            print("  wrote", name)
        sheet = Image.new("RGB", (W, H), (0, 0, 0))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % 3) * (W // 3), (i // 3) * (H // 3)))
        sheet.save(os.path.join(OUT_DIR, "contact.png"))
        print("wrote", os.path.join(OUT_DIR, "contact.png"))
    else:
        im = render(album, args.at, W, H)
        p = os.path.join(OUT_DIR, "preview.png")
        im.save(p)
        print("wrote", p)


if __name__ == "__main__":
    main()
