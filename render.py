#!/usr/bin/env python3
"""
Kindle 4 weather dashboard renderer.

Produces a 600x800 (framebuffer), 16-level greyscale PNG for a Kindle 4 (or any 6" E Ink
Kindle) showing:
  - current conditions, today's high/low
  - a one-line rain summary
  - the next 24 hours: chance of rain as bars, temperature as an overlaid
    line, and a strip of condition icons along the top

Data comes from Open-Meteo (free, no API key).

Usage:
  python3 render.py                      # live data, writes dashboard.png
  python3 render.py --out /var/www/kindle/dash.png
  python3 render.py --lat 45.46 --lon 9.19 --place Milan
  python3 render.py --sample             # offline sample data (for testing)
  python3 render.py --orientation portrait
  python3 render.py --preview upright.png  # also save an unrotated copy to check

Requires: Pillow (pip install pillow)
"""
import argparse
import json
import math
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- settings
S = 2                    # supersample factor for smooth lines
HOURS = 24               # hours shown in the chart
DEFAULT = dict(lat=51.51, lon=-0.13, place="London", tz="Europe/London")

INK = 0                  # black
MID = 110                # mid grey for secondary text
SOFT = 165               # light grey for bars
FAINT = 215              # gridlines
PAPER = 255

HERE = Path(__file__).resolve().parent
FONT_CANDIDATES = {
    "regular": [str(HERE / "fonts/Inter-Regular.otf"),
                "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
                "/Library/Fonts/Inter-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "medium":  [str(HERE / "fonts/Inter-Medium.otf"),
                "/usr/share/fonts/opentype/inter/Inter-Medium.otf",
                "/Library/Fonts/Inter-Medium.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold":    [str(HERE / "fonts/Inter-SemiBold.otf"),
                "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
                "/Library/Fonts/Inter-SemiBold.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "display": [str(HERE / "fonts/InterDisplay-SemiBold.otf"),
                "/usr/share/fonts/opentype/inter/InterDisplay-SemiBold.otf",
                "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
                "/Library/Fonts/Inter-SemiBold.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}
_font_cache = {}


def font(weight, size):
    key = (weight, size)
    if key not in _font_cache:
        for path in FONT_CANDIDATES[weight]:
            if Path(path).exists():
                _font_cache[key] = ImageFont.truetype(path, size * S)
                break
        else:
            _font_cache[key] = ImageFont.load_default(size * S)
    return _font_cache[key]


def s(v):
    return int(round(v * S))


# ---------------------------------------------------------------- weather codes
# WMO weather codes -> (category, label)
def describe(code):
    if code == 0:
        return "clear", "Clear"
    if code == 1:
        return "mostly_clear", "Mostly clear"
    if code == 2:
        return "partly", "Partly cloudy"
    if code == 3:
        return "cloudy", "Overcast"
    if code in (45, 48):
        return "fog", "Fog"
    if 51 <= code <= 57:
        return "drizzle", "Drizzle"
    if code in (61, 66, 80):
        return "rain", "Light rain"
    if code in (63, 81):
        return "rain", "Rain"
    if code in (65, 67, 82):
        return "heavy_rain", "Heavy rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow", "Snow"
    if code >= 95:
        return "thunder", "Thunderstorm"
    return "cloudy", "Cloudy"


# ---------------------------------------------------------------- icons
def _cloud(d, cx, cy, r, fill=PAPER, stroke=INK, width=None):
    """Cloud centred on (cx, cy) with overall half-width ~r (supersampled px)."""
    width = width or max(2, int(r * 0.12))
    parts = [
        ("e", cx - r * 0.45, cy + r * 0.05, r * 0.38),
        ("e", cx + r * 0.05, cy - r * 0.15, r * 0.52),
        ("e", cx + r * 0.52, cy + r * 0.12, r * 0.34),
        ("r", cx - r * 0.82, cy + r * 0.05, cx + r * 0.86, cy + r * 0.46),
    ]

    def draw(grow, colour):
        for p in parts:
            if p[0] == "e":
                _, x, y, rr = p
                d.ellipse([x - rr - grow, y - rr - grow, x + rr + grow, y + rr + grow], fill=colour)
            else:
                _, x0, y0, x1, y1 = p
                d.rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow],
                                    radius=(y1 - y0) / 2 + grow, fill=colour)
    draw(width, stroke)
    draw(0, fill)


def _sun(d, cx, cy, r, rays=True):
    w = max(2, int(r * 0.16))
    core = r * 0.5
    d.ellipse([cx - core, cy - core, cx + core, cy + core], outline=INK, width=w)
    if rays:
        for i in range(8):
            a = i * math.pi / 4
            x0, y0 = cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72
            x1, y1 = cx + math.cos(a) * r * 1.0, cy + math.sin(a) * r * 1.0
            d.line([x0, y0, x1, y1], fill=INK, width=w)


def _moon(d, cx, cy, r):
    rr = r * 0.62
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=INK)
    off = rr * 0.55
    d.ellipse([cx - rr + off, cy - rr - off * 0.45, cx + rr + off, cy + rr - off * 0.45], fill=PAPER)


