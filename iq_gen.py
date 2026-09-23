"""Rasmli IQ savollari generatori: Raven uslubidagi matritsalar, figuralar
ketma-ketligi va «ortiqcha figura» topshiriqlari.

Savollar qat'iy `seed` bilan yaratiladi — har ishga tushishda bir xil bank
chiqadi, shuning uchun bazadagi takrorlar fingerprint orqali tushib qoladi.
Rasmlar `media_dir` ichiga PNG bo'lib yoziladi, savolda esa ularga nisbiy
yo'l saqlanadi (masalan ``iq/m3_05.png``).
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

CELL = 150          # bitta katak (px)
SS = 3              # supersampling — silliq chiziqlar uchun
INK = (25, 25, 25)
GRAY = (160, 160, 160)
BG = (255, 255, 255)
LINE = (70, 70, 70)

SHAPES = ["circle", "square", "triangle", "diamond", "pentagon", "hexagon", "star", "cross"]
FILLS = ["empty", "solid", "gray", "striped"]
RADII = [0.12, 0.17, 0.22]          # o'lcham darajalari (katak ulushi)
COUNTS = [1, 2, 3, 4]

SHAPE_UZ = {"circle": "doira", "square": "kvadrat", "triangle": "uchburchak",
            "diamond": "romb", "pentagon": "beshburchak", "hexagon": "oltiburchak",
            "star": "yulduz", "cross": "xoch", "arrow": "strelka"}
FILL_UZ = {"empty": "bo'sh", "solid": "qora", "gray": "kulrang", "striped": "shtrixli"}
ATTR_UZ = {"shape": "shakl turi", "count": "shakllar soni", "size": "o'lcham",
           "fill": "bo'yoq", "rot": "yo'nalish"}

LAYOUT = {
    1: [(0.5, 0.5)],
    2: [(0.28, 0.5), (0.72, 0.5)],
    3: [(0.5, 0.27), (0.27, 0.73), (0.73, 0.73)],
    4: [(0.27, 0.27), (0.73, 0.27), (0.27, 0.73), (0.73, 0.73)],
}


# ------------------------------------------------------------------ chizish
def font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "LiberationSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _polygon(cx: float, cy: float, r: float, shape: str, rot_deg: float) -> list[tuple]:
    def regular(n: int, start: float) -> list[tuple]:
        return [(cx + r * math.cos(math.radians(start + rot_deg + i * 360 / n)),
                 cy + r * math.sin(math.radians(start + rot_deg + i * 360 / n)))
                for i in range(n)]

    if shape == "square":
        return regular(4, 45)
    if shape == "diamond":
        return regular(4, -90)
    if shape == "triangle":
        return regular(3, -90)
    if shape == "pentagon":
        return regular(5, -90)
    if shape == "hexagon":
        return regular(6, 0)
    if shape == "star":
        pts = []
        for i in range(10):
            rr = r if i % 2 == 0 else r * 0.45
            a = math.radians(-90 + rot_deg + i * 36)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        return pts
    if shape == "cross":
        w = r * 0.36
        raw = [(-w, -r), (w, -r), (w, -w), (r, -w), (r, w), (w, w), (w, r), (-w, r),
               (-w, w), (-r, w), (-r, -w), (-w, -w)]
    elif shape == "arrow":
        raw = [(0, -r), (r * 0.75, -r * 0.1), (r * 0.3, -r * 0.1), (r * 0.3, r),
               (-r * 0.3, r), (-r * 0.3, -r * 0.1), (-r * 0.75, -r * 0.1)]
    else:
        raise ValueError(shape)
    a = math.radians(rot_deg)
    return [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a))
            for x, y in raw]


def _stripes(size: tuple[int, int], step: int, width: int) -> Image.Image:
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    w, h = size
    for x in range(-h, w, step):
        d.line([(x, h), (x + h, 0)], fill=INK, width=width)
    return img


def draw_figure(spec: dict, size: int = CELL) -> Image.Image:
    """spec: {shape, count, size, fill, rot} -> katak rasmi."""
    s = size * SS
    img = Image.new("RGB", (s, s), BG)
    r = RADII[spec["size"]] * s
    outline = max(2, round(s * 0.018))
    fill = FILLS[spec["fill"]]
    for fx, fy in LAYOUT[spec["count"]]:
        cx, cy = fx * s, fy * s
        mask = Image.new("L", (s, s), 0)
        md = ImageDraw.Draw(mask)
        if spec["shape"] == "circle":
            box = [cx - r, cy - r, cx + r, cy + r]
            md.ellipse(box, fill=255)
        else:
            pts = _polygon(cx, cy, r, spec["shape"], spec["rot"] * 45)
            md.polygon(pts, fill=255)
        if fill == "solid":
            img.paste(INK, mask=mask)
        elif fill == "gray":
            img.paste(GRAY, mask=mask)
        elif fill == "striped":
            img.paste(_stripes((s, s), round(s * 0.05), max(2, round(s * 0.012))), mask=mask)
        else:
            img.paste(BG, mask=mask)
        d = ImageDraw.Draw(img)
        if spec["shape"] == "circle":
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=outline)
        else:
            d.polygon(pts, outline=INK, width=outline)
    return img.resize((size, size), Image.LANCZOS)


def _question_mark(size: int = CELL) -> Image.Image:
    img = Image.new("RGB", (size, size), (246, 246, 246))
    d = ImageDraw.Draw(img)
    f = font(int(size * 0.5))
    d.text((size / 2, size / 2), "?", fill=(120, 120, 120), font=f, anchor="mm")
    return img


def draw_grid(cells: list[list[dict | None]]) -> Image.Image:
    """Kataklar to'ri; None — «?» katagi."""
    rows, cols = len(cells), len(cells[0])
    pad = 6
    w, h = cols * CELL + (cols + 1) * pad, rows * CELL + (rows + 1) * pad
    img = Image.new("RGB", (w, h), LINE)
    for r, row in enumerate(cells):
        for c, spec in enumerate(row):
            tile = _question_mark() if spec is None else draw_figure(spec)
            img.paste(tile, (pad + c * (CELL + pad), pad + r * (CELL + pad)))
    return img


