"""ui.py - Spotify-inspired Tkinter interface for My Music Player.

Layout:   sidebar (navigation + playlists)  |  main panel (pages)  |  bottom player bar
Everything lives in this one file (sections: theme, graphics, artwork, widgets, application).

This module only talks to the existing back-end through the same calls as before:
  Library:      songs, get, artwork, search, all_ids, liked, recent, playlists, is_liked,
                toggle_like, popular, add_recent, add_to_playlist, remove_from_playlist,
                create_playlist, delete_playlist, remove_song, import_file, save
  MusicPlayer:  play, pause, resume, stop, seek, position, finished, playing, paused,
                volume, set_volume, shutdown
"""
import hashlib
import io
import math
import os
import random
import sys
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk

from library import Library, SUPPORTED_EXTENSIONS
from music_player import MusicPlayer


# ==========================================================================
# THEME: colours, fonts, helpers
# ==========================================================================
# ---------- palette ----------
BLACK = "#000000"      # window background / player bar
BG = "#121212"         # main content panel
PANEL = "#181818"      # sidebar panels, cards
CARD = "#242424"       # inputs, chips, row hover
HOVER = "#2A2A2A"      # hover / selected
HOVER2 = "#333333"
GREEN = "#1DB954"
GREEN_HI = "#1ED760"
WHITE = "#FFFFFF"
GREY = "#B3B3B3"
DIM = "#727272"
LINE = "#2A2A2A"
RED = "#E5484D"

# the colourful tiles on the Search page
PALETTE = ["#E13300", "#1E3264", "#8D67AB", "#477D95", "#E8115B", "#148A08",
           "#DC148C", "#509BF5", "#AF2896", "#BC5900", "#2D46B9", "#608108"]

# ---------- fonts ----------
_PREFERRED = ("Circular Std", "Gotham", "Inter", "Segoe UI Variable Display", "Segoe UI",
              "SF Pro Display", "Helvetica Neue", "Cantarell", "Ubuntu", "Noto Sans",
              "DejaVu Sans")
_family = "Helvetica"
_measure_fonts = {}


def init_fonts(root):
    """Pick the best installed font family. Call once after the Tk root exists."""
    global _family
    try:
        have = set(tkfont.families(root))
    except Exception:
        have = set()
    for name in _PREFERRED:
        if name in have:
            _family = name
            return
    fallback = {"win32": "Segoe UI", "darwin": "Helvetica Neue"}.get(sys.platform, "DejaVu Sans")
    _family = fallback


def F(size, bold=False):
    return (_family, size, "bold") if bold else (_family, size)


def font(size, bold=False):
    """A tkfont.Font object (used for measuring text in pixels)."""
    key = (size, bold)
    if key not in _measure_fonts:
        _measure_fonts[key] = tkfont.Font(font=F(size, bold))
    return _measure_fonts[key]


# ---------- text helpers ----------
def fmt(sec):
    sec = int(max(0, sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_long(sec):
    """'1 hr 5 min' / '12 min' style total durations."""
    mins = int(round(max(0, sec or 0) / 60))
    if mins >= 60:
        return f"{mins // 60} hr {mins % 60} min"
    return f"{max(mins, 1) if sec else 0} min"


def trunc(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


def ellipsize(text, fnt, px):
    """Shorten text with an ellipsis so it fits in `px` pixels."""
    text = text or ""
    if px <= 12:
        return "…" if text else ""
    if fnt.measure(text) <= px:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fnt.measure(text[:mid] + "…") <= px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


# ---------- colour helpers ----------
def hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def lerp(c1, c2, t):
    a, b = hex_rgb(c1), hex_rgb(c2)
    return rgb_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def name_color(name):
    """Stable colour for a name (playlist, artist...)."""
    h = int(hashlib.md5((name or "").encode("utf-8", "ignore")).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


# ==========================================================================
# GRAPHICS: antialiased icons / shapes rendered with Pillow
# ==========================================================================
SS = 4  # supersampling factor

try:  # Pillow >= 9.1
    LANCZOS = Image.Resampling.LANCZOS
    BICUBIC = Image.Resampling.BICUBIC
    FLIP_LR = Image.Transpose.FLIP_LEFT_RIGHT
    FLIP_TB = Image.Transpose.FLIP_TOP_BOTTOM
except AttributeError:  # older Pillow
    LANCZOS, BICUBIC = Image.LANCZOS, Image.BICUBIC
    FLIP_LR, FLIP_TB = Image.FLIP_LEFT_RIGHT, Image.FLIP_TOP_BOTTOM


def _rgba(color, alpha=255):
    r, g, b = hex_rgb(color)
    return r, g, b, alpha


# --------------------------------------------------------------------------
# icons
# --------------------------------------------------------------------------
class _Pen:
    """Draws in a [-1, 1] x [-1, 1] coordinate box."""

    def __init__(self, size, color):
        self.size = size
        self.n = size * SS
        self.img = Image.new("RGBA", (self.n, self.n), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.col = _rgba(color)
        self.c = self.n / 2
        self.k = self.n / 2 * 0.88
        self.lw = max(SS * 1.5, self.n * 0.085)

    def p(self, x, y):
        return (self.c + x * self.k, self.c + y * self.k)

    def pts(self, pts):
        return [self.p(x, y) for x, y in pts]

    def poly(self, *pts):
        self.d.polygon(self.pts(pts), fill=self.col)

    def line(self, *pts, w=None, close=False):
        w = w or self.lw
        P = self.pts(pts + ((pts[0],) if close else ()))
        self.d.line(P, fill=self.col, width=int(round(w)), joint="curve")
        r = w / 2
        for x, y in ((P[0], P[-1]) if not close else ()):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=self.col)

    def rect(self, x1, y1, x2, y2, r=0.1):
        a, b = self.p(x1, y1), self.p(x2, y2)
        self.d.rounded_rectangle((a[0], a[1], b[0], b[1]), radius=r * self.k, fill=self.col)

    def ring(self, x1, y1, x2, y2, w=None):
        a, b = self.p(x1, y1), self.p(x2, y2)
        self.d.ellipse((a[0], a[1], b[0], b[1]), outline=self.col, width=int(round(w or self.lw)))

    def disc(self, cx, cy, r):
        x, y = self.p(cx, cy)
        rr = r * self.k
        self.d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=self.col)

    def arc(self, x1, y1, x2, y2, start, end, w=None):
        a, b = self.p(x1, y1), self.p(x2, y2)
        self.d.arc((a[0], a[1], b[0], b[1]), start % 360, end % 360, fill=self.col,
                   width=int(round(w or self.lw)))

    def done(self):
        return self.img.resize((self.size, self.size), LANCZOS)


def _heart_points():
    pts = []
    for i in range(120):
        t = i / 120 * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((x / 16 * 0.97, (y - 2.5) / 14.5 * 0.92))
    return tuple(pts)


_HEART = _heart_points()
_HOUSE = ((0, -.9), (.95, -.05), (.75, -.05), (.75, .85), (.25, .85), (.25, .25),
          (-.25, .25), (-.25, .85), (-.75, .85), (-.75, -.05), (-.95, -.05))


def _ic_play(p, f):
    p.poly((-.5, -.85), (.9, 0), (-.5, .85))
    p.line((-.5, -.85), (.9, 0), (-.5, .85), w=p.lw * .6, close=True)


def _ic_pause(p, f):
    p.rect(-.65, -.8, -.12, .8, .12)
    p.rect(.12, -.8, .65, .8, .12)


def _ic_next(p, f):
    p.poly((-.85, -.75), (.5, 0), (-.85, .75))
    p.rect(.55, -.75, .85, .75, .05)


def _ic_prev(p, f):
    p.poly((.85, -.75), (-.5, 0), (.85, .75))
    p.rect(-.85, -.75, -.55, .75, .05)


def _ic_stop(p, f):
    p.rect(-.7, -.7, .7, .7, .18)


def _ic_shuffle(p, f):
    p.line((-.9, -.5), (-.3, -.5), (.3, .5), (.6, .5))
    p.line((-.9, .5), (-.3, .5), (.3, -.5), (.6, -.5))
    p.poly((.5, .1), (.98, .5), (.5, .9))
    p.poly((.5, -.9), (.98, -.5), (.5, -.1))


def _ic_repeat(p, f, one=False):
    p.line((-.75, .15), (-.75, -.45), (.4, -.45))
    p.line((.75, -.15), (.75, .45), (-.4, .45))
    p.poly((.3, -.85), (.88, -.45), (.3, -.05))
    p.poly((-.3, .05), (-.88, .45), (-.3, .85))
    if one:
        p.line((-.13, -.1), (.05, -.22), (.05, .22), w=p.lw * .8)


def _ic_repeat1(p, f):
    _ic_repeat(p, f, True)


def _ic_home(p, f):
    if f:
        p.poly(*_HOUSE)
    else:
        p.line(*_HOUSE, w=p.lw * .9, close=True)


def _ic_search(p, f):
    p.ring(-.85, -.85, .4, .4, p.lw * (1.25 if f else 1.0))
    p.line((.2, .2), (.88, .88), w=p.lw * (1.25 if f else 1.0))


def _ic_library(p, f):
    p.rect(-.88, -.8, -.58, .8, .05)
    p.rect(-.4, -.8, -.1, .8, .05)
    p.poly((.2, -.7), (.5, -.84), (.95, .7), (.65, .84))


def _ic_heart(p, f):
    if f:
        p.poly(*_HEART)
    else:
        p.line(*_HEART, w=p.lw * .9, close=True)


def _ic_clock(p, f):
    p.ring(-.9, -.9, .9, .9, p.lw * (1.2 if f else .9))
    p.line((0, 0), (0, -.5))
    p.line((0, 0), (.4, .25))


def _speaker(p):
    p.poly((-.95, -.3), (-.55, -.3), (0, -.8), (0, .8), (-.55, .3), (-.95, .3))


def _ic_volume(p, f):
    _speaker(p)
    p.arc(-.45, -.55, .45, .55, -55, 55, p.lw * .85)
    p.arc(-.65, -.95, .95, .95, -55, 55, p.lw * .85)


def _ic_volume_low(p, f):
    _speaker(p)
    p.arc(-.45, -.55, .45, .55, -55, 55, p.lw * .85)


def _ic_mute(p, f):
    _speaker(p)
    p.line((.25, -.35), (.9, .35), w=p.lw * .85)
    p.line((.9, -.35), (.25, .35), w=p.lw * .85)


def _ic_queue(p, f):
    p.line((-.9, -.55), (.3, -.55))
    p.line((-.9, 0), (.3, 0))
    p.line((-.9, .55), (-.1, .55))
    p.poly((.3, .12), (.95, .55), (.3, .98))


def _ic_plus(p, f):
    p.line((-.7, 0), (.7, 0))
    p.line((0, -.7), (0, .7))


def _ic_chev_l(p, f):
    p.line((.35, -.7), (-.35, 0), (.35, .7))


def _ic_chev_r(p, f):
    p.line((-.35, -.7), (.35, 0), (-.35, .7))


def _ic_chev_d(p, f):
    p.line((-.7, -.3), (0, .4), (.7, -.3))


def _ic_dots(p, f):
    for x in (-.65, 0, .65):
        p.disc(x, 0, .17)


def _ic_note(p, f):
    p.disc(-.4, .55, .4)
    p.rect(-.1, -.85, .12, .55, .06)
    p.poly((.1, -.85), (.92, -.55), (.92, -.1), (.1, -.4))


def _ic_list(p, f):
    for y in (-.55, 0, .55):
        p.disc(-.78, y, .1)
        p.line((-.4, y), (.9, y), w=p.lw * .8)


def _ic_grid(p, f):
    for x1, y1 in ((-.85, -.85), (.08, -.85), (-.85, .08), (.08, .08)):
        p.rect(x1, y1, x1 + .77, y1 + .77, .12)


def _ic_close(p, f):
    p.line((-.6, -.6), (.6, .6))
    p.line((.6, -.6), (-.6, .6))


def _ic_check(p, f):
    p.line((-.7, 0), (-.2, .55), (.75, -.55))


def _ic_sort(p, f):
    p.line((-.8, -.5), (.8, -.5))
    p.line((-.55, 0), (.55, 0))
    p.line((-.3, .5), (.3, .5))


def _ic_warn(p, f):
    p.poly((0, -.9), (.95, .8), (-.95, .8))


_ICONS = {
    "play": _ic_play, "pause": _ic_pause, "next": _ic_next, "prev": _ic_prev, "stop": _ic_stop,
    "shuffle": _ic_shuffle, "repeat": _ic_repeat, "repeat1": _ic_repeat1, "home": _ic_home,
    "search": _ic_search, "library": _ic_library, "heart": _ic_heart, "clock": _ic_clock,
    "volume": _ic_volume, "volume_low": _ic_volume_low, "mute": _ic_mute, "queue": _ic_queue,
    "plus": _ic_plus, "chev_l": _ic_chev_l, "chev_r": _ic_chev_r, "chev_d": _ic_chev_d,
    "dots": _ic_dots, "note": _ic_note, "list": _ic_list, "grid": _ic_grid, "close": _ic_close,
    "check": _ic_check, "sort": _ic_sort, "warn": _ic_warn,
}


def pil_icon(name, size, color, filled=True):
    pen = _Pen(size, color)
    _ICONS[name](pen, filled)
    return pen.done()


@lru_cache(maxsize=None)
def gfx_icon(name, size, color, filled=True):
    return ImageTk.PhotoImage(pil_icon(name, size, color, filled))


# --------------------------------------------------------------------------
# shapes
# --------------------------------------------------------------------------
def pil_rrect(w, h, r, fill, outline=None, outline_w=2):
    w, h = max(2, int(w)), max(2, int(h))
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    kw = {"fill": _rgba(fill)} if fill else {}
    if outline:
        kw.update(outline=_rgba(outline), width=outline_w * SS)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=r * SS, **kw)
    return big.resize((w, h), LANCZOS)


@lru_cache(maxsize=1024)
def gfx_rrect(w, h, r, fill, outline=None, outline_w=2):
    return ImageTk.PhotoImage(pil_rrect(w, h, r, fill, outline, outline_w))


def gfx_rrect_nocache(w, h, r, fill, outline=None, outline_w=2):
    return ImageTk.PhotoImage(pil_rrect(w, h, r, fill, outline, outline_w))


@lru_cache(maxsize=256)
def gfx_circle(d, fill):
    big = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, d * SS - 1, d * SS - 1), fill=_rgba(fill))
    return ImageTk.PhotoImage(big.resize((d, d), LANCZOS))