def draw_icon(d, category, is_day, cx, cy, size):
    """Draw a weather icon centred at (cx, cy) in supersampled coords, fitting `size`."""
    r = size / 2
    sky = (lambda x, y, rr: _sun(d, x, y, rr)) if is_day else (lambda x, y, rr: _moon(d, x, y, rr))
    if category == "clear":
        sky(cx, cy, r * 0.95)
    elif category in ("mostly_clear", "partly"):
        big = category == "mostly_clear"
        sky(cx - r * 0.25, cy - r * 0.25, r * (0.7 if big else 0.62))
        _cloud(d, cx + r * 0.18, cy + r * 0.2, r * (0.55 if big else 0.7))
    elif category == "cloudy":
        _cloud(d, cx - r * 0.15, cy - r * 0.15, r * 0.6, fill=FAINT)
        _cloud(d, cx + r * 0.08, cy + r * 0.12, r * 0.78)
    elif category == "fog":
        w = max(2, int(r * 0.13))
        for i, (a, b) in enumerate([(-0.8, 0.6), (-0.6, 0.85), (-0.85, 0.5), (-0.5, 0.8)]):
            y = cy - r * 0.55 + i * r * 0.37
            d.line([cx + a * r, y, cx + b * r, y], fill=INK, width=w)
    elif category == "thunder":
        _cloud(d, cx, cy - r * 0.25, r * 0.8, fill=SOFT)
        bolt = [(cx + r * 0.05, cy + r * 0.05), (cx - r * 0.25, cy + r * 0.5),
                (cx, cy + r * 0.5), (cx - r * 0.15, cy + r * 0.95),
                (cx + r * 0.3, cy + r * 0.35), (cx + r * 0.05, cy + r * 0.35),
                (cx + r * 0.2, cy + r * 0.05)]
        d.polygon(bolt, fill=INK)
    else:  # precipitation: drizzle / rain / heavy_rain / snow
        fill = SOFT if category == "heavy_rain" else PAPER
        _cloud(d, cx, cy - r * 0.3, r * 0.8, fill=fill)
        w = max(2, int(r * 0.12))
        xs = [-0.45, 0.0, 0.45]
        for i, dx in enumerate(xs):
            x = cx + dx * r
            y0 = cy + r * 0.38 + (i % 2) * r * 0.12
            if category == "snow":
                rr = r * 0.1
                for k in range(2):
                    yy = y0 + k * r * 0.32
                    d.ellipse([x - rr, yy - rr, x + rr, yy + rr], fill=INK)
            elif category == "drizzle":
                rr = r * 0.075
                for k in range(2):
                    yy = y0 + k * r * 0.3
                    d.ellipse([x - rr, yy - rr, x + rr, yy + rr], fill=INK)
            else:
                ln = r * (0.5 if category == "heavy_rain" else 0.36)
                d.line([x + r * 0.12, y0, x - r * 0.08, y0 + ln], fill=INK, width=w)