# ------------------------------------------------------------- qoidalar
def key(spec: dict) -> tuple:
    """Ko'rinishi bir xil figuralar uchun bir xil kalit (burilish faqat strelkada)."""
    return (spec["shape"], spec["count"], spec["size"], spec["fill"],
            spec["rot"] if spec["shape"] == "arrow" else 0)


class Rule:
    def __init__(self, attr: str, kind: str, fn: Callable[[int, int], object],
                 values: list, text: str):
        self.attr, self.kind, self.fn, self.values, self.text = attr, kind, fn, values, text


def _domain(attr: str) -> list:
    return {"shape": [s for s in SHAPES], "count": COUNTS, "size": [0, 1, 2],
            "fill": list(range(len(FILLS))), "rot": list(range(8))}[attr]


def _rule(rng: random.Random, attr: str, kind: str) -> Rule:
    if kind == "const":
        v = rng.choice(_domain(attr))
        if attr == "size":
            v = rng.choice([1, 2])
        return Rule(attr, kind, lambda r, c, v=v: v, [v], "")
    if kind == "row":
        vals = rng.sample(_domain(attr), 3)
        return Rule(attr, kind, lambda r, c, v=vals: v[r], vals,
                    f"har qatorda {ATTR_UZ[attr]} o'zgarmaydi")
    if kind == "dist":
        vals = rng.sample(_domain(attr), 3)
        sh = rng.choice([1, 2])
        return Rule(attr, kind, lambda r, c, v=vals, sh=sh: v[(c + r * sh) % 3], vals,
                    f"har qator va ustunda uchta {ATTR_UZ[attr]} bir martadan uchraydi")
    if kind == "prog":
        if attr == "count":
            starts = [rng.choice([1, 2]) for _ in range(3)]
            return Rule(attr, kind, lambda r, c, s=starts: s[r] + c, COUNTS,
                        "har qatorda shakllar soni chapdan o'ngga bittaga ortadi")
        if attr == "size":
            down = rng.random() < 0.5
            return Rule(attr, kind, lambda r, c, d=down: 2 - c if d else c, [0, 1, 2],
                        "har qatorda o'lcham chapdan o'ngga "
                        + ("kichrayib boradi" if down else "kattalashib boradi"))
        if attr == "rot":
            step = rng.choice([1, 2, -1, -2])
            starts = [rng.randrange(8) for _ in range(3)]
            deg = abs(step) * 45
            way = "soat mili bo'yicha" if step > 0 else "soat miliga teskari"
            return Rule(attr, kind, lambda r, c, s=starts, st=step: (s[r] + c * st) % 8,
                        list(range(8)), f"har qatorda strelka {way} {deg}° ga buriladi")
    if kind == "add" and attr == "count":
        pairs = [(a, b) for a in (1, 2, 3) for b in (1, 2, 3) if a + b <= 4]
        rows = [rng.choice(pairs) for _ in range(3)]
        return Rule(attr, kind,
                    lambda r, c, p=rows: p[r][0] if c == 0 else (p[r][1] if c == 1 else sum(p[r])),
                    COUNTS, "har qatorda uchinchi katakdagi shakllar soni birinchi ikkitasining "
                            "yig'indisiga teng")
    raise ValueError((attr, kind))