def rounded_mask(size_w, size_h, radius):
    big = Image.new("L", (size_w * SS, size_h * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size_w * SS - 1, size_h * SS - 1),
                                          radius=radius * SS, fill=255)
    return big.resize((size_w, size_h), LANCZOS)


def round_image(img, radius):
    img = img.convert("RGBA")
    if radius > 0:
        img.putalpha(rounded_mask(img.width, img.height, radius))
    return img


def pil_gradient(w, h, c1, c2, diagonal=True):
    a = Image.new("RGB", (w, h), hex_rgb(c1))
    b = Image.new("RGB", (w, h), hex_rgb(c2))
    base = Image.linear_gradient("L")  # black (top) -> white (bottom)
    vert = base.resize((w, h))
    mask = ImageChops.add(vert, base.rotate(90).resize((w, h)), scale=2.0) if diagonal else vert
    return Image.composite(b, a, mask)


def with_shadow(img, blur=14, offset=8, alpha=150):
    """Return `img` (RGBA) on a larger transparent canvas with a soft drop shadow."""
    pad = blur * 2
    w, h = img.size
    size = (w + 2 * pad, h + 2 * pad)
    mask = Image.new("L", size, 0)
    mask.paste(img.getchannel("A").point(lambda a: a * alpha // 255), (pad, pad + offset))
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", size, (0, 0, 0, 255))
    shadow.putalpha(mask)
    shadow.alpha_composite(img, (pad, pad))
    return shadow


def corner_image(r, outer, which):
    """r x r image that is `outer` coloured except a transparent quarter-circle."""
    big = Image.new("RGBA", (r * SS, r * SS), _rgba(outer))
    ImageDraw.Draw(big).ellipse((0, 0, 2 * r * SS - 1, 2 * r * SS - 1), fill=(0, 0, 0, 0))
    img = big.resize((r, r), LANCZOS)  # top-left corner
    if which in ("tr", "br"):
        img = img.transpose(FLIP_LR)
    if which in ("bl", "br"):
        img = img.transpose(FLIP_TB)
    return ImageTk.PhotoImage(img)


# ==========================================================================
# ARTWORK: album art loading, caching, generated covers
# ==========================================================================
SRC_PX = 320          # artwork is kept at this size in memory
SRC_LIMIT = 160       # how many source images to keep
TK_LIMIT = 900        # how many PhotoImages to keep

SPECIAL = {           # kind -> (gradient start, gradient end, icon)
    "liked": ("#4A2FD0", "#9AA8F0", "heart"),
    "recent": ("#0B6E6E", "#3FD6C0", "clock"),
    "queue": ("#8A2BE2", "#F36AC2", "queue"),
    "library": ("#1B6B3A", "#53D58A", "library"),
}


class ArtCache:
    """Loads album artwork (or a generated cover) as cached Tk images."""

    def __init__(self, lib):
        self.lib = lib
        self._src = OrderedDict()    # sid -> PIL image or None
        self._tk = OrderedDict()     # key -> PhotoImage
        self._default = None

    # ---------- source images ----------
    def source(self, sid):
        """Square-ish RGB artwork for a song, or None when it has none."""
        if not sid:
            return None
        if sid in self._src:
            self._src.move_to_end(sid)
            return self._src[sid]
        img = None
        song = self.lib.get(sid)
        if song and os.path.isfile(song["path"]):
            try:
                data = self.lib.artwork(song["path"])
                if data:
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    img.thumbnail((SRC_PX, SRC_PX))
            except Exception:
                img = None
        self._src[sid] = img
        if len(self._src) > SRC_LIMIT:
            self._src.popitem(last=False)
        return img

    def has_art(self, sid):
        return self.source(sid) is not None

    def default(self, size):
        if self._default is None:
            base = pil_gradient(SRC_PX, SRC_PX, "#3A3A3A", "#1E1E1E")
            note = pil_icon("note", int(SRC_PX * .5), "#8A8A8A")
            base = base.convert("RGBA")
            base.alpha_composite(note, ((SRC_PX - note.width) // 2, (SRC_PX - note.height) // 2))
            self._default = base.convert("RGB")
        return self._default.resize((size, size), LANCZOS)

    # ---------- PIL builders ----------
    def pil(self, sid, size, radius=0):
        src = self.source(sid)
        img = ImageOps.fit(src, (size, size), LANCZOS) if src else self.default(size)
        return round_image(img, radius)

    def pil_mosaic(self, sids, size, radius=0):
        picks = []
        for sid in sids[:40]:
            if self.has_art(sid):
                picks.append(sid)
            if len(picks) == 4:
                break
        if len(picks) < 4:
            return self.pil(picks[0] if picks else None, size, radius)
        half = size // 2
        out = Image.new("RGB", (size, size), "#181818")
        for i, sid in enumerate(picks):
            tile = ImageOps.fit(self.source(sid), (half, half), LANCZOS)
            out.paste(tile, ((i % 2) * half, (i // 2) * half))
        return round_image(out, radius)

    def pil_special(self, kind, size, radius=0, name=None):
        c1, c2, ic = SPECIAL.get(kind, (name_color(name), None, "note"))
        if c2 is None:
            c2 = rgb_hex(tuple(int(v * .45) for v in hex_rgb(c1)))
        img = pil_gradient(size, size, c1, c2).convert("RGBA")
        glyph = pil_icon(ic, max(8, int(size * .42)), WHITE, True)
        img.alpha_composite(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2))
        return round_image(img, radius)

    # ---------- Tk images (cached) ----------
    def _remember(self, key, make):
        if key in self._tk:
            self._tk.move_to_end(key)
            return self._tk[key]
        photo = ImageTk.PhotoImage(make())
        self._tk[key] = photo
        if len(self._tk) > TK_LIMIT:
            self._tk.popitem(last=False)
        return photo

    def get(self, sid, size, radius=0):
        return self._remember(("s", sid, size, radius), lambda: self.pil(sid, size, radius))

    def mosaic(self, sids, size, radius=0):
        key = ("m", tuple(sids[:40]), size, radius)
        return self._remember(key, lambda: self.pil_mosaic(list(sids), size, radius))

    def special(self, kind, size, radius=0, name=None):
        return self._remember(("p", kind, name, size, radius),
                              lambda: self.pil_special(kind, size, radius, name))

    def playlist_cover(self, name, sids, size, radius=0):
        """Mosaic/single artwork for a playlist, else a coloured generated cover."""
        if any(self.has_art(s) for s in sids[:40]):
            return self.mosaic(sids, size, radius)
        return self.special("playlist", size, radius, name)

    def hero(self, kind, size, radius, sids=(), name=None):
        """Large cover with a soft shadow for page headers."""
        def make():
            if kind in SPECIAL:
                img = self.pil_special(kind, size, radius)
            elif sids and any(self.has_art(s) for s in sids[:40]):
                img = self.pil_mosaic(list(sids), size, radius)
            else:
                img = self.pil_special("playlist", size, radius, name)
            return with_shadow(img)
        return self._remember(("h", kind, name, tuple(sids[:40]), size, radius), make)

    def tilted(self, sid, size, angle=25):
        """Rotated artwork used on the Search page colour tiles."""
        def make():
            img = self.pil(sid, size, 6)
            return img.rotate(angle, expand=True, resample=BICUBIC)
        return self._remember(("t", sid, size, angle), make)

    # ---------- colours ----------
    def tint(self, kind=None, sids=(), name=None):
        """A saturated base colour for a page header gradient."""
        if kind in SPECIAL:
            return SPECIAL[kind][0]
        for sid in list(sids)[:20]:
            src = self.source(sid)
            if src is not None:
                r, g, b = src.resize((1, 1), LANCZOS).getpixel((0, 0))
                top = max(r, g, b, 1)
                k = max(.55, min(1.4, 150 / top))
                return rgb_hex((r * k, g * k, b * k))
        return name_color(name)


# ==========================================================================
# WIDGETS: custom Tk widgets
# ==========================================================================
# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def rounded_pts(x1, y1, x2, y2, r):
    """Point list for a smooth rounded-rectangle canvas polygon."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def tween(widget, apply, start, end, ms=140, steps=7, key="_tw"):
    """Animate a number from start to end (ease-out), calling apply(value) each frame."""
    job = getattr(widget, key, None)
    if job:
        try:
            widget.after_cancel(job)
        except Exception:
            pass
    delay = max(8, ms // steps)

    def step(i):
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        t = i / steps
        t = 1 - (1 - t) ** 3
        apply(start + (end - start) * t)
        setattr(widget, key, widget.after(delay, step, i + 1) if i < steps else None)

    step(1)


def round_corners(frame, r, panel, outer):
    """Overlay four corner pieces so a plain Frame looks like it has rounded corners."""
    pieces = []
    for which, (rx, ry, anchor) in {"tl": (0, 0, "nw"), "tr": (1, 0, "ne"),
                                    "bl": (0, 1, "sw"), "br": (1, 1, "se")}.items():
        c = tk.Canvas(frame, width=r, height=r, bg=panel, highlightthickness=0, bd=0)
        c.photo = corner_image(r, outer, which)
        c.create_image(0, 0, anchor="nw", image=c.photo)
        c.place(relx=rx, rely=ry, anchor=anchor)
        pieces.append(c)
    return pieces


# --------------------------------------------------------------------------
# buttons
# --------------------------------------------------------------------------
class IconButton(tk.Canvas):
    """Clickable antialiased icon with hover colour."""

    def __init__(self, parent, shape, px=20, bg=BLACK, color=GREY, hover=WHITE, filled=True,
                 cmd=None, pad=6):
        d = px + 2 * pad
        super().__init__(parent, width=d, height=d, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2" if cmd else "")
        self.shape, self.px, self.color, self.hover_color = shape, px, color, hover
        self.filled, self.hov = filled, False
        self.photo = None
        self.item = self.create_image(d // 2, d // 2)
        if cmd:
            self.bind("<Button-1>", lambda e: cmd())
            self.bind("<Enter>", lambda e: self._hover(True))
            self.bind("<Leave>", lambda e: self._hover(False))
        self._draw()

    def _hover(self, v):
        self.hov = v
        self._draw()

    def set(self, shape=None, color=None, filled=None):
        self.shape = shape or self.shape
        self.color = color or self.color
        if filled is not None:
            self.filled = filled
        self._draw()

    def _draw(self):
        col = self.hover_color if self.hov and self.color in (GREY, DIM) else self.color
        self.photo = gfx_icon(self.shape, self.px, col, self.filled)
        self.itemconfig(self.item, image=self.photo)


def Pill(parent, text, cmd, bg=WHITE, fg=BLACK, hover=None, icon=None, h=36, size=10):
    """Fully rounded pill button."""
    fnt = font(size, True)
    ic = 18 if icon else 0
    w = fnt.measure(text) + 40 + (ic + 8 if icon else 0)
    hover = hover or {WHITE: "#F0F0F0", GREEN: GREEN_HI}.get(bg, lerp(bg, WHITE, .12))
    c = tk.Canvas(parent, width=w, height=h, bg=parent.cget("bg"), highlightthickness=0, bd=0,
                  cursor="hand2")
    c.imgs = (gfx_rrect(w, h, h // 2, bg), gfx_rrect(w, h, h // 2, hover))
    bgi = c.create_image(0, 0, anchor="nw", image=c.imgs[0])
    tx = w // 2
    if icon:
        c.ico = gfx_icon(icon, ic, fg, True)
        c.create_image(20, h // 2, image=c.ico)
        tx = 20 + ic // 2 + 8 + fnt.measure(text) // 2
    c.create_text(tx, h // 2, text=text, font=F(size, True), fill=fg)
    c.bind("<Enter>", lambda e: c.itemconfig(bgi, image=c.imgs[1]))
    c.bind("<Leave>", lambda e: c.itemconfig(bgi, image=c.imgs[0]))
    c.bind("<Button-1>", lambda e: cmd())
    return c


class PlayCircle(tk.Canvas):
    """Round play/pause button that grows slightly on hover."""

    def __init__(self, parent, px, cmd, bg, color=WHITE, icon_color=BLACK):
        self.px, self.color, self.icon_color = px, color, icon_color
        d = px + 8
        super().__init__(parent, width=d, height=d, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.playing, self.hov, self.photo, self.icon_photo = False, False, None, None
        self.circ = self.create_image(d // 2, d // 2)
        self.glyph = self.create_image(d // 2, d // 2)
        self.bind("<Button-1>", lambda e: cmd())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.draw()

    def _hover(self, v):
        self.hov = v
        self.draw()

    def set(self, playing):
        self.playing = playing
        self.draw()

    def draw(self):
        dia = self.px + (6 if self.hov else 0)
        col = self.color
        if self.hov:
            col = {WHITE: "#F0F0F0", GREEN: GREEN_HI}.get(self.color, self.color)
        self.photo = gfx_circle(dia, col)
        self.icon_photo = gfx_icon("pause" if self.playing else "play", int(dia * .44), self.icon_color, True)
        self.itemconfig(self.circ, image=self.photo)
        off = 0 if self.playing else 1
        self.coords(self.glyph, int(self["width"]) // 2 + off, int(self["height"]) // 2)
        self.itemconfig(self.glyph, image=self.icon_photo)


class Slider(tk.Canvas):
    """Spotify-style slider (value 0..1). on_release fires when the user lets go."""
    PAD = 6

    def __init__(self, parent, width, bg=BLACK, on_change=None, on_release=None, value=0.0,
                 color=WHITE, hover_color=GREEN):
        super().__init__(parent, width=width, height=16, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.value, self.dragging, self.hover = value, False, False
        self.color, self.hover_color = color, hover_color
        self.on_change, self.on_release = on_change, on_release
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self._move)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, state):
        self.hover = state
        self.draw()

    def _value_at(self, x):
        w = self.winfo_width() - 2 * self.PAD
        return min(1.0, max(0.0, (x - self.PAD) / w)) if w > 0 else 0.0

    def _move(self, e):
        self.dragging = True
        self.value = self._value_at(e.x)
        self.draw()
        if self.on_change:
            self.on_change(self.value)

    def _release(self, e):
        self.dragging = False
        self.value = self._value_at(e.x)
        self.draw()
        if self.on_release:
            self.on_release(self.value)

    def set(self, v):
        if not self.dragging:
            self.value = min(1.0, max(0.0, v))
            self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        x = self.PAD + (w - 2 * self.PAD) * self.value
        active = self.hover or self.dragging
        self.create_line(self.PAD, 8, w - self.PAD, 8, width=4, fill="#4D4D4D", capstyle="round")
        if x > self.PAD:
            self.create_line(self.PAD, 8, x, 8, width=4, fill=self.hover_color if active else self.color,
                             capstyle="round")
        if active:
            self.create_oval(x - 6, 2, x + 6, 14, fill=WHITE, outline="")


class CircleButton(tk.Canvas):
    """Round button with an icon or a text glyph (used for back/forward and help)."""

    def __init__(self, parent, d, cmd, bg=BG, fill="#0A0A0A", hover_fill=HOVER2, shape=None,
                 text=None, icon_px=16):
        super().__init__(parent, width=d, height=d, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.d, self.fill_c, self.hover_c = d, fill, hover_fill
        self.shape, self.text, self.icon_px = shape, text, icon_px
        self.enabled, self.hov, self.cmd = True, False, cmd
        self.circ = self.create_image(d // 2, d // 2)
        self.glyph = self.create_image(d // 2, d // 2) if shape else None
        self.label = self.create_text(d // 2, d // 2, text=text or "", font=F(11, True)) if text else None
        self.bind("<Button-1>", lambda e: self.enabled and self.cmd())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self._draw()

    def _hover(self, v):
        self.hov = v
        self._draw()

    def set_enabled(self, v):
        self.enabled = v
        self.configure(cursor="hand2" if v else "")
        self._draw()

    def _draw(self):
        self.photo = gfx_circle(self.d, self.hover_c if (self.hov and self.enabled) else self.fill_c)
        self.itemconfig(self.circ, image=self.photo)
        col = WHITE if self.enabled else "#5A5A5A"
        if self.glyph:
            self.glyph_photo = gfx_icon(self.shape, self.icon_px, col, True)
            self.itemconfig(self.glyph, image=self.glyph_photo)
        if self.label:
            self.itemconfig(self.label, fill=col)


class Chip(tk.Canvas):
    """Pill-shaped toggle used for library filters."""

    def __init__(self, parent, text, cmd, bg=BG, active=False):
        fnt = font(10, True)
        self.w, self.h, self.text = fnt.measure(text) + 32, 32, text
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.is_on, self.hov = active, False
        self.back = self.create_image(0, 0, anchor="nw")
        self.label = self.create_text(self.w // 2, self.h // 2, text=text, font=F(10, True))
        self.bind("<Button-1>", lambda e: cmd())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self._draw()

    def _hover(self, v):
        self.hov = v
        self._draw()

    def set_active(self, v):
        self.is_on = v
        self._draw()

    def _draw(self):
        fill = WHITE if self.is_on else (HOVER2 if self.hov else CARD)
        self.photo = gfx_rrect(self.w, self.h, 16, fill)
        self.itemconfig(self.back, image=self.photo)
        self.itemconfig(self.label, fill=BLACK if self.is_on else WHITE)


# --------------------------------------------------------------------------
# scrolling
# --------------------------------------------------------------------------
class ScrollFrame(tk.Frame):
    """Vertically scrollable frame; put children in .inner. The scrollbar floats on top."""
    is_scroll = True

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                style="Slim.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(fill="both", expand=True)
        self._sb_shown = False
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))

    def _on_scroll(self, a, b):
        self.sb.set(a, b)
        need = not (float(a) <= 0.0 and float(b) >= 1.0)
        if need and not self._sb_shown:
            self.sb.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
            self._sb_shown = True
        elif not need and self._sb_shown:
            self.sb.place_forget()
            self._sb_shown = False

    def can_scroll(self):
        return self.inner.winfo_reqheight() > self.canvas.winfo_height()

    def scroll_units(self, n):
        if self.can_scroll():
            self.canvas.yview_scroll(n, "units")

    def get_y(self):
        return self.canvas.yview()[0]

    def set_y(self, frac):
        self.canvas.yview_moveto(frac)


# --------------------------------------------------------------------------
# fluid (full-width) items with a rounded hover background
# --------------------------------------------------------------------------
class FluidCanvas(tk.Canvas):
    """Canvas with a rounded background that stretches with the widget and fades on hover."""

    def __init__(self, parent, height, base, hover, active, parent_bg, radius=8, cursor="hand2"):
        super().__init__(parent, height=height, bg=parent_bg, highlightthickness=0, bd=0, cursor=cursor)
        self.base_c, self.hover_c, self.active_c, self.radius = base, hover, active, radius
        self.is_active, self.hovering, self._p = False, False, 0.0
        self.bg_item = self.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, fill=base, outline="")
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")

    def _on_configure(self, e):
        self.coords(self.bg_item, *rounded_pts(0, 0, e.width, e.height, self.radius))
        self.relayout(e.width, e.height)

    def relayout(self, w, h):
        pass

    def on_hover(self, v):
        pass

    def _enter(self, _):
        self.hovering = True
        tween(self, self._set_p, self._p, 1.0, 90, 4)
        self.on_hover(True)

    def _leave(self, _):
        self.hovering = False
        tween(self, self._set_p, self._p, 0.0, 120, 4)
        self.on_hover(False)

    def _set_p(self, p):
        self._p = p
        self._paint()

    def _paint(self):
        if self.is_active:
            col = lerp(self.active_c, lerp(self.active_c, WHITE, .06), self._p)
        else:
            col = lerp(self.base_c, self.hover_c, self._p)
        self.itemconfig(self.bg_item, fill=col)
        self.painted(self._p)

    def painted(self, p):
        pass

    def set_active(self, v):
        self.is_active = v
        self._paint()


class NavItem(FluidCanvas):
    """Sidebar navigation entry: icon + label, clear active state."""
    H = 44

    def __init__(self, parent, shape, label, cmd, outline_when_idle=True):
        super().__init__(parent, self.H, PANEL, "#212121", CARD, PANEL)
        self.shape, self.outline_idle = shape, outline_when_idle
        self.i_icon = self.create_image(26, self.H // 2)
        self.t_label = self.create_text(54, self.H // 2, text=label, anchor="w", fill=GREY, font=F(11, True))
        self.bar = self.create_rectangle(0, 12, 3, self.H - 12, fill=GREEN, outline="", state="hidden")
        self.bind("<Button-1>", lambda e: cmd())
        self._style(0.0)

    def _style(self, p):
        active = self.is_active
        col = WHITE if (active or p > .5) else GREY
        filled = active or not self.outline_idle
        self.photo = gfx_icon(self.shape, 22, col, filled)
        self.itemconfig(self.i_icon, image=self.photo)
        self.itemconfig(self.t_label, fill=WHITE if active else lerp(GREY, WHITE, p))
        self.itemconfig(self.bar, state="normal" if active else "hidden")

    def painted(self, p):
        self._style(p)

    def set_active(self, v):
        self.is_active = v
        self._paint()


class SideItem(FluidCanvas):
    """Sidebar playlist entry with a cover thumbnail."""
    H = 64

    def __init__(self, parent, photo, title, sub, on_click, on_menu=None):
        super().__init__(parent, self.H, PANEL, CARD, HOVER, PANEL)
        self.photo, self.raw_title, self.raw_sub = photo, title, sub
        self.create_image(10, 8, anchor="nw", image=photo)
        self.t_title = self.create_text(72, 23, anchor="w", text=title, fill=WHITE, font=F(11, True))
        self.t_sub = self.create_text(72, 43, anchor="w", text=sub, fill=GREY, font=F(10))
        self.bind("<Button-1>", lambda e: on_click())
        if on_menu:
            for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                self.bind(seq, on_menu)

    def relayout(self, w, h):
        px = max(40, w - 72 - 12)
        self.itemconfig(self.t_title, text=ellipsize(self.raw_title, font(11, True), px))
        self.itemconfig(self.t_sub, text=ellipsize(self.raw_sub, font(10), px))


class Row(FluidCanvas):
    """One song (or playlist) row: #, artwork, title/artist, like, duration, menu."""
    H = 56

    def __init__(self, parent, *, num=None, photo=None, title="", sub="", right="", sid=None,
                 liked=False, playing=False, missing=False, on_play=None, on_menu=None,
                 on_open=None, on_like=None, on_select=None):
        super().__init__(parent, self.H, BG, CARD, HOVER, BG, radius=6)
        self.sid, self.liked, self.playing, self.audio_on, self.missing = sid, liked, playing, False, missing
        self.numbered = num is not None
        self.raw_title, self.raw_sub, self.photo = title, sub, photo
        self.on_play, self.on_menu, self.on_open = on_play, on_menu, on_open
        self.on_like, self.on_select = on_like, on_select
        self.art_x = 60 if self.numbered else 12
        self.text_x = self.art_x + 52
        mid = self.H // 2
        self.t_num = self.create_text(34, mid, text=str(num) if num else "", fill=GREY, font=F(11))
        self.i_play = self.create_image(34, mid, state="hidden")
        self.bars = [self.create_rectangle(0, 0, 0, 0, fill=GREEN, outline="", state="hidden") for _ in range(3)]
        self.create_image(self.art_x, 8, anchor="nw", image=photo)
        self.t_title = self.create_text(self.text_x, 20, anchor="w", text=title, font=F(11, True))
        self.t_sub = self.create_text(self.text_x, 38, anchor="w", text=sub, fill=GREY, font=F(10))
        self.t_right = self.create_text(0, mid, anchor="e", text=right, fill=GREY, font=F(10))
        self.i_heart = self.create_image(0, mid, state="hidden")
        self.i_dots = self.create_image(0, mid, state="hidden")
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._double)
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.bind(seq, self._context)
        self._refresh()

    # ----- geometry
    def _heart_x(self, w):
        return w - 112

    def relayout(self, w, h):
        mid = self.H // 2
        if self.sid:
            self.coords(self.t_right, w - 62, mid)
            self.coords(self.i_heart, self._heart_x(w), mid)
            self.coords(self.i_dots, w - 30, mid)
            limit = self._heart_x(w) - 24
        else:
            self.coords(self.t_right, w - 20, mid)
            limit = w - 20 - font(10).measure(self.itemcget(self.t_right, "text")) - 20
        px = max(40, limit - self.text_x)
        self.itemconfig(self.t_title, text=ellipsize(self.raw_title, font(11, True), px))
        self.itemconfig(self.t_sub, text=ellipsize(self.raw_sub, font(10), px))

    # ----- state
    def on_hover(self, v):
        self._refresh()

    def set_playing(self, playing, audio_on):
        self.playing, self.audio_on = playing, audio_on
        self._refresh()

    def set_liked(self, liked):
        self.liked = liked
        self._refresh()

    def _refresh(self):
        hov = self.hovering
        self.itemconfig(self.t_title, fill=GREEN if self.playing else (DIM if self.missing else WHITE))
        # left cell: number / play icon / equaliser
        if self.numbered:
            if hov and self.sid:
                glyph = "pause" if (self.playing and self.audio_on) else "play"
                self._glyph = gfx_icon(glyph, 16, WHITE, True)
                self.itemconfig(self.i_play, image=self._glyph, state="normal")
                self.itemconfig(self.t_num, state="hidden")
                self._bars(False)
            elif self.playing:
                self.itemconfig(self.i_play, state="hidden")
                self.itemconfig(self.t_num, state="hidden")
                self._bars(True)
                self.animate(force=True)
            else:
                self.itemconfig(self.i_play, state="hidden")
                self.itemconfig(self.t_num, state="normal", fill=DIM if self.missing else GREY)
                self._bars(False)
        # right cell
        if self.sid:
            if self.liked:
                self._heart = gfx_icon("heart", 18, GREEN, True)
                self.itemconfig(self.i_heart, image=self._heart, state="normal")
            elif hov:
                self._heart = gfx_icon("heart", 18, GREY, False)
                self.itemconfig(self.i_heart, image=self._heart, state="normal")
            else:
                self.itemconfig(self.i_heart, state="hidden")
            if hov:
                self._dots = gfx_icon("dots", 20, GREY, True)
                self.itemconfig(self.i_dots, image=self._dots, state="normal")
            else:
                self.itemconfig(self.i_dots, state="hidden")

    def _bars(self, show):
        for b in self.bars:
            self.itemconfig(b, state="normal" if show else "hidden")

    def animate(self, force=False):
        """Bounce the equaliser bars (called from the app's timer)."""
        if not (self.playing and not self.hovering):
            return
        for i, b in enumerate(self.bars):
            h = random.randint(6, 18) if (self.audio_on and not force) else (8, 14, 10)[i]
            x = 28 + i * 6
            self.coords(b, x, 38 - h, x + 3, 38)

    # ----- mouse
    def _zone(self, x):
        w = self.winfo_width()
        if self.numbered and self.sid and x < self.art_x - 6:
            return "play"
        if self.sid and abs(x - self._heart_x(w)) < 14 and (self.hovering or self.liked):
            return "heart"
        if self.sid and abs(x - (w - 30)) < 14 and self.hovering:
            return "dots"
        return "row"

    def _click(self, e):
        if self.on_open:
            self.on_open()
            return
        zone = self._zone(e.x)
        if zone == "play" and self.on_play:
            self.on_play()
        elif zone == "heart" and self.on_like:
            self.on_like()
        elif zone == "dots" and self.on_menu:
            self.on_menu(e)
        elif self.on_select:
            self.on_select(self)

    def _double(self, e):
        if self.on_open or self._zone(e.x) != "row":
            return
        if self.on_play:
            self.on_play()

    def _context(self, e):
        if self.on_select:
            self.on_select(self)
        if self.on_menu:
            self.on_menu(e)


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------
class Card(tk.Canvas):
    """Album/playlist card; a green play button slides up on hover."""

    def __init__(self, parent, photo, title, sub, on_click, width, art, on_menu=None, bg=BG):
        self.W, self.A = width, art
        self.H = art + 76
        super().__init__(parent, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.photo = photo
        self.back_photo = gfx_rrect(self.W, self.H, 8, PANEL)
        self.back = self.create_image(0, 0, anchor="nw", image=self.back_photo)
        self.create_image(12, 12, anchor="nw", image=photo)
        tw = self.W - 24
        self.create_text(12, 12 + art + 22, anchor="w", fill=WHITE, font=F(11, True),
                         text=ellipsize(title, font(11, True), tw))
        self.create_text(12, 12 + art + 43, anchor="w", fill=GREY, font=F(10),
                         text=ellipsize(sub, font(10), tw))
        self.btn = self.create_image(0, 0, state="hidden")
        self.glyph = self.create_image(0, 0, state="hidden")
        self._glyph_photo = gfx_icon("play", 20, BLACK, True)
        self.itemconfig(self.glyph, image=self._glyph_photo)
        self.bind("<Enter>", lambda e: tween(self, self._anim, self._p, 1.0, 140, 6))
        self.bind("<Leave>", lambda e: tween(self, self._anim, self._p, 0.0, 110, 5))
        self.bind("<Button-1>", lambda e: on_click())
        if on_menu:
            for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                self.bind(seq, on_menu)
        self._p = 0.0

    def _anim(self, p):
        self._p = p
        self.back_photo = gfx_rrect(self.W, self.H, 8, lerp(PANEL, HOVER, p))
        self.itemconfig(self.back, image=self.back_photo)
        if p < .03:
            self.itemconfig(self.btn, state="hidden")
            self.itemconfig(self.glyph, state="hidden")
            return
        cx, cy = 12 + self.A - 30, 12 + self.A - 30 + (1 - p) * 14
        self.btn_photo = gfx_circle(48, lerp(PANEL, GREEN, min(1.0, p * 1.5)))
        self.itemconfig(self.btn, image=self.btn_photo, state="normal")
        self.coords(self.btn, cx, cy)
        self.itemconfig(self.glyph, state="normal" if p > .45 else "hidden")
        self.coords(self.glyph, cx + 1, cy)


class Tile(tk.Canvas):
    """Compact quick-access tile for the top of Home."""
    H = 64

    def __init__(self, parent, photo, title, on_click, width, bg=BG):
        self.W = width
        super().__init__(parent, width=width, height=self.H, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.photo = photo
        self.back_photo = gfx_rrect(width, self.H, 6, CARD)
        self.back = self.create_image(0, 0, anchor="nw", image=self.back_photo)
        self.create_image(0, 0, anchor="nw", image=photo)
        self.create_text(78, self.H // 2, anchor="w", fill=WHITE, font=F(11, True),
                         text=ellipsize(title, font(11, True), width - 78 - 64))
        self.btn = self.create_image(width - 34, self.H // 2, state="hidden")
        self.glyph = self.create_image(width - 33, self.H // 2, state="hidden")
        self._glyph_photo = gfx_icon("play", 16, BLACK, True)
        self.itemconfig(self.glyph, image=self._glyph_photo)
        self._p = 0.0
        self.bind("<Enter>", lambda e: tween(self, self._anim, self._p, 1.0, 120, 5))
        self.bind("<Leave>", lambda e: tween(self, self._anim, self._p, 0.0, 100, 4))
        self.bind("<Button-1>", lambda e: on_click())

    def _anim(self, p):
        self._p = p
        self.back_photo = gfx_rrect(self.W, self.H, 6, lerp(CARD, HOVER2, p))
        self.itemconfig(self.back, image=self.back_photo)
        if p < .03:
            self.itemconfig(self.btn, state="hidden")
            self.itemconfig(self.glyph, state="hidden")
            return
        self.btn_photo = gfx_circle(38, lerp(CARD, GREEN, min(1.0, p * 1.5)))
        self.itemconfig(self.btn, image=self.btn_photo, state="normal")
        self.itemconfig(self.glyph, state="normal" if p > .45 else "hidden")


class ColorTile(tk.Canvas):
    """Colourful 'browse' tile (Search page) with tilted artwork in the corner."""
    H = 104

    def __init__(self, parent, width, color, title, photo, on_click, bg=BG):
        self.W, self.color = width, color
        super().__init__(parent, width=width, height=self.H, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.photo = photo
        self.back_photo = gfx_rrect(width, self.H, 8, color)
        self.back = self.create_image(0, 0, anchor="nw", image=self.back_photo)
        self.create_text(14, 14, anchor="nw", fill=WHITE, font=F(14, True), width=int(width * .62), text=title)
        if photo is not None:
            self.create_image(width - 6, self.H - 2, anchor="se", image=photo)
        self.bind("<Enter>", lambda e: self._set(lerp(color, WHITE, .12)))
        self.bind("<Leave>", lambda e: self._set(color))
        self.bind("<Button-1>", lambda e: on_click())

    def _set(self, col):
        self.back_photo = gfx_rrect(self.W, self.H, 8, col)
        self.itemconfig(self.back, image=self.back_photo)


# --------------------------------------------------------------------------
# search box
# --------------------------------------------------------------------------
class SearchBox(tk.Canvas):
    """Rounded search input with placeholder, clear button and focus ring."""

    def __init__(self, parent, placeholder="What do you want to play?", on_change=None, bg=BG,
                 max_w=440, h=40, icon_px=20, width=None):
        super().__init__(parent, height=h, bg=bg, highlightthickness=0, bd=0)
        if width:
            self.configure(width=width)
        self.ph, self.on_change, self.max_w, self.h = placeholder, on_change, max_w, h
        self._ph_on, self._focus, self._bw = False, False, 0
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, bd=0, bg=CARD, fg=WHITE, insertbackground=WHITE,
                              font=F(11), relief="flat", highlightthickness=0)
        self.back = self.create_image(0, 0, anchor="nw")
        self.ico_photo = gfx_icon("search", icon_px, GREY, True)
        self.create_image(24, h // 2, image=self.ico_photo)
        self.win = self.create_window(44, h // 2, window=self.entry, anchor="w")
        self.clr_photo = gfx_icon("close", 16, GREY, True)
        self.clr = self.create_image(0, h // 2, image=self.clr_photo, state="hidden")
        self.tag_bind(self.clr, "<Button-1>", lambda e: self.clear())
        self.bind("<Configure>", self._on_configure)
        self.var.trace_add("write", self._changed)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Escape>", lambda e: (self.clear(), self.winfo_toplevel().focus_set()))
        self._show_placeholder()

    def _on_configure(self, e):
        self._bw = min(e.width, self.max_w)
        self._draw()

    def _draw(self):
        if self._bw < 80:
            return
        self.back_photo = gfx_rrect(self._bw, self.h, self.h // 2, CARD, WHITE if self._focus else None)
        self.itemconfig(self.back, image=self.back_photo)
        self.itemconfigure(self.win, width=max(20, self._bw - 44 - 44), height=self.h - 14)
        self.coords(self.clr, self._bw - 24, self.h // 2)

    def _show_placeholder(self):
        self._ph_on = True
        self.entry.delete(0, "end")
        self.entry.insert(0, self.ph)
        self.entry.configure(fg=DIM)

    def _focus_in(self, _):
        self._focus = True
        if self._ph_on:
            self.entry.delete(0, "end")
            self.entry.configure(fg=WHITE)
            self._ph_on = False
        self._draw()

    def _focus_out(self, _):
        self._focus = False
        if not self.var.get():
            self._show_placeholder()
        self._draw()

    def _changed(self, *_):
        if self._ph_on:
            return
        self.itemconfig(self.clr, state="normal" if self.var.get() else "hidden")
        if self.on_change:
            self.on_change(self.var.get())

    def get(self):
        return "" if self._ph_on else self.var.get().strip()

    def set(self, text):
        if self._ph_on:
            self.entry.delete(0, "end")
            self.entry.configure(fg=WHITE)
            self._ph_on = False
        self.var.set(text)
        self.entry.icursor("end")

    def clear(self):
        if self._ph_on:
            return
        self.var.set("")
        if not self._focus:
            self._show_placeholder()

    def focus_entry(self):
        self.entry.focus_set()
        self.entry.select_range(0, "end")


# --------------------------------------------------------------------------
# toast
# --------------------------------------------------------------------------
class Toast:
    """Small floating notification (info / success / error / progress)."""

    def __init__(self, root, bottom_offset=104):
        self.root, self.offset, self.job = root, bottom_offset, None
        self.c = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.photos = []

    def _render(self, text, kind, frac=None):
        fnt = font(10, True)
        w = max(240, fnt.measure(text) + 24 + 26 + 18 + 12)
        h = 50 if frac is None else 58
        self.c.delete("all")
        self.photos = [gfx_rrect_nocache(w, h, 10, HOVER, "#3E3E3E", 1)]
        self.c.configure(width=w, height=h)
        self.c.create_image(0, 0, anchor="nw", image=self.photos[0])
        glyph, col = {"error": ("warn", RED), "success": ("check", GREEN),
                      "loading": ("note", GREEN)}.get(kind, ("check", GREEN))
        self.photos.append(gfx_icon(glyph, 18, col, True))
        self.c.create_image(24, 25, image=self.photos[1])
        self.c.create_text(46, 25, anchor="w", text=text, fill=WHITE, font=F(10, True))
        if frac is not None:
            self.c.create_rectangle(18, h - 14, w - 18, h - 10, fill="#4D4D4D", outline="")
            self.c.create_rectangle(18, h - 14, 18 + (w - 36) * max(0.0, min(1.0, frac)), h - 10,
                                    fill=GREEN, outline="")
        self.c.place(relx=.5, rely=1.0, y=-self.offset, anchor="s")
        tk.Misc.lift(self.c)

    def _cancel(self):
        if self.job:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    def show(self, text, kind="success", ms=2600):
        self._cancel()
        self._render(text, kind)
        self.job = self.root.after(ms, self.hide)

    def progress(self, text, frac):
        self._cancel()
        self._render(text, "loading", frac)

    def hide(self):
        self._cancel()
        self.c.place_forget()


# --------------------------------------------------------------------------
# context menu
# --------------------------------------------------------------------------
class ContextMenu:
    """Dark, rounded-feeling popup menu. Items: (label, callable) | (label, [subitems]) | None."""
    BG_, HOV_, BORDER = "#282828", "#3E3E3E", "#3A3A3A"

    def __init__(self, root):
        self.root, self.wins = root, []
        root.bind_all("<ButtonPress>", self._outside, add="+")
        root.bind("<Escape>", lambda e: self.close(), add="+")

    def show(self, x, y, items):
        self.close()
        self._open(0, x, y, items)

    def close(self, level=0):
        while len(self.wins) > level:
            w = self.wins.pop()
            try:
                w.destroy()
            except tk.TclError:
                pass

    def _open(self, level, x, y, items):
        self.close(level)
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.configure(bg=self.BORDER)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        body = tk.Frame(win, bg=self.BG_)
        body.pack(padx=1, pady=1)
        tk.Frame(body, bg=self.BG_, height=4).pack()
        for item in items:
            if item is None:
                tk.Frame(body, bg=self.HOV_, height=1).pack(fill="x", padx=2, pady=4)
                continue
            self._row(body, level, item)
        tk.Frame(body, bg=self.BG_, height=4).pack()
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(x, sw - w - 4))
        y = max(0, min(y, sh - h - 4))
        win.geometry(f"+{int(x)}+{int(y)}")
        win.lift()
        self.wins.append(win)

    def _row(self, body, level, item):
        label, action = item[0], item[1]
        sub = isinstance(action, (list, tuple))
        row = tk.Frame(body, bg=self.BG_, cursor="hand2")
        row.pack(fill="x", padx=4)
        lb = tk.Label(row, text=label, font=F(10), fg=WHITE, bg=self.BG_, anchor="w", padx=12, pady=7)
        lb.pack(side="left", fill="x", expand=True)
        widgets = [row, lb]
        if sub:
            ar = tk.Label(row, text="›", font=F(12, True), fg=GREY, bg=self.BG_, padx=10)
            ar.pack(side="right")
            widgets.append(ar)

        def paint(col):
            for w in widgets:
                w.configure(bg=col)

        def click(_e, row=row):
            if sub:
                self._open(level + 1, row.winfo_rootx() + row.winfo_width() - 4, row.winfo_rooty() - 4, action)
            else:
                self.close()
                action()

        for w in widgets:
            w.bind("<Enter>", lambda e: paint(self.HOV_))
            w.bind("<Leave>", lambda e: paint(self.BG_))
            w.bind("<Button-1>", click)

    def _outside(self, e):
        if not self.wins:
            return
        path = str(e.widget)
        for w in self.wins:
            if path.startswith(str(w)):
                return
        self.close()


# --------------------------------------------------------------------------
# dialogs
# --------------------------------------------------------------------------
class Modal(tk.Toplevel):
    """Dark modal dialog: optional text entry, OK/Cancel buttons."""

    def __init__(self, root, title, message="", entry=False, initial="", ok="OK", cancel="Cancel",
                 danger=False, width=420):
        super().__init__(root)
        self.result = None
        self.withdraw()
        self.title(title)
        self.configure(bg="#282828")
        self.resizable(False, False)
        tk.Label(self, text=title, font=F(16, True), fg=WHITE, bg="#282828", anchor="w",
                 justify="left").pack(fill="x", padx=28, pady=(26, 6))
        if message:
            tk.Label(self, text=message, font=F(10), fg=GREY, bg="#282828", anchor="w", justify="left",
                     wraplength=width - 56).pack(fill="x", padx=28, pady=(0, 6))
        self.entry = None
        if entry:
            self.entry = tk.Entry(self, font=F(12), bg="#3E3E3E", fg=WHITE, insertbackground=WHITE,
                                  relief="flat", bd=0, highlightthickness=2, highlightbackground="#3E3E3E",
                                  highlightcolor=WHITE, width=30)
            self.entry.pack(fill="x", padx=28, pady=(8, 4), ipady=8)
            self.entry.insert(0, initial)
        row = tk.Frame(self, bg="#282828")
        row.pack(fill="x", padx=28, pady=(20, 24))
        Pill(row, ok, self._ok, bg=RED if danger else GREEN, fg=WHITE if danger else BLACK).pack(side="right")
        if cancel:
            Pill(row, cancel, self._cancel, bg="#282828", fg=WHITE, hover="#3E3E3E").pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"{max(width, self.winfo_reqwidth())}x{self.winfo_reqheight()}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.transient(root)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        (self.entry or self).focus_set()
        if self.entry:
            self.entry.select_range(0, "end")

    def _ok(self):
        self.result = self.entry.get() if self.entry else True
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    def run(self):
        self.master.wait_window(self)
        return self.result


# --------------------------------------------------------------------------
# empty state
# --------------------------------------------------------------------------
class EmptyState(tk.Frame):
    """Centered illustration + message + optional buttons."""

    def __init__(self, parent, shape, title, text="", buttons=(), bg=BG):
        super().__init__(parent, bg=bg)
        self.photo = gfx_icon(shape, 72, "#4A4A4A", True)
        tk.Label(self, image=self.photo, bg=bg).pack(pady=(0, 18))
        tk.Label(self, text=title, font=F(20, True), fg=WHITE, bg=bg).pack()
        if text:
            tk.Label(self, text=text, font=F(11), fg=GREY, bg=bg, justify="center", wraplength=460).pack(pady=(8, 0))
        if buttons:
            row = tk.Frame(self, bg=bg)
            row.pack(pady=(24, 0))
            for label, cmd, primary in buttons:
                Pill(row, label, cmd, bg=WHITE if primary else HOVER, fg=BLACK if primary else WHITE,
                     h=40).pack(side="left", padx=6)


# ==========================================================================
# APPLICATION
# ==========================================================================
PAD = 28                 # horizontal page padding
SIDEBAR_W = 280
PLAYER_H = 92
MOD = "Command" if sys.platform == "darwin" else "Control"

NAV = [("Home", "home", "home"), ("Search", "search", "search"), ("Your Library", "library", "library"),
       ("Liked Songs", "heart", "liked"), ("Recently Played", "clock", "recent")]

SORTS_SONGS = [("Default order", "default"), ("Title (A–Z)", "title"), ("Artist (A–Z)", "artist"),
               ("Duration", "duration"), ("Recently played", "recent")]
SORTS_LISTS = [("Default order", "default"), ("Name (A–Z)", "title"), ("Most songs", "count")]

SHORTCUTS = [
    ("Space", "Play / pause"), ("Ctrl + →  /  Ctrl + ←", "Next / previous song"),
    ("Ctrl + ↑  /  Ctrl + ↓", "Volume up / down"), ("M", "Mute / unmute"),
    ("Ctrl + S", "Toggle shuffle"), ("Ctrl + R", "Cycle repeat mode"), ("Ctrl + L", "Like current song"),
    ("Ctrl + K  or  Ctrl + F", "Focus search"), ("Ctrl + N", "Create playlist"),
    ("Ctrl + O", "Import music files"), ("Alt + ←  /  Alt + →", "Back / forward"), ("F1", "Show this help"),
]


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My Music Player")
        self.root.geometry("1280x800")
        self.root.minsize(980, 620)
        self.root.configure(bg=BLACK)
        init_fonts(self.root)
        try:
            self.player = MusicPlayer()
        except Exception as exc:  # no audio device, etc.
            messagebox.showerror("Audio error", f"Could not start the audio engine:\n{exc}")
            raise SystemExit(1)
        self.lib = Library()
        self.art = ArtCache(self.lib)
        self.queue, self.history = [], []
        self.current, self.cur_duration = None, 0.0
        self.shuffle, self.repeat = False, 0       # repeat: 0 off, 1 all, 2 one
        self.view, self.back_stack, self.fwd_stack = ("home", None), [], []
        self.page, self.rows, self.selected_row, self._token = None, [], None, 0
        self.collections, self._exists_cache = {}, {}
        self._sig, self._resize_job, self._q_job, self._lib_job = None, None, None, None
        self._prev_volume, self._import = 0.7, None
        self.lib_state = {"filter": "songs", "sort": "default", "mode": "grid", "text": ""}
        self.nav, self.side_items = {}, {}

        self.root.report_callback_exception = self._on_error
        self._styles()
        self.menu = ContextMenu(self.root)
        self.toast = Toast(self.root, bottom_offset=PLAYER_H + 12)
        self._build_player()        # packed first so it spans the full width at the bottom
        body = tk.Frame(self.root, bg=BLACK)
        body.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_sidebar(body)
        self._build_main(body)
        self._bind_keys()
        self.root.update_idletasks()
        self.show_view("home")
        self.refresh_sidebar()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick()

    def run(self):
        self.root.mainloop()

    def _on_error(self, exc_type, exc, tb):
        """Tk calls this for any exception inside a callback: log it, tell the user, keep running."""
        import traceback
        traceback.print_exception(exc_type, exc, tb)
        try:
            self.toast.show(f"Something went wrong: {exc}", "error", 4000)
        except Exception:
            pass

    def on_close(self):
        self.lib.save()
        self.player.shutdown()
        self.root.destroy()

    # ------------------------------------------------------------------ styling
    def _styles(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        name = "Slim.Vertical.TScrollbar"
        s.layout(name, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure(name, background="#4A4A4A", troughcolor=BG, bordercolor=BG, lightcolor="#4A4A4A",
                    darkcolor="#4A4A4A", relief="flat", width=10, gripcount=0)
        s.map(name, background=[("active", "#7A7A7A"), ("pressed", "#9A9A9A")])
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>", self._on_wheel)
        self.root.bind_all("<Button-5>", self._on_wheel)

    def _on_wheel(self, e):
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except Exception:
            w = None
        while w is not None and not getattr(w, "is_scroll", False):
            w = getattr(w, "master", None)
        if w is None:
            return
        if e.num == 4:
            units = -3
        elif e.num == 5:
            units = 3
        elif sys.platform == "darwin":
            units = -int(e.delta) or (-1 if e.delta > 0 else 1)
        else:
            units = -3 * int(e.delta / 120) if abs(e.delta) >= 120 else (-3 if e.delta > 0 else 3)
        self.menu.close()
        w.scroll_units(units)

    # ------------------------------------------------------------------ sidebar
    def _build_sidebar(self, body):
        side = tk.Frame(body, bg=BLACK, width=SIDEBAR_W)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        top = tk.Frame(side, bg=PANEL)
        top.pack(fill="x")
        logo = tk.Frame(top, bg=PANEL)
        logo.pack(fill="x", padx=20, pady=(20, 14))
        self._logo_img = gfx_circle(34, GREEN)
        self._logo_note = gfx_icon("note", 18, BLACK, True)
        lc = tk.Canvas(logo, width=34, height=34, bg=PANEL, highlightthickness=0, bd=0)
        lc.create_image(17, 17, image=self._logo_img)
        lc.create_image(17, 17, image=self._logo_note)
        lc.pack(side="left")
        tk.Label(logo, text="My Music Player", font=F(14, True), fg=WHITE, bg=PANEL).pack(side="left", padx=(10, 0))
        for label, icon, key in NAV:
            item = NavItem(top, icon, label, lambda k=key: self.go(k), outline_when_idle=icon in ("home", "heart", "clock"))
            item.pack(fill="x", padx=8, pady=1)
            self.nav[key] = item
        tk.Frame(top, bg=PANEL, height=10).pack()

        tk.Frame(side, bg=BLACK, height=8).pack()
        lib = tk.Frame(side, bg=PANEL)
        lib.pack(fill="both", expand=True)
        head = tk.Frame(lib, bg=PANEL)
        head.pack(fill="x", padx=20, pady=(18, 12))
        self._lib_icon = gfx_icon("library", 22, GREY, True)
        tk.Label(head, image=self._lib_icon, bg=PANEL).pack(side="left")
        tk.Label(head, text="Playlists", font=F(11, True), fg=GREY, bg=PANEL).pack(side="left", padx=(12, 0))
        pill_row = tk.Frame(lib, bg=PANEL)
        pill_row.pack(fill="x", padx=20, pady=(0, 10))
        Pill(pill_row, "Create Playlist", self.create_playlist, bg=WHITE, icon="plus", h=38).pack(anchor="w")
        self.pl_scroll = ScrollFrame(lib, PANEL)
        self.pl_scroll.pack(fill="both", expand=True, padx=(8, 4), pady=(0, 8))
        self._corners_side = round_corners(top, 10, PANEL, BLACK) + round_corners(lib, 10, PANEL, BLACK)

    def refresh_sidebar(self):
        """Rebuild the playlist list (after create / delete / song added)."""
        inner = self.pl_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        self.side_items = {}
        if not self.lib.playlists:
            tk.Label(inner, text="Create your first playlist\nand it will show up here.", font=F(10),
                     fg=DIM, bg=PANEL, justify="left").pack(anchor="w", padx=14, pady=12)
        for name, ids in self.lib.playlists.items():
            valid = [i for i in ids if i in self.lib.songs]
            item = SideItem(inner, self.art.playlist_cover(name, valid, 48, 6), name,
                            f"Playlist • {len(valid)} songs",
                            lambda n=name: self.navigate("playlist", n),
                            on_menu=lambda e, n=name: self._playlist_menu(e, n))
            item.pack(fill="x", pady=1)
            self.side_items[name] = item
        self._sync_sidebar()

    def _sync_sidebar(self):
        for key, item in self.nav.items():
            item.set_active(self.view[0] == key)
        for name, item in self.side_items.items():
            item.set_active(self.view == ("playlist", name))

    def _playlist_menu(self, e, name):
        ids = [i for i in self.lib.playlists.get(name, []) if i in self.lib.songs]
        items = []
        if ids:
            items.append(("Play", lambda: self.play_song(ids[0], ids)))
            items.append(None)
        items.append(("Delete playlist", lambda: self.delete_playlist(name)))
        self.menu.show(e.x_root, e.y_root, items)

    # ------------------------------------------------------------------ main panel
    def _build_main(self, body):
        self.main = tk.Frame(body, bg=BG)
        self.main.pack(side="left", fill="both", expand=True, padx=(8, 0))
        top = tk.Frame(self.main, bg=BG, height=68)
        top.pack(fill="x")
        top.pack_propagate(False)
        right = tk.Frame(top, bg=BG)
        right.pack(side="right", padx=(0, 20))
        CircleButton(right, 34, self.show_shortcuts, bg=BG, fill=CARD, hover_fill=HOVER2, text="?").pack(side="right", padx=(10, 0))
        Pill(right, "Import Folder", self.import_folder, bg=CARD, fg=WHITE, h=34).pack(side="right", padx=(10, 0))
        Pill(right, "Import Music", self.import_files, bg=WHITE, h=34).pack(side="right")
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", padx=(20, 0))
        self.btn_back = CircleButton(left, 34, self.back, bg=BG, shape="chev_l", icon_px=16)
        self.btn_fwd = CircleButton(left, 34, self.forward, bg=BG, shape="chev_r", icon_px=16)
        self.btn_back.pack(side="left")
        self.btn_fwd.pack(side="left", padx=(8, 0))
        self.searchbox = SearchBox(top, on_change=self._on_query, bg=BG)
        self.searchbox.pack(side="left", fill="x", expand=True, padx=16, pady=14)
        self.content = tk.Frame(self.main, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.content.bind("<Configure>", self._on_resize)
        self._corners_main = round_corners(self.main, 10, BG, BLACK)
        self._update_arrows()

    # ---------- navigation ----------
    def go(self, key):
        self.navigate(key)
        if key == "search":
            self.searchbox.focus_entry()

    def navigate(self, kind, arg=None):
        if (kind, arg) != self.view:
            self.back_stack.append(self.view)
            self.back_stack = self.back_stack[-50:]
            self.fwd_stack = []
        self.show_view(kind, arg)

    def back(self):
        if self.back_stack:
            self.fwd_stack.append(self.view)
            self.show_view(*self.back_stack.pop())

    def forward(self):
        if self.fwd_stack:
            self.back_stack.append(self.view)
            self.show_view(*self.fwd_stack.pop())

    def _update_arrows(self):
        self.btn_back.set_enabled(bool(self.back_stack))
        self.btn_fwd.set_enabled(bool(self.fwd_stack))

    def _on_query(self, _text):
        if self._q_job:
            self.root.after_cancel(self._q_job)
        self._q_job = self.root.after(180, self._apply_query)

    def _apply_query(self):
        self._q_job = None
        if self.view[0] != "search":
            self.navigate("search")
        else:
            self.show_view("search")

    # ---------- resize handling ----------
    def _avail(self):
        w = self.content.winfo_width()
        if w < 100:
            w = self.root.winfo_width() - SIDEBAR_W - 40
        return max(320, w - 2 * PAD)

    def _grid(self, avail=None):
        avail = avail or self._avail()
        gap = 16
        cols = max(2, (avail + gap) // (170 + gap))
        cw = (avail - (cols - 1) * gap) // cols
        return cols, cw, gap

    def _sig_now(self):
        avail = self._avail()
        return (self._grid(avail)[0], max(2, min(4, avail // 230)), avail // 40)

    def _on_resize(self, _e):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(220, self._relayout)

    def _relayout(self):
        self._resize_job = None
        if self.view[0] in ("home", "search", "library") and self._sig_now() != self._sig:
            self.show_view(*self.view, keep_scroll=True)

    # ---------- page switching ----------
    def show_view(self, kind, arg=None, keep_scroll=False):
        scroll_px = 0
        if keep_scroll and self.page is not None:
            try:
                scroll_px = self.page.canvas.canvasy(0)
            except tk.TclError:
                scroll_px = 0
        self._token += 1
        self.menu.close()
        for w in self.content.winfo_children():
            w.destroy()
        self.view, self.page, self.rows, self.selected_row = (kind, arg), None, [], None
        self._exists_cache = {}
        self._sig = self._sig_now()
        builder = {"home": self._page_home, "search": self._page_search, "library": self._page_library,
                   "liked": self._page_liked, "recent": self._page_recent, "playlist": self._page_playlist,
                   "collection": self._page_collection, "queue": self._page_queue}[kind]
        builder(arg) if kind in ("playlist", "collection") else builder()
        self._sync_sidebar()
        self._update_arrows()
        for c in self._corners_main:
            tk.Misc.lift(c)
        if keep_scroll and scroll_px and self.page is not None:
            page = self.page

            def restore():
                try:
                    total = max(1, page.inner.winfo_reqheight())
                    page.set_y(scroll_px / total)
                except tk.TclError:
                    pass
            self.root.after(80, restore)

    def _new_page(self):
        self.page = ScrollFrame(self.content, BG)
        self.page.pack(fill="both", expand=True)
        return self.page.inner

    # ---------- small shared page pieces ----------
    def _gradient(self, parent, tint, height):
        c = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0, bd=0)
        bands = 30
        bh = math.ceil(height / bands)
        for i in range(bands):
            t = i / (bands - 1)
            c.create_rectangle(0, i * bh, 4000, (i + 1) * bh + 1, outline="",
                               fill=lerp(tint, BG, min(1.0, t ** 0.85)))
        c.pack(fill="x")
        return c

    def _exists(self, path):
        if path not in self._exists_cache:
            self._exists_cache[path] = os.path.isfile(path)
        return self._exists_cache[path]

    def _heading(self, parent, text, pady=(28, 12)):
        tk.Label(parent, text=text, font=F(20, True), fg=WHITE, bg=BG).pack(anchor="w", padx=PAD, pady=pady)

    def _empty_library(self, parent):
        EmptyState(parent, "note", "Your library is empty",
                   "Import some MP3 or WAV files and your music will show up here.",
                   buttons=[("Import Music", self.import_files, True),
                            ("Import Folder", self.import_folder, False)]).pack(pady=(70, 0))

    # ---------- card sections ----------
    def _song_items(self, ids, ctx=None):
        ctx = ids if ctx is None else ctx
        out = []
        for sid in ids:
            s = self.lib.get(sid)
            if not s:
                continue
            out.append((lambda size, sid=sid: self.art.get(sid, size, 8), s["title"], s["artist"],
                        lambda sid=sid: self.row_play(sid, ctx),
                        lambda e, sid=sid: self._song_menu(e, sid, ctx)))
        return out

    def _playlist_items(self, names):
        out = []
        for name in names:
            ids = [i for i in self.lib.playlists.get(name, []) if i in self.lib.songs]
            out.append((lambda size, n=name, ids=ids: self.art.playlist_cover(n, ids, size, 8), name,
                        f"Playlist • {len(ids)} songs", lambda n=name: self.navigate("playlist", n),
                        lambda e, n=name: self._playlist_menu(e, n)))
        return out

    def _collection_items(self, names):
        out = []
        for name in names:
            ids = self.collections.get(name, [])
            out.append((lambda size, n=name, ids=ids: self.art.playlist_cover(n, ids, size, 8), name,
                        f"{len(ids)} songs", lambda n=name: self.navigate("collection", n), None))
        return out

    def _section(self, parent, title, items, cols, cw, gap, show_all=None):
        if not items:
            return
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(30, 12))
        tk.Label(head, text=title, font=F(20, True), fg=WHITE, bg=BG).pack(side="left")
        if show_all:
            link = tk.Label(head, text="Show all", font=F(10, True), fg=GREY, bg=BG, cursor="hand2")
            link.pack(side="right")
            link.bind("<Button-1>", lambda e: show_all())
            link.bind("<Enter>", lambda e: link.configure(fg=WHITE))
            link.bind("<Leave>", lambda e: link.configure(fg=GREY))
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", padx=PAD)
        for i, (art_fn, title_, sub, cb, menu) in enumerate(items[:cols]):
            Card(row, art_fn(cw - 24), title_, sub, cb, cw, cw - 24, on_menu=menu).pack(
                side="left", padx=(0 if i == 0 else gap, 0))

    def _fill_grid(self, parent, items, cols, cw, gap, token, start=0):
        """Create cards two rows at a time so big libraries never freeze the window."""
        try:
            if token != self._token or not parent.winfo_exists():
                return
        except tk.TclError:
            return
        end = min(len(items), start + cols * 2)
        for k in range(start, end):
            art_fn, title, sub, cb, menu = items[k]
            Card(parent, art_fn(cw - 24), title, sub, cb, cw, cw - 24, on_menu=menu).grid(
                row=k // cols, column=k % cols, padx=(0, gap), pady=(0, gap), sticky="nw")
        if end < len(items):
            self.root.after(15, self._fill_grid, parent, items, cols, cw, gap, token, end)

    # ---------- collections ("Made for you" etc.) ----------
    def _build_collections(self):
        ids = list(self.lib.all_ids())
        self.collections = {}
        if not ids:
            return
        rnd = random.Random(datetime.now().strftime("%Y-%m-%d") + f"/{len(ids)}")
        shuffled = ids[:]
        rnd.shuffle(shuffled)
        k = 1 + (len(ids) >= 12) + (len(ids) >= 24)
        size = min(30, max(1, math.ceil(len(ids) / k)))
        for n in range(k):
            chunk = shuffled[n * size:(n + 1) * size]
            if chunk:
                self.collections[f"Daily Mix {n + 1}"] = chunk
        popular = [i for i in self.lib.popular(30) if i in self.lib.songs]
        if popular:
            self.collections["Popular Songs"] = popular
        liked_artists = {self.lib.get(i)["artist"] for i in self.lib.liked if i in self.lib.songs}
        recent = set(list(self.lib.recent)[:10])
        scored = []
        for sid in ids:
            s = self.lib.get(sid)
            scored.append(((2 if s["artist"] in liked_artists else 0) + (0 if sid in recent else 1)
                           + rnd.random(), sid))
        scored.sort(reverse=True)
        self.collections["Recommended for You"] = [sid for _, sid in scored[:30]]

    # ------------------------------------------------------------------ HOME
    def _page_home(self):
        p = self._new_page()
        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        hero = self._gradient(p, lerp(BG, GREEN, .38), 130)
        hero.create_text(PAD, 52, anchor="w", text=greet, font=F(30, True), fill=WHITE)
        hero.create_text(PAD, 92, anchor="w", text="Welcome to My Music Player", font=F(11), fill=GREY)
        if not self.lib.songs:
            self._empty_library(p)
            return
        self._build_collections()
        avail = self._avail()
        cols, cw, gap = self._grid(avail)
        tc = max(2, min(4, avail // 230))
        tw = (avail - (tc - 1) * 12) // tc
        lib, all_ids = self.lib, list(self.lib.all_ids())
        recent = [i for i in lib.recent if i in lib.songs]
        tiles = [(self.art.special("liked", 64, 6), "Liked Songs", lambda: self.navigate("liked"))]
        for name, ids in lib.playlists.items():
            valid = [i for i in ids if i in lib.songs]
            tiles.append((self.art.playlist_cover(name, valid, 64, 6), name,
                          lambda n=name: self.navigate("playlist", n)))
        for sid in recent + [i for i in all_ids if i not in recent]:
            tiles.append((self.art.get(sid, 64, 6), lib.get(sid)["title"],
                          lambda sid=sid: self.row_play(sid, all_ids)))
        grid = tk.Frame(p, bg=BG)
        grid.pack(anchor="w", padx=PAD, pady=(4, 0))
        for k, (photo, title, cb) in enumerate(tiles[:tc * 2]):
            Tile(grid, photo, title, cb, tw).grid(row=k // tc, column=k % tc,
                                                  padx=(0, 12 if k % tc < tc - 1 else 0), pady=(0, 12))
        self._section(p, "Recently Played", self._song_items(recent[:cols], recent), cols, cw, gap,
                      show_all=lambda: self.navigate("recent") if len(recent) > cols else None)
        mixes = [n for n in self.collections if n.startswith("Daily Mix")]
        self._section(p, "Made For You", self._collection_items(mixes), cols, cw, gap)
        pop = self.collections.get("Popular Songs", [])
        self._section(p, "Popular Songs", self._song_items(pop[:cols], pop), cols, cw, gap,
                      show_all=lambda: self.navigate("collection", "Popular Songs"))
        self._section(p, "Your Playlists", self._playlist_items(list(lib.playlists)[:cols]), cols, cw, gap,
                      show_all=lambda: self._open_library("playlists"))
        rec = self.collections.get("Recommended for You", [])
        self._section(p, "Recommended Music", self._song_items(rec[:cols], rec), cols, cw, gap,
                      show_all=lambda: self.navigate("collection", "Recommended for You"))
        tk.Frame(p, bg=BG, height=40).pack()

    def _open_library(self, which):
        self.lib_state["filter"] = which
        self.navigate("library")

    # ------------------------------------------------------------------ track tables
    def _make_row(self, parent, i, sid, ids, playlist):
        s = self.lib.get(sid)
        missing = not self._exists(s["path"])
        row = Row(parent, num=i + 1, photo=self.art.get(sid, 40, 4), title=s["title"],
                  sub="File missing" if missing else s["artist"], right=fmt(s["duration"]), sid=sid,
                  liked=self.lib.is_liked(sid), playing=(sid == self.current), missing=missing,
                  on_play=lambda sid=sid: self.row_play(sid, ids),
                  on_menu=lambda e, sid=sid: self._song_menu(e, sid, ids, playlist),
                  on_like=lambda sid=sid: self.toggle_like(sid), on_select=self._select_row)
        if sid == self.current:
            row.set_playing(True, self._audio_on())
        self.rows.append(row)
        return row

    def _select_row(self, row):
        if self.selected_row is not None and self.selected_row is not row:
            try:
                self.selected_row.set_active(False)
            except tk.TclError:
                pass
        self.selected_row = row
        row.set_active(True)

    def _load_rows(self, parent, ids, playlist, token, start=0, batch=24):
        try:
            if token != self._token or not parent.winfo_exists():
                return
        except tk.TclError:
            return
        end = min(len(ids), start + batch)
        for i in range(start, end):
            if self.lib.get(ids[i]):
                self._make_row(parent, i, ids[i], ids, playlist).pack(fill="x")
        if end < len(ids):
            self.root.after(12, self._load_rows, parent, ids, playlist, token, end, 40)

    def _table(self, p, ids, playlist=None):
        """Column header + lazily-built song rows."""
        hd = tk.Canvas(p, height=34, bg=BG, highlightthickness=0, bd=0)
        hd.pack(fill="x", padx=PAD - 12, pady=(6, 4))
        hd.create_text(34, 17, text="#", fill=GREY, font=F(10, True))
        hd.create_text(112, 17, text="TITLE", anchor="w", fill=GREY, font=F(9, True))
        hd.clock = gfx_icon("clock", 16, GREY, False)
        clock = hd.create_image(0, 17, image=hd.clock)
        line = hd.create_line(0, 33, 10, 33, fill=LINE)

        def cfg(e):
            hd.coords(clock, e.width - 70, 17)
            hd.coords(line, 8, 33, e.width - 8, 33)
        hd.bind("<Configure>", cfg)
        frame = tk.Frame(p, bg=BG)
        frame.pack(fill="x", padx=PAD - 12)
        self._load_rows(frame, ids, playlist, self._token)
        tk.Frame(p, bg=BG, height=40).pack()
        return frame

    def _actions(self, p, ids, menu_cb=None):
        act = tk.Frame(p, bg=BG)
        act.pack(fill="x", padx=PAD, pady=(18, 8))
        PlayCircle(act, 56, lambda: self.play_song(ids[0], ids) if ids else None, BG, GREEN).pack(side="left")
        Pill(act, "Shuffle", lambda: self.shuffle_play(ids), bg=CARD, fg=WHITE, icon="shuffle", h=40).pack(
            side="left", padx=(16, 0))
        if menu_cb:
            btn = IconButton(act, "dots", px=24, bg=BG, cmd=lambda: None, pad=8)
            btn.pack(side="left", padx=(12, 0))
            btn.bind("<Button-1>", menu_cb, add="+")   # menu needs the click position
        return act

    def _page_tracks(self, label, title, ids, cover_kind, tint_kind=None, playlist=None, empty=None,
                     cover_name=None, menu_cb=None):
        """Hero header + actions + track table; shared by Liked, Recent, Playlist and collections."""
        p = self._new_page()
        name = cover_name or title
        tint = self.art.tint(tint_kind or (cover_kind if cover_kind in ("liked", "recent", "queue") else None),
                             ids, name)
        hero = self._gradient(p, lerp(BG, tint, .85), 290)
        cover = self.art.hero(cover_kind, 190, 8, ids, name)
        hero.create_image(PAD + 95, 148, image=cover)
        hero.cover = cover
        x0 = PAD + 190 + 30
        total = sum(self.lib.get(i)["duration"] for i in ids if self.lib.get(i))
        meta = f"{len(ids)} songs" + (f"  •  {fmt_long(total)}" if ids else "")
        n = len(title)
        size = 44 if n <= 14 else 34 if n <= 26 else 26
        tw = self._avail() + PAD - x0
        hero.create_text(x0, 112, anchor="w", text=label.upper(), fill=WHITE, font=F(10, True))
        hero.create_text(x0, 160, anchor="w", text=ellipsize(title, font(size, True), tw), fill=WHITE,
                         font=F(size, True))
        hero.create_text(x0, 214, anchor="w", text=meta, fill=GREY, font=F(11))
        if not ids:
            if empty:
                EmptyState(p, *empty[:3], buttons=empty[3] if len(empty) > 3 else ()).pack(pady=(50, 0))
            return
        self._actions(p, ids, menu_cb)
        self._table(p, ids, playlist)

    def _page_liked(self):
        ids = [i for i in self.lib.liked if i in self.lib.songs]
        self._page_tracks("Playlist", "Liked Songs", ids, "liked",
                          empty=("heart", "Songs you like will appear here",
                                 "Save songs by tapping the heart icon next to them."))

    def _page_recent(self):
        ids = [i for i in self.lib.recent if i in self.lib.songs]
        self._page_tracks("History", "Recently Played", ids, "recent",
                          empty=("clock", "Nothing played yet", "Songs you listen to will show up here."))

    def _page_playlist(self, name):
        if name not in self.lib.playlists:
            self.view = ("home", None)
            self._page_home()
            return
        ids = [i for i in self.lib.playlists.get(name, []) if i in self.lib.songs]

        def menu(e):
            self.menu.show(e.x_root, e.y_root, [("Delete playlist", lambda: self.delete_playlist(name))])

        self._page_tracks("Playlist", name, ids, "playlist", playlist=name, cover_name=name, menu_cb=menu,
                          empty=("note", "This playlist is empty",
                                 "Right-click a song in Your Library and choose Add to playlist.",
                                 [("Browse your library", lambda: self.navigate("library"), True)]))

    def _page_collection(self, name):
        ids = [i for i in self.collections.get(name, []) if i in self.lib.songs]
        label = "Made for you" if name.startswith("Daily Mix") else "Collection"
        self._page_tracks(label, name, ids, "collection", cover_name=name,
                          empty=("note", "Nothing here yet", "Import more music to get suggestions."))

    # ------------------------------------------------------------------ QUEUE
    def _page_queue(self):
        p = self._new_page()
        tk.Label(p, text="Queue", font=F(30, True), fg=WHITE, bg=BG).pack(anchor="w", padx=PAD, pady=(14, 4))
        cur = self.lib.get(self.current) if self.current else None
        if not cur:
            EmptyState(p, "queue", "Your queue is empty", "Play a song and what comes next will show up here.",
                       buttons=[("Browse your library", lambda: self.navigate("library"), True)]).pack(pady=(60, 0))
            return
        self._heading(p, "Now playing", (18, 6))
        now = tk.Frame(p, bg=BG)
        now.pack(fill="x", padx=PAD - 12)
        self._load_rows(now, [self.current], None, self._token)
        q = self.queue
        idx = q.index(self.current) if self.current in q else -1
        upcoming = [i for i in q[idx + 1:] if i in self.lib.songs]
        self._heading(p, "Next up", (24, 6))
        if self.shuffle:
            tk.Label(p, text="Shuffle is on, so the next song is picked at random.", font=F(10), fg=GREY,
                     bg=BG).pack(anchor="w", padx=PAD, pady=(0, 8))
        if upcoming:
            rows = tk.Frame(p, bg=BG)
            rows.pack(fill="x", padx=PAD - 12)
            self._load_rows(rows, upcoming, None, self._token)
        else:
            tk.Label(p, text="Nothing else in the queue.", font=F(11), fg=GREY, bg=BG).pack(anchor="w", padx=PAD, pady=8)
        tk.Frame(p, bg=BG, height=40).pack()

    # ------------------------------------------------------------------ SEARCH
    def _page_search(self):
        p = self._new_page()
        q = self.searchbox.get()
        if not self.lib.songs:
            self._empty_library(p)
            return
        if not q:
            self._heading(p, "Browse all", (14, 14))
            groups = {}
            for sid in self.lib.all_ids():
                groups.setdefault(self.lib.get(sid)["artist"] or "Unknown artist", []).append(sid)
            avail = self._avail()
            tc = max(2, avail // 200)
            tw = (avail - (tc - 1) * 16) // tc
            grid = tk.Frame(p, bg=BG)
            grid.pack(anchor="w", padx=PAD)
            ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))[:36]
            for k, (artist, sids) in enumerate(ordered):
                art_sid = next((s for s in sids if self.art.has_art(s)), None)
                photo = self.art.tilted(art_sid, 68) if art_sid else None
                ColorTile(grid, tw, name_color(artist), artist, photo,
                          lambda a=artist: self.searchbox.set(a)).grid(
                    row=k // tc, column=k % tc, padx=(0, 16 if k % tc < tc - 1 else 0), pady=(0, 16))
            tk.Frame(p, bg=BG, height=30).pack()
            return
        ids = [i for i in self.lib.search(q) if i in self.lib.songs]
        tk.Label(p, text=f"Results for “{q}”", font=F(24, True), fg=WHITE, bg=BG).pack(anchor="w", padx=PAD, pady=(14, 0))
        tk.Label(p, text=f"{len(ids)} song{'s' if len(ids) != 1 else ''}", font=F(10), fg=GREY, bg=BG).pack(
            anchor="w", padx=PAD, pady=(2, 8))
        if not ids:
            EmptyState(p, "search", f"No results found for “{q}”",
                       "Check the spelling or try a different title or artist.").pack(pady=(50, 0))
            return
        self._table(p, ids)

    # ------------------------------------------------------------------ LIBRARY
    def _page_library(self):
        p = self._new_page()
        lib, st = self.lib, self.lib_state
        tk.Label(p, text="Your Library", font=F(30, True), fg=WHITE, bg=BG).pack(anchor="w", padx=PAD, pady=(14, 0))
        tk.Label(p, text=f"{len(lib.songs)} songs  •  {len(lib.playlists)} playlists", font=F(10), fg=GREY,
                 bg=BG).pack(anchor="w", padx=PAD, pady=(2, 0))
        if not lib.songs and not lib.playlists:
            self._empty_library(p)
            return
        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", padx=PAD, pady=(18, 14))
        self.chips = {}
        for key, label in (("songs", "Songs"), ("playlists", "Playlists")):
            chip = Chip(bar, label, lambda k=key: self._set_lib("filter", k), active=st["filter"] == key)
            chip.pack(side="left", padx=(0, 8))
            self.chips[key] = chip
        self.view_btns = {}
        for mode, icon in (("list", "list"), ("grid", "grid")):
            b = IconButton(bar, icon, px=20, bg=BG, color=WHITE if st["mode"] == mode else DIM,
                           cmd=lambda m=mode: self._set_lib("mode", m))
            b.pack(side="right")
            self.view_btns[mode] = b
        self.sort_btn = tk.Frame(bar, bg=BG, cursor="hand2")
        self.sort_btn.pack(side="right", padx=(0, 10))
        self._sort_label = tk.Label(self.sort_btn, font=F(10, True), fg=GREY, bg=BG, cursor="hand2")
        self._sort_label.pack(side="left")
        self._sort_icon = gfx_icon("chev_d", 14, GREY, True)
        arrow = tk.Label(self.sort_btn, image=self._sort_icon, bg=BG, cursor="hand2")
        arrow.pack(side="left", padx=(4, 0))
        for w in (self.sort_btn, self._sort_label, arrow):
            w.bind("<Button-1>", self._sort_menu)
        self.filter_box = SearchBox(bar, placeholder="Filter library", bg=BG, max_w=220, h=34, icon_px=16,
                                    width=200, on_change=self._on_lib_filter)
        self.filter_box.pack(side="right", padx=(0, 14))
        if st["text"]:
            self.filter_box.set(st["text"])
        self.lib_body = tk.Frame(p, bg=BG)
        self.lib_body.pack(fill="both", expand=True)
        self._render_library_body()

    def _set_lib(self, key, value):
        st = self.lib_state
        if key == "filter" and st["filter"] != value:
            st["sort"] = "default"
        st[key] = value
        for k, chip in self.chips.items():
            chip.set_active(k == st["filter"])
        for m, b in self.view_btns.items():
            b.set(color=WHITE if m == st["mode"] else DIM)
        self._render_library_body()

    def _on_lib_filter(self, text):
        self.lib_state["text"] = text.strip()
        if self._lib_job:
            self.root.after_cancel(self._lib_job)
        self._lib_job = self.root.after(160, self._render_library_body)

    def _sort_menu(self, e):
        options = SORTS_SONGS if self.lib_state["filter"] == "songs" else SORTS_LISTS
        items = [(("✓  " if v == self.lib_state["sort"] else "     ") + label,
                  lambda v=v: self._set_lib("sort", v)) for label, v in options]
        x = self.sort_btn.winfo_rootx()
        y = self.sort_btn.winfo_rooty() + self.sort_btn.winfo_height() + 4
        self.menu.show(x, y, items)

    def _render_library_body(self):
        self._lib_job = None
        try:
            body = self.lib_body
            if not body.winfo_exists():
                return
        except (AttributeError, tk.TclError):
            return
        self._token += 1
        token = self._token
        for w in body.winfo_children():
            w.destroy()
        self.rows, self.selected_row = [], None
        lib, st = self.lib, self.lib_state
        options = SORTS_SONGS if st["filter"] == "songs" else SORTS_LISTS
        self._sort_label.configure(text=dict((v, l) for l, v in options).get(st["sort"], "Default order"))
        q = st["text"].lower()
        cols, cw, gap = self._grid()
        if st["filter"] == "songs":
            ids = list(lib.all_ids())
            if q:
                ids = [i for i in ids if q in lib.get(i)["title"].lower() or q in lib.get(i)["artist"].lower()]
            key = st["sort"]
            if key == "title":
                ids.sort(key=lambda i: lib.get(i)["title"].lower())
            elif key == "artist":
                ids.sort(key=lambda i: (lib.get(i)["artist"].lower(), lib.get(i)["title"].lower()))
            elif key == "duration":
                ids.sort(key=lambda i: lib.get(i)["duration"] or 0)
            elif key == "recent":
                order = {s: n for n, s in enumerate(lib.recent)}
                ids.sort(key=lambda i: order.get(i, 10 ** 9))
            if not ids:
                EmptyState(body, "search", "No songs match your filter", "Try a different word.").pack(pady=(50, 0))
                return
            if st["mode"] == "grid":
                grid = tk.Frame(body, bg=BG)
                grid.pack(anchor="w", padx=PAD)
                self._fill_grid(grid, self._song_items(ids), cols, cw, gap, token)
            else:
                self._table_into(body, ids)
        else:
            entries = [("Liked Songs", "liked", [i for i in lib.liked if i in lib.songs])]
            for name, pids in lib.playlists.items():
                entries.append((name, "playlist", [i for i in pids if i in lib.songs]))
            if q:
                entries = [e for e in entries if q in e[0].lower()]
            if st["sort"] == "title":
                entries.sort(key=lambda e: e[0].lower())
            elif st["sort"] == "count":
                entries.sort(key=lambda e: -len(e[2]))
            if not entries:
                EmptyState(body, "search", "No playlists match your filter", "Try a different word.").pack(pady=(50, 0))
                return
            if st["mode"] == "grid":
                items = []
                for name, kind, ids in entries:
                    opener = (lambda: self.navigate("liked")) if kind == "liked" else \
                        (lambda n=name: self.navigate("playlist", n))
                    art = (lambda size, k=kind, n=name, ids=ids:
                           self.art.special("liked", size, 8) if k == "liked"
                           else self.art.playlist_cover(n, ids, size, 8))
                    menu = None if kind == "liked" else (lambda e, n=name: self._playlist_menu(e, n))
                    items.append((art, name, f"Playlist • {len(ids)} songs", opener, menu))
                grid = tk.Frame(body, bg=BG)
                grid.pack(anchor="w", padx=PAD)
                self._fill_grid(grid, items, cols, cw, gap, token)
            else:
                frame = tk.Frame(body, bg=BG)
                frame.pack(fill="x", padx=PAD - 12)
                for name, kind, ids in entries:
                    photo = self.art.special("liked", 40, 4) if kind == "liked" else \
                        self.art.playlist_cover(name, ids, 40, 4)
                    opener = (lambda: self.navigate("liked")) if kind == "liked" else \
                        (lambda n=name: self.navigate("playlist", n))
                    Row(frame, photo=photo, title=name, sub="Playlist", right=f"{len(ids)} songs",
                        on_open=opener).pack(fill="x")
        tk.Frame(body, bg=BG, height=40).pack()

    def _table_into(self, body, ids):
        frame = tk.Frame(body, bg=BG)
        frame.pack(fill="x", padx=PAD - 12)
        self._load_rows(frame, ids, None, self._token)

    # ------------------------------------------------------------------ context menus
    def _song_menu(self, e, sid, ctx, playlist=None):
        lib = self.lib
        liked = lib.is_liked(sid)
        sub = [(n, lambda n=n: self._add_to_playlist(n, sid)) for n in lib.playlists]
        if sub:
            sub.append(None)
        sub.append(("New playlist…", lambda: self.create_playlist(add_song=sid)))
        items = [("Play", lambda: self.play_song(sid, ctx)),
                 ("Add to queue", lambda: self.add_to_queue(sid)), None,
                 ("Remove from Liked Songs" if liked else "Save to Liked Songs", lambda: self.toggle_like(sid)),
                 ("Add to playlist", sub)]
        if playlist:
            items.append(("Remove from this playlist", lambda: self._remove_from_playlist(playlist, sid)))
        items += [None, ("Remove from library", lambda: self.remove_song(sid))]
        self.menu.show(e.x_root, e.y_root, items)

    def _add_to_playlist(self, name, sid):
        self.lib.add_to_playlist(name, sid)
        self.toast.show(f"Added to {name}")
        self.refresh_sidebar()

    def _remove_from_playlist(self, name, sid):
        self.lib.remove_from_playlist(name, sid)
        self.refresh_sidebar()
        self.show_view(*self.view, keep_scroll=True)

    def add_to_queue(self, sid):
        if not self.current:
            self.queue = [sid]
            self.toast.show("Added to queue")
            return
        self.queue = [i for i in self.queue if i != sid or i == self.current]
        pos = self.queue.index(self.current) + 1 if self.current in self.queue else len(self.queue)
        self.queue.insert(pos, sid)
        self.toast.show("Added to queue")
        if self.view[0] == "queue":
            self.show_view("queue", keep_scroll=True)

    # ------------------------------------------------------------------ bottom player bar
    def _build_player(self):
        bar = tk.Frame(self.root, bg=BLACK, height=PLAYER_H)
        bar.pack(side="bottom", fill="x")
        bar.grid_propagate(False)
        bar.grid_rowconfigure(0, weight=1)
        bar.grid_columnconfigure(0, weight=3, uniform="bar")
        bar.grid_columnconfigure(1, weight=4, uniform="bar")
        bar.grid_columnconfigure(2, weight=3, uniform="bar")

        # --- left: now playing
        self.np = tk.Canvas(bar, bg=BLACK, highlightthickness=0, bd=0, height=PLAYER_H)
        self.np.grid(row=0, column=0, sticky="nsew", padx=(16, 8))
        self.np_photo = self.art.get(None, 56, 6)
        self.np_art = self.np.create_image(0, PLAYER_H // 2, anchor="w", image=self.np_photo)
        self.np_title = self.np.create_text(72, PLAYER_H // 2 - 11, anchor="w", text="Nothing playing", fill=WHITE,
                                            font=F(11, True))
        self.np_artist = self.np.create_text(72, PLAYER_H // 2 + 11, anchor="w", text="", fill=GREY, font=F(10))
        self.heart = IconButton(self.np, "heart", px=18, bg=BLACK, filled=False, cmd=self._like_current)
        self.np_heart = self.np.create_window(0, PLAYER_H // 2, window=self.heart, anchor="e")
        self._np_text = ("Nothing playing", "")
        self.np.bind("<Configure>", self._np_layout)

        # --- centre: transport + progress
        mid = tk.Frame(bar, bg=BLACK)
        mid.grid(row=0, column=1, sticky="nsew", padx=8)
        ctrl = tk.Frame(mid, bg=BLACK)
        ctrl.pack(pady=(13, 0))
        self.btn_shuffle = IconButton(ctrl, "shuffle", px=18, cmd=self.toggle_shuffle)
        self.btn_prev = IconButton(ctrl, "prev", px=18, hover=WHITE, cmd=self.prev_song)
        self.play_btn = PlayCircle(ctrl, 36, self.toggle_play, BLACK)
        self.btn_next = IconButton(ctrl, "next", px=18, cmd=self.next_song)
        self.btn_repeat = IconButton(ctrl, "repeat", px=18, cmd=self.toggle_repeat)
        for w in (self.btn_shuffle, self.btn_prev, self.play_btn, self.btn_next, self.btn_repeat):
            w.pack(side="left", padx=5)
        prog = tk.Frame(mid, bg=BLACK)
        prog.pack(fill="x", padx=4, pady=(0, 6))
        self.t_cur = tk.Label(prog, text="0:00", font=F(9), fg=GREY, bg=BLACK, width=5, anchor="e")
        self.t_cur.pack(side="left")
        self.t_tot = tk.Label(prog, text="0:00", font=F(9), fg=GREY, bg=BLACK, width=5, anchor="w")
        self.t_tot.pack(side="right")
        self.progress = Slider(prog, 300, bg=BLACK, color=GREEN, hover_color=GREEN,
                               on_change=lambda v: self.t_cur.config(text=fmt(v * self.cur_duration)),
                               on_release=self.on_seek)
        self.progress.pack(side="left", fill="x", expand=True, padx=4)

        # --- right: queue, stop, volume
        right = tk.Frame(bar, bg=BLACK)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 16))
        box = tk.Frame(right, bg=BLACK)
        box.place(relx=1.0, rely=0.5, anchor="e")
        self.btn_queue = IconButton(box, "queue", px=18, cmd=lambda: self.navigate("queue"))
        self.btn_stop = IconButton(box, "stop", px=16, cmd=self.stop)
        self.vol_icon = IconButton(box, "volume", px=20, cmd=self.toggle_mute)
        self.vol_slider = Slider(box, 110, bg=BLACK, on_change=self._set_volume, value=self.player.volume)
        for w in (self.btn_queue, self.btn_stop, self.vol_icon):
            w.pack(side="left", padx=2)
        self.vol_slider.pack(side="left", padx=(4, 0))
        self._vol_icon_sync(self.player.volume)

    def _np_layout(self, e):
        w = e.width
        self.np.coords(self.np_heart, w - 4, PLAYER_H // 2)
        self._np_ellipsize()

    def _np_ellipsize(self):
        w = self.np.winfo_width()
        px = max(40, w - 72 - 52)
        title, artist = self._np_text
        self.np.itemconfig(self.np_title, text=ellipsize(title, font(11, True), px))
        self.np.itemconfig(self.np_artist, text=ellipsize(artist, font(10), px))

    # ---------- volume ----------
    def _vol_icon_sync(self, v):
        self.vol_icon.set(shape="mute" if v <= 0.001 else "volume_low" if v < 0.4 else "volume")

    def _set_volume(self, v):
        self.player.set_volume(v)
        self._vol_icon_sync(v)

    def _bump_volume(self, delta):
        v = min(1.0, max(0.0, self.player.volume + delta))
        self._set_volume(v)
        self.vol_slider.set(v)

    def toggle_mute(self):
        if self.player.volume > 0.001:
            self._prev_volume = self.player.volume
            self._set_volume(0.0)
            self.vol_slider.set(0.0)
        else:
            self._set_volume(self._prev_volume or 0.7)
            self.vol_slider.set(self._prev_volume or 0.7)

    # ------------------------------------------------------------------ playback logic
    def _audio_on(self):
        return bool(self.player.playing and not self.player.paused)

    def row_play(self, sid, ctx=None):
        """Row/card click: pause/resume if it is the current song, otherwise start it."""
        if sid == self.current and self.player.playing:
            self.toggle_play()
        else:
            self.play_song(sid, ctx)

    def play_song(self, sid, ctx=None, record=True):
        s = self.lib.get(sid)
        if not s:
            return False
        if not os.path.isfile(s["path"]):
            self._exists_cache[s["path"]] = False
            self.toast.show(f"Can't find “{s['title']}” — the file was moved or deleted.", "error", 4200)
            return False
        try:
            self.player.play(s["path"], s["duration"])
        except Exception as exc:
            self.toast.show(f"“{s['title']}” could not be played: {exc}", "error", 4800)
            return False
        if ctx is not None:
            self.queue = list(ctx)
        elif sid not in self.queue:
            self.queue = [sid]
        if record and self.current and self.current != sid:
            self.history = (self.history + [self.current])[-100:]
        self.current, self.cur_duration = sid, s["duration"]
        self.lib.add_recent(sid)
        self._update_now_playing()
        self._highlight()
        return True

    def shuffle_play(self, ids):
        if not ids:
            return
        self.shuffle = True
        self.play_song(random.choice(ids), ids)
        self._update_buttons()

    def toggle_play(self):
        p = self.player
        if p.playing:
            p.resume() if p.paused else p.pause()
            self._update_buttons()
        elif self.current and self.lib.get(self.current):
            self.play_song(self.current, record=False)
        elif self.lib.songs:
            ids = self.lib.all_ids()
            self.play_song(random.choice(ids) if self.shuffle else ids[0], ids)
        else:
            self.toast.show("Import some MP3 or WAV files first.", "error")

    def stop(self):
        self.player.stop()
        self.progress.set(0)
        self.t_cur.config(text="0:00")
        self._update_buttons()

    def next_song(self, auto=False):
        q = self.queue
        if not q:
            return
        if self.shuffle and len(q) > 1:
            nxt = random.choice([i for i in q if i != self.current])
        else:
            idx = q.index(self.current) if self.current in q else -1
            if idx + 1 < len(q):
                nxt = q[idx + 1]
            elif self.repeat == 1 or not auto:
                nxt = q[0]
            else:
                self.stop()
                return
        self.play_song(nxt)

    def prev_song(self):
        q = self.queue
        if not q or not self.current:
            return
        if self.player.position() > 3:
            self.play_song(self.current, record=False)
        elif self.shuffle and self.history:
            self.play_song(self.history.pop(), record=False)
        else:
            idx = q.index(self.current) if self.current in q else 0
            self.play_song(q[idx - 1], record=False)

    def on_seek(self, frac):
        if self.current and self.player.playing and self.cur_duration:
            self.player.seek(frac * self.cur_duration)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self._update_buttons()

    def toggle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        self._update_buttons()

    def _tick(self):
        """Runs every 250 ms via after(): progress bar, song end detection, equaliser."""
        try:
            self._tick_body()
        except Exception:
            pass                       # a bad frame must never stop the timer
        self.root.after(250, self._tick)

    def _tick_body(self):
        p = self.player
        if p.playing:
            if not self.progress.dragging:
                pos = p.position()
                self.progress.set(pos / self.cur_duration if self.cur_duration else 0)
                self.t_cur.config(text=fmt(pos))
            if p.finished():
                if self.repeat == 2:
                    self.play_song(self.current, record=False)
                else:
                    self.next_song(auto=True)
            for r in self.rows:
                try:
                    r.animate()
                except tk.TclError:
                    pass

    # ------------------------------------------------------------------ UI sync
    def _update_buttons(self):
        self.play_btn.set(self._audio_on())
        self.btn_shuffle.set(color=GREEN if self.shuffle else GREY)
        self.btn_repeat.set(shape="repeat1" if self.repeat == 2 else "repeat", color=GREEN if self.repeat else GREY)
        self._highlight()

    def _update_now_playing(self):
        s = self.lib.get(self.current) if self.current else None
        self.np_photo = self.art.get(self.current if s else None, 56, 6)
        self.np.itemconfig(self.np_art, image=self.np_photo)
        self._np_text = (s["title"], s["artist"]) if s else ("Nothing playing", "")
        self._np_ellipsize()
        self.t_tot.config(text=fmt(s["duration"]) if s else "0:00")
        liked = bool(s and self.lib.is_liked(s["id"]))
        self.heart.set(color=GREEN if liked else GREY, filled=liked)
        self._update_buttons()

    def _highlight(self):
        on = self._audio_on()
        for r in self.rows:
            try:
                r.set_playing(r.sid is not None and r.sid == self.current, on)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ likes / library / playlists
    def toggle_like(self, sid):
        liked = self.lib.toggle_like(sid)
        if sid == self.current:
            self._update_now_playing()
        self.toast.show("Added to Liked Songs" if liked else "Removed from Liked Songs")
        if self.view[0] == "liked":
            self.show_view("liked", keep_scroll=True)
            return
        for r in self.rows:
            if r.sid == sid:
                try:
                    r.set_liked(liked)
                except tk.TclError:
                    pass

    def _like_current(self):
        if self.current:
            self.toggle_like(self.current)

    def remove_song(self, sid):
        if self.current == sid:
            self.stop()
            self.current = None
            self._update_now_playing()
        self.queue = [i for i in self.queue if i != sid]
        self.lib.remove_song(sid)
        self.toast.show("Removed from library")
        self.refresh_sidebar()
        self.show_view(*self.view, keep_scroll=True)

    def create_playlist(self, add_song=None):
        name = Modal(self.root, "Create playlist", "Give your playlist a name.", entry=True,
                     initial="My Playlist", ok="Create").run()
        if not name or not name.strip():
            return
        name = name.strip()
        if not self.lib.create_playlist(name):
            self.toast.show("A playlist with that name already exists.", "error", 3600)
            return
        if add_song:
            self.lib.add_to_playlist(name, add_song)
            self.toast.show(f"Added to {name}")
            self.refresh_sidebar()
            if self.view[0] in ("library", "home"):
                self.show_view(*self.view, keep_scroll=True)
        else:
            self.refresh_sidebar()
            self.navigate("playlist", name)

    def delete_playlist(self, name):
        if not Modal(self.root, "Delete playlist", f"Delete “{name}”? The songs stay in your library.",
                     ok="Delete", danger=True).run():
            return
        self.lib.delete_playlist(name)
        self.refresh_sidebar()
        if self.view == ("playlist", name):
            self.back_stack = [v for v in self.back_stack if v != ("playlist", name)]
            self.navigate("home")
        else:
            self.show_view(*self.view, keep_scroll=True)

    # ------------------------------------------------------------------ importing
    def import_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="Import music",
                                            filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")])
        self._add_paths(paths)

    def import_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Import a music folder")
        if folder:
            paths = [os.path.join(r, f) for r, _, files in os.walk(folder) for f in files
                     if f.lower().endswith(SUPPORTED_EXTENSIONS)]
            if not paths:
                self.toast.show("No supported audio files found in that folder.", "error", 3600)
                return
            self._add_paths(paths)

    def _add_paths(self, paths):
        paths = list(paths or [])
        if not paths:
            return
        if self._import:                      # already importing: just queue more
            self._import["queue"].extend(paths)
            self._import["total"] += len(paths)
            return
        self._import = {"queue": paths, "total": len(paths), "done": 0, "ok": 0, "dupes": 0, "failed": [],
                        "was_empty": not self.lib.songs}
        self._import_step()

    def _import_step(self):
        st = self._import
        if not st["queue"]:
            self._import_done()
            return
        path = st["queue"].pop(0)
        try:
            _song, is_new = self.lib.import_file(path)
            if is_new:
                st["ok"] += 1
            else:
                st["dupes"] += 1
        except ValueError as exc:
            st["failed"].append(f"{os.path.basename(path)}: {exc}")
        except Exception as exc:               # never let one bad file crash the import
            st["failed"].append(f"{os.path.basename(path)}: {exc}")
        st["done"] += 1
        self.toast.progress(f"Importing {st['done']} of {st['total']}…  {os.path.basename(path)[:30]}",
                            st["done"] / st["total"])
        self.root.after(1, self._import_step)

    def _import_done(self):
        st, self._import = self._import, None
        failed = st["failed"]
        if st["ok"]:
            self.toast.show(f"Imported {st['ok']} song{'s' if st['ok'] != 1 else ''}"
                            + (f" ({len(failed)} skipped)" if failed else ""), "success", 3200)
        elif st["dupes"] and not failed:
            self.toast.show("Those songs are already in your library.", "success", 3200)
        else:
            self.toast.hide()
        self.refresh_sidebar()
        if self.view[0] in ("home", "library", "search") or st["was_empty"]:
            if st["was_empty"] and self.view[0] not in ("home", "library", "search"):
                self.navigate("library")
            else:
                self.show_view(*self.view)
        if failed:
            Modal(self.root, "Some files were skipped",
                  "\n".join(failed[:10]) + ("\n…" if len(failed) > 10 else ""), ok="OK", cancel=None, width=520).run()

    # ------------------------------------------------------------------ keyboard
    def _typing(self):
        try:
            return isinstance(self.root.focus_get(), tk.Entry)
        except Exception:
            return False

    def _key(self, fn, always=False):
        def handler(_e):
            if always or not self._typing():
                fn()
                return "break"
        return handler

    def _bind_keys(self):
        r = self.root
        r.bind("<space>", self._key(self.toggle_play))
        r.bind("<Key-m>", self._key(self.toggle_mute))
        r.bind(f"<{MOD}-Right>", self._key(self.next_song, True))
        r.bind(f"<{MOD}-Left>", self._key(self.prev_song, True))
        r.bind(f"<{MOD}-Up>", self._key(lambda: self._bump_volume(.05), True))
        r.bind(f"<{MOD}-Down>", self._key(lambda: self._bump_volume(-.05), True))
        r.bind(f"<{MOD}-s>", self._key(self.toggle_shuffle, True))
        r.bind(f"<{MOD}-r>", self._key(self.toggle_repeat, True))
        r.bind(f"<{MOD}-l>", self._key(self._like_current, True))
        r.bind(f"<{MOD}-k>", self._key(lambda: self.go("search"), True))
        r.bind(f"<{MOD}-f>", self._key(lambda: self.go("search"), True))
        r.bind(f"<{MOD}-n>", self._key(self.create_playlist, True))
        r.bind(f"<{MOD}-o>", self._key(self.import_files, True))
        r.bind("<Alt-Left>", self._key(self.back, True))
        r.bind("<Alt-Right>", self._key(self.forward, True))
        r.bind("<F1>", self._key(self.show_shortcuts, True))

    def show_shortcuts(self):
        text = "\n".join(f"{k}   —   {v}" for k, v in SHORTCUTS)
        Modal(self.root, "Keyboard shortcuts", text, ok="Got it", cancel=None, width=480).run()


if __name__ == "__main__":
    App().run()