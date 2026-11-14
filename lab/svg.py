"""Tiny SVG charts in the team's dark instrument palette (AGENTS.md style). Text files, not images.

Each chart takes the colour of what it is about: person (zones), fault (alert,
SENSOR BLIND), action (check-in), object (the tray), link (radio links). Extra
series are secondary grey with a dash, and every series has a word in the legend.
"""
from __future__ import annotations

from pathlib import Path

BG, CARD, TEXT, SUB, LINE, EDGE = "#111316", "#1A1D21", "#E6E8EB", "#9AA3AD", "#353B43", "#6B7480"
PERSON, OBJECT, LINK, ACTION, FAULT = "#FF9F43", "#A9B4C2", "#5AA9E6", "#3DD68C", "#F2555A"
DASHES = ["", "5 3", "2 3", "8 3 2 3"]


def _series(k, color):
    return (color, "") if k == 0 else (SUB, DASHES[k % len(DASHES)])
W, H, L, R, T, B = 520, 300, 58, 16, 46, 48


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _frame(title, xlabel, ylabel):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="Hanken Grotesk, sans-serif" font-size="11" fill="{TEXT}">',
            f'<rect width="{W}" height="{H}" fill="{BG}"/>',
            f'<rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="{CARD}" stroke="{EDGE}"/>',
            f'<text x="{L}" y="20" font-family="Newsreader, serif" font-size="15">{_esc(title)}</text>',
            f'<text x="{L}" y="36" fill="{SUB}">SIMULATED (lab/, dev only). Not a measurement.</text>',
            f'<text x="{(W + L - R) / 2:.0f}" y="{H - 10}" text-anchor="middle" fill="{SUB}">{_esc(xlabel)}</text>',
            f'<text transform="translate(14 {(H + T - B) / 2:.0f}) rotate(-90)" text-anchor="middle" '
            f'fill="{SUB}">{_esc(ylabel)}</text>']


def _axes(out, xticks, ylo, yhi, fx, fy, xfmt=str):
    for v in [ylo + (yhi - ylo) * k / 4 for k in range(5)]:
        y = fy(v)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINE}"/>')
        out.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" fill="{SUB}">{v:g}</text>')
    for v in xticks:
        out.append(f'<text x="{fx(v):.1f}" y="{H - B + 16}" text-anchor="middle" fill="{SUB}">{_esc(xfmt(v))}</text>')


def _legend(out, names, color):
    x = L + 8
    for k, name in enumerate(names):
        col, dash = _series(k, color)
        out.append(f'<line x1="{x}" x2="{x + 18}" y1="{T + 12}" y2="{T + 12}" stroke="{col}" stroke-width="2" '
                   f'stroke-dasharray="{dash}"/><text x="{x + 22}" y="{T + 16}">{_esc(name)}</text>')
        x += 30 + 7 * len(str(name))


def lines(path, title, series, xlabel, ylabel, ylim=(0, 1), xfmt=str, color=PERSON):
    """series: [(name, xs, ys)] with ys None where there is no data."""
    xs_all = sorted({x for _, xs, _ in series for x in xs})
    x0, x1 = min(xs_all), max(xs_all)
    ylo, yhi = ylim
    fx = lambda v: L + 12 + (W - L - R - 24) * ((v - x0) / ((x1 - x0) or 1))   # noqa: E731
    fy = lambda v: H - B - (H - T - B - 26) * ((v - ylo) / ((yhi - ylo) or 1))   # noqa: E731
    out = _frame(title, xlabel, ylabel)
    _axes(out, xs_all, ylo, yhi, fx, fy, xfmt)
    for k, (_, xs, ys) in enumerate(series):
        col, dash = _series(k, color)
        pts = [(fx(x), fy(y)) for x, y in zip(xs, ys) if y is not None]
        out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" stroke-dasharray="{dash}" points="'
                   + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '"/>')
        out += [f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.5" fill="{col}"/>' for a, b in pts]
    if len(series) > 1:
        _legend(out, [s[0] for s in series], color)
    Path(path).write_text("\n".join(out + ["</svg>", ""]), encoding="utf-8", newline="\n")


def bars(path, title, labels, values, xlabel, ylabel, ylim=(0, 1), color=PERSON):
    n = len(labels)
    ylo, yhi = ylim
    slot = (W - L - R - 16) / n
    fx = lambda i: L + 8 + slot * (i + 0.5)   # noqa: E731
    fy = lambda v: H - B - (H - T - B - 26) * ((v - ylo) / ((yhi - ylo) or 1))   # noqa: E731
    out = _frame(title, xlabel, ylabel)
    _axes(out, [], ylo, yhi, fx, fy)
    for i, (lab, v) in enumerate(zip(labels, values)):
        if v is None:
            continue
        x, y = fx(i), fy(v)
        out.append(f'<rect x="{x - slot * 0.32:.1f}" y="{y:.1f}" width="{slot * 0.64:.1f}" height="{H - B - y:.1f}" '
                   f'fill="{color}"/><text x="{x:.1f}" y="{y - 4:.1f}" text-anchor="middle">{v:.2f}</text>')
        out.append(f'<text x="{x:.1f}" y="{H - B + 16}" text-anchor="middle" fill="{SUB}">{_esc(lab)}</text>')
    Path(path).write_text("\n".join(out + ["</svg>", ""]), encoding="utf-8", newline="\n")


def scatter(path, title, pts, xlabel, ylabel, xlim, ylim, mark=None, color=ACTION):
    """pts: [(x, y)]; mark: one (x, y, label) to ring and name."""
    (x0, x1), (ylo, yhi) = xlim, ylim
    fx = lambda v: L + 12 + (W - L - R - 24) * ((min(max(v, x0), x1) - x0) / ((x1 - x0) or 1))   # noqa: E731
    fy = lambda v: H - B - (H - T - B - 26) * ((v - ylo) / ((yhi - ylo) or 1))   # noqa: E731
    out = _frame(title, xlabel, ylabel)
    _axes(out, [x0 + (x1 - x0) * k / 4 for k in range(5)], ylo, yhi, fx, fy, lambda v: f"{v:g}")
    out += [f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="2.5" fill="{color}" fill-opacity="0.6"/>' for x, y in pts]
    if mark:
        x, y, lab = mark
        out.append(f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="6" fill="none" stroke="{TEXT}" stroke-width="2"/>'
                   f'<text x="{fx(x) + 9:.1f}" y="{fy(y) + 4:.1f}">{_esc(lab)}</text>')
    Path(path).write_text("\n".join(out + ["</svg>", ""]), encoding="utf-8", newline="\n")