# har daraja uchun: o'zgaruvchi atributlar va qoida turlari
PLANS = {
    1: [[("count", "prog")], [("shape", "dist")], [("fill", "dist")], [("size", "prog")]],
    2: [[("count", "prog"), ("shape", "dist")], [("fill", "dist"), ("size", "prog")],
        [("shape", "dist"), ("fill", "row")], [("count", "prog"), ("fill", "dist")]],
    3: [[("shape", "dist"), ("fill", "dist")], [("count", "prog"), ("shape", "dist"), ("size", "row")],
        [("rot", "prog")], [("count", "add")]],
    4: [[("shape", "dist"), ("fill", "dist"), ("count", "prog")],
        [("rot", "prog"), ("fill", "dist")], [("count", "add"), ("shape", "dist")],
        [("shape", "dist"), ("fill", "dist"), ("size", "prog")]],
    5: [[("rot", "prog"), ("fill", "dist"), ("size", "dist")],
        [("count", "add"), ("shape", "dist"), ("fill", "dist")],
        [("shape", "dist"), ("fill", "dist"), ("count", "prog"), ("size", "dist")],
        [("rot", "prog"), ("count", "prog"), ("fill", "dist")]],
}


def _make_rules(rng: random.Random, plan: list[tuple[str, str]]) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for attr, kind in plan:
        rules[attr] = _rule(rng, attr, kind)
    uses_rot = "rot" in rules
    if uses_rot:
        rules["shape"] = Rule("shape", "const", lambda r, c: "arrow", ["arrow"], "")
    for attr in ("shape", "count", "size", "fill", "rot"):
        if attr in rules:
            continue
        if attr == "rot":
            rules[attr] = Rule(attr, "const", lambda r, c: 0, [0], "")
        elif attr == "shape":
            v = rng.choice([s for s in SHAPES if s != "cross"])
            rules[attr] = Rule(attr, "const", lambda r, c, v=v: v, [v], "")
        elif attr == "count":
            rules[attr] = Rule(attr, "const", lambda r, c: 1, [1], "")
        else:
            rules[attr] = _rule(rng, attr, "const")
    # ko'p shaklli kataklarda katta o'lcham sig'maydi
    counts = {rules["count"].fn(r, c) for r in range(3) for c in range(3)}
    if max(counts) >= 2 and rules["size"].kind == "const":
        rules["size"] = Rule("size", "const", lambda r, c: 0 if max(counts) >= 3 else 1,
                             [0], "")
    return rules