# ---------------------------------------------------------------- data
def fetch(lat, lon, tz):
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}&timezone={tz.replace('/', '%2F')}"
           "&current=temperature_2m,apparent_temperature,weather_code,is_day"
           "&hourly=temperature_2m,precipitation_probability,weather_code,is_day"
           "&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset"
           "&forecast_days=3")
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def sample():
    """Realistic late-October London day, for offline testing."""
    start = datetime(2026, 10, 26, 12)
    temps = [13.2, 13.8, 14.1, 13.6, 12.9, 12.1, 11.4, 10.9, 10.5, 10.1, 9.8, 9.4,
             9.1, 8.8, 8.5, 8.3, 8.1, 7.9, 7.8, 8.0, 8.6, 9.6, 10.8, 11.9]
    rain = [10, 15, 25, 45, 65, 80, 75, 55, 35, 20, 10, 5,
            5, 0, 0, 0, 5, 5, 5, 10, 5, 0, 0, 0]
    codes = [2, 3, 3, 61, 61, 63, 63, 61, 3, 3, 2, 2,
             1, 0, 0, 0, 0, 1, 2, 2, 2, 1, 1, 0]
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(24)]
    is_day = [1 if 7 <= (12 + i) % 24 <= 16 else 0 for i in range(24)]
    return {
        "current": {"time": "2026-10-26T11:45", "temperature_2m": 13.0,
                    "apparent_temperature": 11.0, "weather_code": 2, "is_day": 1},
        "hourly": {"time": times, "temperature_2m": temps,
                   "precipitation_probability": rain, "weather_code": codes, "is_day": is_day},
        "daily": {"time": ["2026-10-26", "2026-10-27"],
                  "temperature_2m_max": [14.1, 13.0], "temperature_2m_min": [7.8, 7.0],
                  "sunrise": ["2026-10-26T06:55", "2026-10-27T06:57"],
                  "sunset": ["2026-10-26T16:44", "2026-10-27T16:42"]},
    }


def next_hours(data, n=HOURS):
    h = data["hourly"]
    now = datetime.fromisoformat(data["current"]["time"]).replace(minute=0)
    rows = []
    for i, t in enumerate(h["time"]):
        dt = datetime.fromisoformat(t)
        if dt >= now:
            rows.append(dict(t=dt, temp=h["temperature_2m"][i],
                             rain=h["precipitation_probability"][i] or 0,
                             code=h["weather_code"][i], day=h["is_day"][i]))
        if len(rows) == n:
            break
    return rows


def rain_summary(rows):
    """One headline + one detail line about rain in the next 24 hours."""
    def when(t):
        return f"{t:%H:%M}" if t.date() == rows[0]["t"].date() else f"{t:%H:%M} {t:%a}"

    # contiguous runs of hours where rain is likely (>= 50%)
    runs, cur = [], []
    for r in rows:
        if r["rain"] >= 50:
            cur.append(r)
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)

    if runs:
        first = runs[0]
        peak = max(first, key=lambda r: r["rain"])
        end = first[-1]["t"] + timedelta(hours=1)
        if first[0] is rows[0]:
            head = "Rain now" if first[-1] is rows[-1] else f"Rain until around {when(end)}"
        else:
            head = f"Rain likely {first[0]['t']:%H:%M}–{end:%H:%M}"
            if first[0]["t"].date() != rows[0]["t"].date():
                head += f" {first[0]['t']:%a}"
        detail = f"peaks at {peak['rain']}% around {when(peak['t'])}"
        if len(runs) > 1:
            detail += f" · more from {when(runs[1][0]['t'])}"
        return head, detail

    peak = max(rows, key=lambda r: r["rain"])
    if peak["rain"] >= 25:
        return f"Chance of showers around {when(peak['t'])}", f"up to {peak['rain']}%"
    return "Dry for the next 24 hours", None