def _spec(rules: dict[str, Rule], r: int, c: int) -> dict:
    return {a: rules[a].fn(r, c) for a in ("shape", "count", "size", "fill", "rot")}


def _distractors(rng: random.Random, rules: dict[str, Rule], grid: list[list[dict]],
                 answer: dict, n: int) -> list[dict] | None:
    """Raven APM uslubi: to'g'ri javobdan bitta-ikkita belgisi bilan farqlanadi."""
    seen = {key(answer)}
    out: list[dict] = []

    def add(spec: dict) -> None:
        k = key(spec)
        if k in seen or len(out) >= n:
            return
        if spec["count"] >= 3 and spec["size"] == 2:
            return
        seen.add(k)
        out.append(spec)

    varying = [a for a, rl in rules.items() if rl.kind != "const"]
    others = [a for a in ("fill", "size", "count", "shape") if a not in varying
              and not (a == "shape" and "rot" in rules and rules["rot"].kind != "const")]

    def plausible(attr: str) -> list:
        vals = {grid[r][c][attr] for r in range(3) for c in range(3)}
        if attr == "count":
            vals |= {answer["count"] - 1, answer["count"] + 1}
            vals = {v for v in vals if 1 <= v <= 4}
        if attr == "rot":
            vals |= {(answer["rot"] + d) % 8 for d in (2, 4, 6)}
        return sorted(vals, key=lambda v: str(v))

    # 1) bitta varying belgisi o'zgartirilgan
    for attr in varying:
        vals = [v for v in plausible(attr) if v != answer[attr]]
        rng.shuffle(vals)
        for v in vals[:2]:
            add({**answer, attr: v})
    # 2) matritsadagi qo'shni kataklar nusxasi (keng tarqalgan xato)
    for r, c in ((2, 1), (1, 2), (2, 0), (0, 2)):
        add(dict(grid[r][c]))
    # 3) ikki belgisi o'zgargan
    for _ in range(40):
        if len(out) >= n:
            break
        pool = varying + others
        if len(pool) < 2:
            break
        a1, a2 = rng.sample(pool, 2)
        v1 = [v for v in (plausible(a1) if a1 in varying else _domain(a1)) if v != answer[a1]]
        v2 = [v for v in (plausible(a2) if a2 in varying else _domain(a2)) if v != answer[a2]]
        if a1 == "size" or a2 == "size":
            v1 = [v for v in v1 if a1 != "size" or v < 2] or v1
            v2 = [v for v in v2 if a2 != "size" or v < 2] or v2
        if v1 and v2:
            add({**answer, a1: rng.choice(v1), a2: rng.choice(v2)})
    # 4) doimiy belgisi o'zgargan
    for attr in others:
        vals = [v for v in _domain(attr) if v != answer[attr]]
        rng.shuffle(vals)
        for v in vals[:1]:
            add({**answer, attr: v})
    return out if len(out) >= n else None


def _explain(rules: dict[str, Rule], answer: dict) -> str:
    parts = [rl.text for rl in rules.values() if rl.text]
    desc = f"{answer['count']} ta {FILL_UZ[FILLS[answer['fill']]]} {SHAPE_UZ[answer['shape']]}"
    return ("Qoida: " + "; ".join(parts) + f". Javob — {desc}.")[:480]


# ---------------------------------------------------------------- savollar
def _save(draw: Callable[[], Image.Image], media_dir: Path, rel: str) -> str:
    """Rasm faqat fayl hali yo'q bo'lsa chiziladi (ishga tushish tez bo'lsin)."""
    path = media_dir / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        draw().save(path, optimize=True)
    return rel