# ---------------------------------------------------------------- render
def merge_segments(rows):
    """Condition strip: merge consecutive hours with the same broad condition."""
    STRIP = {"mostly_clear": ("clear", "Clear"), "drizzle": ("rain", "Rain"),
             "rain": ("rain", "Rain"), "heavy_rain": ("heavy_rain", "Heavy rain")}
    segs = []
    for i, r in enumerate(rows):
        c, lab = describe(r["code"])
        c, lab = STRIP.get(c, (c, lab))
        if segs and segs[-1]["cat"] == c:
            segs[-1]["end"] = i
        else:
            segs.append(dict(cat=c, label=lab, start=i, end=i))
    # fold lone dry hours into a neighbour so icons never get too small
    wet = {"rain", "heavy_rain", "snow", "thunder"}
    merged = []
    for sg in segs:
        if merged and sg["start"] == sg["end"] and sg["cat"] not in wet:
            merged[-1]["end"] = sg["end"]
        elif merged and merged[-1]["start"] == merged[-1]["end"] and merged[-1]["cat"] not in wet:
            sg["start"] = merged[-1]["start"]
            merged[-1] = sg
        else:
            merged.append(sg)
    return merged


def draw_chart(d, rows, left, right, band_top, band_h, plot_bot, hour_every=3):
    """Condition strip + rain bars + temperature line + x axis."""
    plot_top = band_top + band_h + 14
    n = len(rows)
    step = (right - left) / n

    def xc(i):
        return left + step * (i + 0.5)

    for k, sg in enumerate(merge_segments(rows)):
        x0, x1 = left + step * sg["start"], left + step * (sg["end"] + 1)
        mid_i = (sg["start"] + sg["end"]) // 2
        width = x1 - x0
        isize = min(40, width - 4)
        has_label = width >= 78
        icy = band_top + (22 if has_label else band_h / 2)
        draw_icon(d, sg["cat"], rows[mid_i]["day"], s((x0 + x1) / 2), s(icy), s(isize))
        if has_label:
            d.text((s((x0 + x1) / 2), s(band_top + 50)), sg["label"],
                   font=font("regular", 14), fill=MID, anchor="mm")
        if k > 0:
            d.line([s(x0), s(band_top + 4), s(x0), s(band_top + band_h - 4)], fill=FAINT, width=s(1))

    # gridlines + right-hand % axis
    for pct in (0, 50, 100):
        gy = plot_bot - (plot_bot - plot_top) * pct / 100
        d.line([s(left), s(gy), s(right), s(gy)], fill=FAINT if pct else MID, width=s(1))
        d.text((s(right + 6), s(gy)), f"{pct}%", font=font("regular", 13), fill=MID, anchor="lm")

    # rain bars
    bw = step * 0.66
    for i, r in enumerate(rows):
        if r["rain"] <= 0:
            continue
        top = plot_bot - (plot_bot - plot_top) * r["rain"] / 100
        d.rectangle([s(xc(i) - bw / 2), s(top), s(xc(i) + bw / 2), s(plot_bot)], fill=SOFT)

    # temperature line (own scale, kept in the upper part of the plot)
    temps = [r["temp"] for r in rows]
    tmin, tmax = min(temps), max(temps)
    span = max(tmax - tmin, 4)
    t_top, t_bot = plot_top + 26, plot_top + (plot_bot - plot_top) * 0.62
    pad = (span - (tmax - tmin)) / span * (t_bot - t_top) / 2

    def ty(t):
        return t_bot - (t - tmin) / span * (t_bot - t_top) - pad

    pts = [(s(xc(i)), s(ty(r["temp"]))) for i, r in enumerate(rows)]
    d.line(pts, fill=PAPER, width=s(9), joint="curve")       # halo over bars
    d.line(pts, fill=INK, width=s(3.5), joint="curve")

    # label every few hours plus the max and min points
    imax, imin = temps.index(tmax), temps.index(tmin)
    for i in sorted(set(range(0, n, hour_every)) | {imax, imin}):
        if i not in (imax, imin) and (abs(i - imax) < 2 or abs(i - imin) < 2):
            continue
        x, yv = xc(i), ty(temps[i])
        rr = 4.5 if i in (imax, imin) else 3.5
        d.ellipse([s(x - rr), s(yv - rr), s(x + rr), s(yv + rr)], fill=INK)
        weight = "bold" if i in (imax, imin) else "medium"
        d.text((s(x), s(yv - 9)), f"{round(temps[i])}°", font=font(weight, 16),
               fill=INK, anchor="mb", stroke_width=s(3), stroke_fill=PAPER)

    # x axis: hour labels, day name at midnight
    for i, r in enumerate(rows):
        if r["t"].hour == 0:
            d.line([s(left + step * i), s(plot_top), s(left + step * i), s(plot_bot)],
                   fill=MID, width=s(1))
            d.text((s(xc(i)), s(plot_bot + 8)), f"{r['t']:%a}", font=font("bold", 15),
                   fill=INK, anchor="ma")
            continue
        if i % hour_every == 0 and all(rows[j]["t"].hour != 0 for j in range(max(0, i - 1), min(n, i + 2))):
            d.text((s(xc(i)), s(plot_bot + 8)), f"{r['t']:%H}", font=font("medium", 15),
                   fill=INK, anchor="ma")


def draw_legend(d, x, y):
    d.rectangle([s(x), s(y - 6), s(x + 14), s(y + 6)], fill=SOFT)
    d.text((s(x + 22), s(y)), "Chance of rain", font=font("regular", 15), fill=MID, anchor="lm")
    lx = x + 160
    d.line([s(lx), s(y), s(lx + 22), s(y)], fill=INK, width=s(3.5))
    d.text((s(lx + 30), s(y)), "Temperature °C", font=font("regular", 15), fill=MID, anchor="lm")


def context(data):
    cur, daily = data["current"], data["daily"]
    now = datetime.fromisoformat(cur["time"])
    cat, label = describe(cur["weather_code"])
    return dict(
        rows=next_hours(data), cur=cur, now=now, cat=cat, label=label,
        is_day=cur.get("is_day", 1),
        hi=round(daily["temperature_2m_max"][0]), lo=round(daily["temperature_2m_min"][0]),
        feels=round(cur["apparent_temperature"]), temp=round(cur["temperature_2m"]),
        sunrise=datetime.fromisoformat(daily["sunrise"][0]),
        sunset=datetime.fromisoformat(daily["sunset"][0]),
    )


def layout_portrait(data, place):
    W, H = 600, 800
    img = Image.new("L", (s(W), s(H)), PAPER)
    d = ImageDraw.Draw(img)
    M = 32
    c = context(data)

    d.text((s(M), s(30)), f"{c['now']:%A} {c['now'].day} {c['now']:%B}", font=font("bold", 26), fill=INK)
    d.text((s(M), s(64)), place, font=font("regular", 19), fill=MID)
    d.text((s(M - 4), s(88)), f"{c['temp']}°", font=font("display", 112), fill=INK)
    draw_icon(d, c["cat"], c["is_day"], s(W - M - 66), s(128), s(118))
    d.text((s(W - M), s(196)), c["label"], font=font("medium", 22), fill=INK, anchor="ra")
    d.text((s(W - M), s(226)), f"H {c['hi']}°   L {c['lo']}°   Feels {c['feels']}°",
           font=font("regular", 18), fill=MID, anchor="ra")

    y = 272
    d.line([s(M), s(y), s(W - M), s(y)], fill=INK, width=s(1.5))
    head, sub = rain_summary(c["rows"])
    d.text((s(M), s(y + 18)), head, font=font("bold", 23), fill=INK)
    if sub:
        d.text((s(M), s(y + 50)), sub, font=font("regular", 18), fill=MID)

    draw_chart(d, c["rows"], M, W - M - 34, band_top=368, band_h=62, plot_bot=676)
    draw_legend(d, M, 716)

    fy = H - 30
    d.line([s(M), s(fy - 22), s(W - M), s(fy - 22)], fill=FAINT, width=s(1))
    d.text((s(M), s(fy)), f"Sunrise {c['sunrise']:%H:%M}  ·  Sunset {c['sunset']:%H:%M}",
           font=font("regular", 15), fill=MID, anchor="lm")
    d.text((s(W - M), s(fy)), f"Updated {c['now']:%H:%M}", font=font("regular", 15),
           fill=MID, anchor="rm")
    return img, (W, H)