def _options(rng: random.Random, answer: dict, distractors: list[dict]):
    opts = distractors + [answer]
    rng.shuffle(opts)
    return opts, opts.index(answer)


def make_matrix(rng: random.Random, level: int, media_dir: Path, name: str) -> dict:
    n_opts = 6 if level <= 2 else 8
    for _ in range(200):
        plan = rng.choice(PLANS[level])
        rules = _make_rules(rng, plan)
        grid = [[_spec(rules, r, c) for c in range(3)] for r in range(3)]
        answer = grid[2][2]
        if any(s["count"] >= 3 and s["size"] == 2 for row in grid for s in row):
            continue
        dis = _distractors(rng, rules, grid, answer, n_opts - 1)
        if dis:
            break
    else:  # pragma: no cover
        raise RuntimeError("matritsa yaratilmadi")
    opts, correct = _options(rng, answer, dis)
    cells = [row[:] for row in grid]
    cells[2][2] = None
    return {
        "text": "Matritsadagi qonuniyatni toping. «?» o'rniga qaysi figura mos keladi?",
        "image": _save(lambda: draw_grid(cells), media_dir, f"{name}.png"),
        "option_images": [_save(lambda o=o: draw_figure(o), media_dir, f"{name}_{i}.png")
                          for i, o in enumerate(opts)],
        "options": [""] * len(opts),
        "correct": correct,
        "explanation": _explain(rules, answer),
        "category": "Matritsalar (Raven)",
        "difficulty": level,
    }


SERIES_PLANS = {
    1: [["count"], ["size"], ["rot"]],
    2: [["count", "fill"], ["rot", "fill"], ["size", "shape"]],
    3: [["rot", "count"], ["count", "shape", "fill"], ["rot", "size", "fill"]],
}


def make_series(rng: random.Random, level: int, media_dir: Path, name: str) -> dict:
    """Figuralar ketma-ketligi: 4 ta figura + «?», 5 ta variant."""
    for _ in range(200):
        attrs = rng.choice(SERIES_PLANS[level])
        texts, fns = [], {}
        for a in attrs:
            if a == "count":
                fns[a] = lambda i: (i % 4) + 1
                texts.append("shakllar soni bittadan ortadi (4 dan keyin qaytadan 1)")
            elif a == "size":
                fns[a] = lambda i: [0, 1, 2, 1, 0][i]
                texts.append("o'lcham kattalashib, so'ng kichrayadi")
            elif a == "rot":
                st = rng.choice([1, 2, -1])
                s0 = rng.randrange(8)
                fns[a] = lambda i, s0=s0, st=st: (s0 + i * st) % 8
                texts.append(f"strelka har qadamda {abs(st) * 45}° "
                             + ("soat mili bo'yicha" if st > 0 else "teskari") + " buriladi")
            elif a == "fill":
                vals = rng.sample(range(4), 2)
                fns[a] = lambda i, v=vals: v[i % 2]
                texts.append("bo'yoq navbatma-navbat almashadi")
            elif a == "shape":
                vals = rng.sample(["circle", "square", "triangle", "hexagon"], 3)
                fns[a] = lambda i, v=vals: v[i % 3]
                texts.append("shakllar uchtadan takrorlanib keladi")
        base = {"shape": "arrow" if "rot" in attrs else rng.choice(["circle", "square", "hexagon"]),
                "count": 1, "size": 1, "fill": rng.randrange(4), "rot": 0}
        if "count" in attrs:
            base["size"] = 0
        seq = [{**base, **{a: f(i) for a, f in fns.items()}} for i in range(5)]
        answer = seq[4]
        fake_rules = {a: Rule(a, "prog", lambda r, c: 0, [], "") for a in attrs}
        grid = [seq[:3], seq[1:4], [seq[2], seq[3], answer]]
        dis = _distractors(rng, fake_rules, grid, answer, 4)
        if dis:
            break
    else:  # pragma: no cover
        raise RuntimeError("ketma-ketlik yaratilmadi")
    opts, correct = _options(rng, answer, dis)
    return {
        "text": "Figuralar ketma-ketligini davom ettiring: «?» o'rnida qaysi figura bo'ladi?",
        "image": _save(lambda: draw_grid([seq[:4] + [None]]), media_dir, f"{name}.png"),
        "option_images": [_save(lambda o=o: draw_figure(o), media_dir, f"{name}_{i}.png")
                          for i, o in enumerate(opts)],
        "options": [""] * len(opts),
        "correct": correct,
        "explanation": ("Qoida: " + "; ".join(texts) + ".")[:480],
        "category": "Figuralar ketma-ketligi",
        "difficulty": level,
    }