def layout_landscape(data, place):
    W, H = 800, 600
    img = Image.new("L", (s(W), s(H)), PAPER)
    d = ImageDraw.Draw(img)
    M = 32
    c = context(data)

    # left: date, place, big temperature, icon
    d.text((s(M), s(26)), f"{c['now']:%A} {c['now'].day} {c['now']:%B}", font=font("bold", 24), fill=INK)
    d.text((s(M), s(58)), place, font=font("regular", 17), fill=MID)
    d.text((s(M - 4), s(78)), f"{c['temp']}°", font=font("display", 100), fill=INK)
    draw_icon(d, c["cat"], c["is_day"], s(282), s(132), s(92))

    # right: condition + rain summary
    R = W - M
    d.text((s(R), s(28)), c["label"], font=font("medium", 22), fill=INK, anchor="ra")
    d.text((s(R), s(58)), f"H {c['hi']}°   L {c['lo']}°   Feels {c['feels']}°",
           font=font("regular", 17), fill=MID, anchor="ra")
    head, sub = rain_summary(c["rows"])
    d.text((s(R), s(118)), head, font=font("bold", 22), fill=INK, anchor="ra")
    if sub:
        d.text((s(R), s(150)), sub, font=font("regular", 17), fill=MID, anchor="ra")

    d.line([s(M), s(196), s(R), s(196)], fill=INK, width=s(1.5))

    # full-width chart
    draw_chart(d, c["rows"], M, R - 34, band_top=208, band_h=62, plot_bot=520)

    # footer: legend left, sun times + update right
    fy = H - 26
    draw_legend(d, M, fy)
    d.text((s(R), s(fy)), f"Sunrise {c['sunrise']:%H:%M}  ·  Sunset {c['sunset']:%H:%M}"
           f"   ·   Updated {c['now']:%H:%M}", font=font("regular", 15), fill=MID, anchor="rm")
    return img, (W, H)


def render(data, place, out, orientation="landscape", preview=None):
    """
    orientation:
      portrait   - Kindle upright, buttons at the bottom
      landscape  - Kindle turned 90° anticlockwise, buttons on the right
    The Kindle's framebuffer is always 600x800 portrait, so landscape output is
    rotated 90° clockwise before saving; `preview` saves the upright view.
    """
    layout = layout_landscape if orientation == "landscape" else layout_portrait
    img, size = layout(data, place)
    img = img.resize(size, Image.LANCZOS)
    img = img.point(lambda v: int(round(v / 17)) * 17)   # Kindle's 16 grey levels
    if preview:
        img.save(preview, optimize=True)
    if orientation == "landscape":
        img = img.transpose(Image.Transpose.ROTATE_270)   # 90° clockwise
    img.save(out, optimize=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=DEFAULT["lat"])
    ap.add_argument("--lon", type=float, default=DEFAULT["lon"])
    ap.add_argument("--place", default=DEFAULT["place"])
    ap.add_argument("--tz", default=DEFAULT["tz"])
    ap.add_argument("--out", default="dashboard.png")
    ap.add_argument("--sample", action="store_true", help="use built-in sample data")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape",
                    help="landscape = Kindle turned 90° anticlockwise, buttons on the right")
    ap.add_argument("--preview", help="also save an upright (unrotated) copy here")
    a = ap.parse_args()
    data = sample() if a.sample else fetch(a.lat, a.lon, a.tz)
    print(render(data, a.place, a.out, a.orientation, a.preview))


if __name__ == "__main__":
    main()