def make_odd(rng: random.Random, level: int, media_dir: Path, name: str) -> dict:
    """5 ta figuradan bittasi umumiy belgiga ega emas (variantlar — rasmlar)."""
    attrs = ["shape", "fill", "count"]
    for _ in range(500):
        common = rng.choice(attrs)
        noise = rng.sample([a for a in attrs + ["size"] if a != common], level)
        base = {"shape": rng.choice(SHAPES[:6]), "count": rng.choice([1, 2, 3]),
                "size": 0, "fill": rng.randrange(4), "rot": 0}
        figs = []
        for _i in range(5):
            f = dict(base)
            for a in noise:
                f[a] = rng.choice({"shape": SHAPES[:6], "fill": [0, 1, 2, 3],
                                   "count": [1, 2, 3], "size": [0, 1]}[a])
            figs.append(f)
        odd = rng.randrange(5)
        others = [v for v in {"shape": SHAPES[:6], "fill": [0, 1, 2, 3],
                              "count": [1, 2, 3, 4]}[common] if v != base[common]]
        figs[odd] = {**figs[odd], common: rng.choice(others)}
        if len({key(f) for f in figs}) < 5:
            continue
        # boshqa belgida ham «4 ta bir xil + 1 ta boshqa» bo'lsa — noaniq, qaytadan
        ambiguous = False
        for a in ("shape", "fill", "count", "size"):
            if a == common:
                continue
            vals = [f[a] for f in figs]
            if any(vals.count(v) == 4 for v in set(vals)):
                ambiguous = True
        if not ambiguous:
            break
    else:  # pragma: no cover
        raise RuntimeError("ortiqcha figura yaratilmadi")
    what = {"shape": "shakl turi", "fill": "bo'yog'i", "count": "shakllar soni"}[common]
    return {
        "text": "Qaysi figura qolganlariga o'xshamaydi (ortiqcha)?",
        "image": "",
        "option_images": [_save(lambda f=f: draw_figure(f), media_dir, f"{name}_{i}.png")
                          for i, f in enumerate(figs)],
        "options": [""] * 5,
        "correct": odd,
        "explanation": f"Qolgan to'rtta figurada {what} bir xil, bu figurada esa boshqacha.",
        "category": "Ortiqcha figura",
        "difficulty": level,
    }


BANK_SEED = 20260923
MATRIX_PER_LEVEL = 10
SERIES_PER_LEVEL = 4
ODD_PER_LEVEL = 3


def build_bank(media_dir: Path, seed: int = BANK_SEED) -> list[dict]:
    """Butun rasmli bank (deterministik)."""
    rng = random.Random(seed)
    out: list[dict] = []
    for level in range(1, 6):
        for i in range(MATRIX_PER_LEVEL):
            out.append(make_matrix(rng, level, media_dir, f"iq/m{level}_{i:02d}"))
    for level in range(1, 4):
        for i in range(SERIES_PER_LEVEL):
            out.append(make_series(rng, level, media_dir, f"iq/s{level}_{i:02d}"))
    for level in range(1, 4):
        for i in range(ODD_PER_LEVEL):
            out.append(make_odd(rng, level, media_dir, f"iq/o{level}_{i:02d}"))
    return out
