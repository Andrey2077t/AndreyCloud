#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AndreyCloud — sua nuvem pessoal que roda LOCALMENTE no seu PC.
100% gratuita e open source.

Instalação:  pip install PyQt6
Execução:    python andreycloud.py

Como funciona
  • Você escolhe quais discos/partições usar (C:, D:, ...). O app cria a pasta
    AndreyCloud dentro de cada um e soma o espaço livre de todos. Dá para
    mudar isso quando quiser em Configurações. Dá para mexer nas pastas
    pelo explorador de arquivos também: o app atualiza
    sozinho quando você volta para a janela (ou aperte F5).
  • Upload (botão ou arrastar e soltar), pastas, renomear, mover, favoritos,
    lixeira com restauração, busca e miniaturas de imagens.
  • Duplo clique abre pastas e arquivos.
  • "Compart." cria um link na sua rede local (Wi-Fi/LAN), servido pelo
    próprio app enquanto ele estiver aberto.
  • Configurações ficam em ~/.andreycloud/config.json.

Atalhos: Ctrl+F busca · F2 renomear · Delete lixeira · F5 atualizar · Alt+← voltar

Dica: coloque um arquivo  avatar.png  (ou avatar.jpg) na mesma pasta do script
(ou use o menu do perfil) para usar a sua foto no canto superior direito.

Tudo é desenhado via QPainter (ícones, pastas, PDF, ZIP, fundo), então não
depende de nenhum arquivo de imagem externo.
"""
import sys
import os
import math
import json
import uuid
import shutil
import socket
import secrets
import zipfile
import tempfile
import mimetypes
import threading
import collections
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QPixmap, QFontMetrics, QPolygonF, QGuiApplication,
    QDesktopServices, QImageReader, QShortcut, QKeySequence, QCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QAbstractButton, QButtonGroup,
    QScrollArea, QMenu, QMessageBox, QInputDialog, QFileDialog, QSizeGrip,
    QSizePolicy, QDialog, QSpinBox, QProgressDialog, QCheckBox,
)

# ───────────────────────────── constantes ─────────────────────────────
FONT_FAMILY = "Segoe UI"
ACCENT = "#2f7bff"
MUTED = "#8b96ab"
ICON_COLOR = "#c5cee0"

CONFIG_DIR = Path.home() / ".andreycloud"
CONFIG_FILE = CONFIG_DIR / "config.json"

AL_C = Qt.AlignmentFlag.AlignCenter.value
AL_VL = (Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft).value
AL_VR = (Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight).value

MESES = ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.",
         "jul.", "ago.", "set.", "out.", "nov.", "dez."]


def mkfont(px, bold=False, semi=False):
    f = QFont(FONT_FAMILY)
    f.setFamilies([FONT_FAMILY, "Inter", "Roboto", "Helvetica Neue", "Arial"])
    f.setPixelSize(px)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    elif semi:
        f.setWeight(QFont.Weight.DemiBold)
    return f


def fmt_date(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fmt_size(n):
    if n <= 0:
        return "0 KB"
    if n >= 1 << 40:
        return f"{n / (1 << 40):.2f}".replace(".", ",") + " TB"
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f}".replace(".", ",") + " GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}".replace(".", ",") + " MB"
    return f"{max(1, n // 1024)} KB"


def qpoly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


# ───────────────────────────── ícones (QPainter) ─────────────────────────────
def _poly(p, pts, close=False):
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    p.drawPath(path)


def _cloud_path():
    path = QPainterPath()
    path.moveTo(7, 18.5)
    path.cubicTo(4.2, 18.5, 2.5, 16.6, 2.5, 14.3)
    path.cubicTo(2.5, 12.2, 4.0, 10.7, 6.0, 10.4)
    path.cubicTo(6.6, 7.4, 9.0, 5.5, 12.0, 5.5)
    path.cubicTo(15.0, 5.5, 17.3, 7.5, 17.8, 10.2)
    path.cubicTo(20.2, 10.4, 21.7, 12.2, 21.7, 14.3)
    path.cubicTo(21.7, 16.6, 20.0, 18.5, 17.5, 18.5)
    path.closeSubpath()
    return path


def _folder_path():
    path = QPainterPath()
    path.moveTo(3, 7)
    path.quadTo(3, 5, 5, 5)
    path.lineTo(9.5, 5)
    path.lineTo(12, 8)
    path.lineTo(19, 8)
    path.quadTo(21, 8, 21, 10)
    path.lineTo(21, 18)
    path.quadTo(21, 20, 19, 20)
    path.lineTo(5, 20)
    path.quadTo(3, 20, 3, 18)
    path.closeSubpath()
    return path


def _star_pts():
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 9.2 if i % 2 == 0 else 4.1
        pts.append((12 + r * math.cos(a), 12.8 + r * math.sin(a)))
    return pts


class Icons:
    """Ícones desenhados em um grid de 24x24."""

    @staticmethod
    def paint(p, name, rect, color, width=1.8):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(rect.topLeft())
        s = rect.width() / 24.0
        p.scale(s, s)
        c = QColor(color)
        pen = QPen(c, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        getattr(Icons, "_" + name)(p, c)
        p.restore()

    @staticmethod
    def _home(p, c):
        _poly(p, [(3, 11), (12, 3), (21, 11)])
        _poly(p, [(5, 9.5), (5, 20), (19, 20), (19, 9.5)])
        _poly(p, [(10, 20), (10, 14), (14, 14), (14, 20)])

    @staticmethod
    def _folder(p, c):
        p.drawPath(_folder_path())

    @staticmethod
    def _folder_fill(p, c):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        p.drawPath(_folder_path())

    @staticmethod
    def _image(p, c):
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 3.5, 3.5)
        p.drawEllipse(QPointF(8.5, 8.5), 1.7, 1.7)
        _poly(p, [(3.5, 17), (8.5, 12.2), (13, 16.5), (16, 13.6), (20.5, 18.2)])

    @staticmethod
    def _users(p, c):
        p.drawEllipse(QPointF(9, 8), 3.6, 3.6)
        path = QPainterPath()
        path.moveTo(2.8, 20)
        path.cubicTo(2.8, 16.4, 5.4, 14.4, 9, 14.4)
        path.cubicTo(12.6, 14.4, 15.2, 16.4, 15.2, 20)
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(15.2, 4.6)
        path2.cubicTo(17.6, 4.4, 19.4, 5.9, 19.4, 8.2)
        path2.cubicTo(19.4, 10.0, 18.4, 11.3, 16.9, 11.8)
        p.drawPath(path2)
        path3 = QPainterPath()
        path3.moveTo(17.2, 14.6)
        path3.cubicTo(19.6, 15.0, 21.2, 16.8, 21.2, 19.6)
        p.drawPath(path3)

    @staticmethod
    def _star(p, c):
        _poly(p, _star_pts(), True)

    @staticmethod
    def _star_fill(p, c):
        p.setBrush(QBrush(c))
        _poly(p, _star_pts(), True)

    @staticmethod
    def _trash(p, c):
        _poly(p, [(4, 7), (20, 7)])
        _poly(p, [(9, 7), (9, 4), (15, 4), (15, 7)])
        _poly(p, [(6, 7), (7, 20), (17, 20), (18, 7)])
        _poly(p, [(10, 11), (10, 16)])
        _poly(p, [(14, 11), (14, 16)])

    @staticmethod
    def _search(p, c):
        p.drawEllipse(QPointF(11, 11), 6.6, 6.6)
        p.drawLine(QPointF(16, 16), QPointF(20.5, 20.5))

    @staticmethod
    def _bell(p, c):
        path = QPainterPath()
        path.moveTo(4.5, 18)
        path.lineTo(6, 16.5)
        path.lineTo(6, 11)
        path.cubicTo(6, 7.5, 8.5, 5.2, 12, 5.2)
        path.cubicTo(15.5, 5.2, 18, 7.5, 18, 11)
        path.lineTo(18, 16.5)
        path.lineTo(19.5, 18)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 3.4), QPointF(12, 5.2))
        c2 = QPainterPath()
        c2.moveTo(10, 20.6)
        c2.cubicTo(10.4, 22, 13.6, 22, 14, 20.6)
        p.drawPath(c2)

    @staticmethod
    def _gear(p, c):
        pts = []
        for k in range(8):
            a = k * math.pi / 4
            for da, r in ((-0.30, 7.4), (-0.17, 9.6), (0.17, 9.6), (0.30, 7.4)):
                pts.append((12 + r * math.cos(a + da), 12 + r * math.sin(a + da)))
        _poly(p, pts, True)
        p.drawEllipse(QPointF(12, 12), 3.2, 3.2)

    @staticmethod
    def _chevron_down(p, c):
        _poly(p, [(6, 9), (12, 15), (18, 9)])

    @staticmethod
    def _chevron_right(p, c):
        _poly(p, [(9, 6), (15, 12), (9, 18)])

    @staticmethod
    def _chevron_left2(p, c):
        _poly(p, [(12.5, 6), (6.5, 12), (12.5, 18)])
        _poly(p, [(18.5, 6), (12.5, 12), (18.5, 18)])

    @staticmethod
    def _chevron_right2(p, c):
        _poly(p, [(11.5, 6), (17.5, 12), (11.5, 18)])
        _poly(p, [(5.5, 6), (11.5, 12), (5.5, 18)])

    @staticmethod
    def _cloud(p, c):
        p.drawPath(_cloud_path())

    @staticmethod
    def _upload(p, c):
        p.drawPath(_cloud_path())
        p.drawLine(QPointF(12, 16.2), QPointF(12, 10.2))
        _poly(p, [(9.3, 12.7), (12, 10), (14.7, 12.7)])

    @staticmethod
    def _folder_plus(p, c):
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 4, 4)
        p.drawLine(QPointF(12, 8), QPointF(12, 16))
        p.drawLine(QPointF(8, 12), QPointF(16, 12))

    @staticmethod
    def _grid(p, c):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.8, 1.8)

    @staticmethod
    def _download(p, c):
        p.drawLine(QPointF(12, 4), QPointF(12, 15))
        _poly(p, [(7.5, 10.5), (12, 15), (16.5, 10.5)])
        _poly(p, [(5, 19.5), (19, 19.5)])

    @staticmethod
    def _share(p, c):
        for x, y in ((6.5, 12), (17.5, 6), (17.5, 18)):
            p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        p.drawLine(QPointF(8.8, 10.8), QPointF(15.2, 7.2))
        p.drawLine(QPointF(8.8, 13.2), QPointF(15.2, 16.8))

    @staticmethod
    def _pencil(p, c):
        _poly(p, [(4, 20), (5, 15.5), (15.5, 5), (19, 8.5), (8.5, 19)], True)
        p.drawLine(QPointF(13.5, 7), QPointF(17, 10.5))

    @staticmethod
    def _crown(p, c):
        p.setBrush(QBrush(c))
        _poly(p, [(4, 8), (8, 12), (12, 5.5), (16, 12), (20, 8),
                  (18.2, 18.5), (5.8, 18.5)], True)

    @staticmethod
    def _database(p, c):
        p.drawEllipse(QRectF(5, 3, 14, 6))
        p.drawLine(QPointF(5, 6), QPointF(5, 18))
        p.drawLine(QPointF(19, 6), QPointF(19, 18))
        p.drawArc(QRectF(5, 9, 14, 6), 180 * 16, 180 * 16)
        p.drawArc(QRectF(5, 15, 14, 6), 180 * 16, 180 * 16)

    @staticmethod
    def _list(p, c):
        for y in (7, 12, 17):
            p.drawLine(QPointF(8.5, y), QPointF(20, y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        for y in (7, 12, 17):
            p.drawEllipse(QPointF(4.4, y), 1.2, 1.2)

    @staticmethod
    def _check(p, c):
        _poly(p, [(5, 12.5), (10, 17), (19, 7.5)])

    @staticmethod
    def _dots(p, c):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        for x in (5, 12, 19):
            p.drawEllipse(QPointF(x, 12), 1.9, 1.9)


# ───────────────────────────── miniaturas procedurais ─────────────────────────────
_PALETTES = [
    dict(sky=("#2f6fd6", "#8fb4ea", "#e9c9bd"), mount="#4a6490", snow="#f4f7fc",
         lake=("#3a86bf", "#1c4f7c"), tree="#16382c"),
    dict(sky=("#27396b", "#c0678a", "#f6a56b"), mount="#3b2f5a", snow="#f2d9d0",
         lake=("#7a5a88", "#2a2750"), tree="#12202a"),
    dict(sky=("#1f4f86", "#5fa8c9", "#d9ecf0"), mount="#2f5a73", snow="#ffffff",
         lake=("#2a9db0", "#145766"), tree="#0f3a2a"),
]
_landscape_cache = {}


def make_landscape(w, h, variant=0, radius=12):
    key = (w, h, variant, radius)
    if key in _landscape_cache:
        return _landscape_cache[key]
    dpr = 2
    pm = QPixmap(w * dpr, h * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(clip)
    pal = _PALETTES[variant % len(_PALETTES)]
    hor = h * 0.64

    g = QLinearGradient(0, 0, 0, hor)
    g.setColorAt(0.0, QColor(pal["sky"][0]))
    g.setColorAt(0.55, QColor(pal["sky"][1]))
    g.setColorAt(1.0, QColor(pal["sky"][2]))
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))

    def peak(cx, top, half, base, col, snow):
        span = base - top
        path = QPainterPath()
        path.moveTo(cx - half, base)
        path.lineTo(cx - half * 0.45, top + span * 0.45)
        path.lineTo(cx - half * 0.12, top + span * 0.30)
        path.lineTo(cx, top)
        path.lineTo(cx + half * 0.18, top + span * 0.28)
        path.lineTo(cx + half * 0.5, top + span * 0.5)
        path.lineTo(cx + half, base)
        path.closeSubpath()
        gg = QLinearGradient(0, top, 0, base)
        gg.setColorAt(0, QColor(col).lighter(125))
        gg.setColorAt(1, QColor(col))
        p.fillPath(path, QBrush(gg))
        if snow:
            sp = QPainterPath()
            sp.moveTo(cx, top)
            sp.lineTo(cx + half * 0.18, top + span * 0.28)
            sp.lineTo(cx + half * 0.08, top + span * 0.24)
            sp.lineTo(cx + half * 0.02, top + span * 0.37)
            sp.lineTo(cx - half * 0.08, top + span * 0.27)
            sp.lineTo(cx - half * 0.18, top + span * 0.41)
            sp.lineTo(cx - half * 0.12, top + span * 0.30)
            sp.closeSubpath()
            p.fillPath(sp, QColor(pal["snow"]))

    back = QColor(pal["mount"]).lighter(135).name()
    peak(w * 0.16, h * 0.34, w * 0.34, hor, back, True)
    peak(w * 0.84, h * 0.30, w * 0.36, hor, back, True)
    peak(w * 0.50, h * 0.08, w * 0.52, hor, pal["mount"], True)

    lg = QLinearGradient(0, hor, 0, h)
    lg.setColorAt(0, QColor(pal["lake"][0]))
    lg.setColorAt(1, QColor(pal["lake"][1]))
    p.fillRect(QRectF(0, hor, w, h - hor), QBrush(lg))
    p.setPen(QPen(QColor(255, 255, 255, 40), 1))
    for i in range(1, 5):
        yy = hor + i * (h - hor) / 5.5
        p.drawLine(QPointF(w * 0.2, yy), QPointF(w * 0.8, yy))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(pal["tree"]))
    step = max(6, int(w / 22))
    for i in range(-step, int(w) + step, step):
        th = h * (0.13 + 0.05 * ((i // step) % 3))
        t = QPainterPath()
        t.moveTo(i, hor + 3)
        t.lineTo(i + step / 2, hor + 3 - th)
        t.lineTo(i + step, hor + 3)
        t.closeSubpath()
        p.drawPath(t)
    p.setBrush(QColor(pal["tree"]).darker(130))
    p.drawRect(QRectF(0, h - h * 0.06, w, h * 0.06))
    p.end()
    _landscape_cache[key] = pm
    return pm


# ───────────────────────────── desenhos grandes dos cards ─────────────────────────────
def draw_folder(p, r):
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    back = QPainterPath()
    back.moveTo(x, y + 12)
    back.quadTo(x, y, x + 12, y)
    back.lineTo(x + w * 0.36, y)
    back.lineTo(x + w * 0.43, y + h * 0.13)
    back.lineTo(x + w - 12, y + h * 0.13)
    back.quadTo(x + w, y + h * 0.13, x + w, y + h * 0.13 + 12)
    back.lineTo(x + w, y + h - 12)
    back.quadTo(x + w, y + h, x + w - 12, y + h)
    back.lineTo(x + 12, y + h)
    back.quadTo(x, y + h, x, y + h - 12)
    back.closeSubpath()
    bg = QLinearGradient(0, y, 0, y + h)
    bg.setColorAt(0, QColor("#3b7cf0"))
    bg.setColorAt(1, QColor("#2354c8"))
    p.fillPath(back, QBrush(bg))

    front = QPainterPath()
    front.addRoundedRect(QRectF(x, y + h * 0.27, w, h * 0.73), 13, 13)
    fg = QLinearGradient(0, y + h * 0.27, 0, y + h)
    fg.setColorAt(0, QColor("#66b4ff"))
    fg.setColorAt(1, QColor("#2f72f2"))
    p.fillPath(front, QBrush(fg))
    p.setPen(QPen(QColor(255, 255, 255, 80), 1.5))
    p.drawLine(QPointF(x + 12, y + h * 0.27 + 1), QPointF(x + w - 12, y + h * 0.27 + 1))


def draw_folder_photos(p, r):
    draw_folder(p, r)
    cx = r.center().x()
    specs = [(-34, 78, 46, 56, -9, 0), (36, 72, 46, 56, 10, 2), (0, 86, 54, 64, 0, 1)]
    for dx, cy, pw, ph, rot, var in specs:
        p.save()
        p.translate(cx + dx, cy)
        p.rotate(rot)
        rect = QRectF(-pw / 2, -ph / 2, pw, ph)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(rect.translated(0, 3), 6, 6)
        p.drawPixmap(rect.topLeft(), make_landscape(pw, ph, var, 6))
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        p.restore()


def draw_doc(p, r, c1, c2, fold_color):
    l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
    f = r.width() * 0.34
    k = 10
    path = QPainterPath()
    path.moveTo(l + k, t)
    path.lineTo(rr - f, t)
    path.lineTo(rr, t + f)
    path.lineTo(rr, b - k)
    path.quadTo(rr, b, rr - k, b)
    path.lineTo(l + k, b)
    path.quadTo(l, b, l, b - k)
    path.lineTo(l, t + k)
    path.quadTo(l, t, l + k, t)
    g = QLinearGradient(0, t, 0, b)
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    p.fillPath(path, QBrush(g))
    flap = QPainterPath()
    flap.moveTo(rr - f, t)
    flap.lineTo(rr - f, t + f - 6)
    flap.quadTo(rr - f, t + f, rr - f + 6, t + f)
    flap.lineTo(rr, t + f)
    flap.closeSubpath()
    p.fillPath(flap, QColor(fold_color))


def draw_pdf(p, r):
    draw_doc(p, r, "#ff6f6f", "#e03a3f", QColor(255, 255, 255, 90))
    p.setPen(QColor("white"))
    p.setFont(mkfont(21, bold=True))
    p.drawText(QRectF(r.left(), r.top() + r.height() * 0.42, r.width(), r.height() * 0.3), AL_C, "PDF")


def draw_zip(p, r):
    draw_doc(p, r, "#3b4357", "#1d2333", QColor(255, 255, 255, 40))
    cx = r.center().x() - 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#cfd6e4"))
    y = r.top() + 6
    i = 0
    while y < r.top() + r.height() * 0.52:
        p.drawRect(QRectF(cx - 5 + (5 if i % 2 else 0), y, 5, 4))
        y += 5.5
        i += 1
    p.setPen(QPen(QColor("#d5dbe8"), 2))
    p.setBrush(QColor("#161c2b"))
    p.drawRoundedRect(QRectF(cx - 6, y + 1, 14, 22), 4, 4)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#d5dbe8"))
    p.drawRoundedRect(QRectF(cx - 2, y + 6, 6, 8), 2, 2)


def draw_generic_doc(p, r):
    draw_doc(p, r, "#6a86b8", "#3c5282", QColor(255, 255, 255, 70))
    p.setPen(QPen(QColor(255, 255, 255, 170), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(4):
        yy = r.top() + r.height() * (0.45 + i * 0.12)
        p.drawLine(QPointF(r.left() + 16, yy), QPointF(r.right() - (16 if i < 3 else 36), yy))


class BigIcon(QWidget):
    def __init__(self, kind, pixmap=None, height=130):
        super().__init__()
        self.kind = kind
        self.pm = pixmap
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        cx = self.width() / 2
        k = self.kind
        if k == "folder":
            draw_folder(p, QRectF(cx - 65.5, 10, 131, 105))
        elif k == "folder_photos":
            draw_folder_photos(p, QRectF(cx - 66, 10, 132, 105))
        elif k == "folder_shared":
            draw_folder(p, QRectF(cx - 65.5, 10, 131, 105))
            bx, by = cx + 52, 82
            p.setPen(QPen(QColor("#2a3550"), 1.5))
            p.setBrush(QColor("#161e30"))
            p.drawEllipse(QRectF(bx, by, 46, 46))
            Icons.paint(p, "users", QRectF(bx + 11, by + 11, 24, 24), "#dfe6f5", 1.7)
        elif k == "pdf":
            draw_pdf(p, QRectF(cx - 39, 2, 78, 92))
        elif k == "zip":
            draw_zip(p, QRectF(cx - 44, 8, 88, 116))
        elif k == "doc":
            draw_generic_doc(p, QRectF(cx - 44, 8, 88, 116))
        elif k == "image":
            rect = QRectF(cx - 101, 0, 202, 138)
            clip = QPainterPath()
            clip.addRoundedRect(rect, 12, 12)
            if self.pm is not None and not self.pm.isNull():
                p.save()
                p.setClipPath(clip)
                sw, sh = self.pm.width(), self.pm.height()
                tr = rect.width() / rect.height()
                if sw / sh > tr:
                    nw = sh * tr
                    src = QRectF((sw - nw) / 2, 0, nw, sh)
                else:
                    nh = sw / tr
                    src = QRectF(0, (sh - nh) / 2, sw, nh)
                p.drawPixmap(rect, self.pm, src)
                p.restore()
            else:
                p.drawPixmap(rect.topLeft(), make_landscape(202, 138, 0, 12))
            bad = QRectF(rect.left() + 10, rect.bottom() - 39, 32, 32)
            bg = QLinearGradient(0, bad.top(), 0, bad.bottom())
            bg.setColorAt(0, QColor("#3d8bff"))
            bg.setColorAt(1, QColor("#1f62d8"))
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.setBrush(QBrush(bg))
            p.drawRoundedRect(bad, 9, 9)
            Icons.paint(p, "image", QRectF(bad.left() + 7, bad.top() + 7, 18, 18), "#ffffff", 2.0)


# ───────────────────────────── widgets básicos ─────────────────────────────
class IconButton(QAbstractButton):
    def __init__(self, name, size=22, box=(40, 40), color=ICON_COLOR, badge=False,
                 bordered=False, parent=None):
        super().__init__(parent)
        self.name = name
        self.size_ = size
        self.color = color
        self.badge = badge
        self.bordered = bordered
        self.setFixedSize(*box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_name(self, name):
        self.name = name
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.bordered:
            p.setPen(QPen(QColor("#222d45"), 1))
            p.setBrush(QColor(255, 255, 255, 14 if self.underMouse() else 6))
            p.drawRoundedRect(r, 12, 12)
        elif self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(r, 12, 12)
        s = self.size_
        Icons.paint(p, self.name, QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s), self.color)
        if self.badge:
            bx, by = self.width() / 2 + s * 0.28, self.height() / 2 - s * 0.5
            p.setPen(QPen(QColor("#0b111e"), 2))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QPointF(bx + 2, by + 3), 4.5, 4.5)


class CheckBox(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, 20, 20)
        if self.isChecked():
            g = QLinearGradient(0, 0, 0, 22)
            g.setColorAt(0, QColor("#3d8bff"))
            g.setColorAt(1, QColor("#1f66e0"))
            p.setPen(QPen(QColor("#74adff"), 1))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r, 5, 5)
            Icons.paint(p, "check", QRectF(3, 3, 16, 16), "#ffffff", 2.6)
        else:
            p.setPen(QPen(QColor("#8b96ab" if self.underMouse() else "#59647d"), 1.5))
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawRoundedRect(r, 5, 5)


class TrafficLight(QAbstractButton):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.color.darker(115) if self.underMouse() else self.color
        p.setPen(QPen(c.darker(130), 1))
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 16, 16))


class PillButton(QAbstractButton):
    def __init__(self, text, left_icon, width, icon_x, text_x, right_icon=None,
                 chev_from_right=22, primary=False):
        super().__init__()
        self.label = text
        self.left_icon = left_icon
        self.right_icon = right_icon
        self.icon_x = icon_x
        self.text_x = text_x
        self.chev = chev_from_right
        self.primary = primary
        self.setFixedSize(width, 53)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse()
        if self.primary:
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor("#3f8dff" if not hover else "#58a0ff"))
            g.setColorAt(1, QColor("#1f68ee" if not hover else "#2f7bff"))
            p.setPen(QPen(QColor("#6fb0ff"), 1))
            p.setBrush(QBrush(g))
            col = "#ffffff"
        else:
            p.setPen(QPen(QColor("#222d45"), 1))
            p.setBrush(QColor("#141c30" if hover else "#0e1525"))
            col = "#e4eaf7"
        p.drawRoundedRect(r, 14, 14)
        Icons.paint(p, self.left_icon, QRectF(self.icon_x, (self.height() - 26) / 2, 26, 26), col, 1.7)
        p.setPen(QColor(col))
        p.setFont(mkfont(15, semi=True))
        p.drawText(QRectF(self.text_x, 0, self.width() - self.text_x, self.height()), AL_VL, self.label)
        if self.right_icon:
            Icons.paint(p, self.right_icon,
                        QRectF(self.width() - self.chev - 10, (self.height() - 20) / 2, 20, 20), col, 1.9)


class SortButton(QAbstractButton):
    def __init__(self, value="Nome"):
        super().__init__()
        self.value = value
        self.setFixedSize(142, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(mkfont(14))
        p.setPen(QColor("#aab4c8"))
        txt = "Ordenar por: "
        w1 = QFontMetrics(p.font()).horizontalAdvance(txt)
        p.drawText(QRectF(0, 0, w1, self.height()), AL_VL, txt)
        p.setFont(mkfont(14, bold=True))
        p.setPen(QColor("#ffffff" if not self.underMouse() else "#bcd6ff"))
        w2 = QFontMetrics(p.font()).horizontalAdvance(self.value)
        p.drawText(QRectF(w1, 0, w2 + 4, self.height()), AL_VL, self.value)
        Icons.paint(p, "chevron_down", QRectF(w1 + w2 + 6, (self.height() - 16) / 2, 16, 16), "#c5cee0", 2.0)


class Avatar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(56, 56)
        self.pm = None
        self.reload()

    def reload(self):
        self.pm = None
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for base in (str(CONFIG_DIR), script_dir):
            for n in ("avatar.png", "avatar.jpg", "avatar.jpeg"):
                f = os.path.join(base, n)
                if os.path.exists(f):
                    pm = QPixmap(f)
                    if not pm.isNull():
                        self.pm = pm
                        break
            if self.pm:
                break
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        circle = QPainterPath()
        circle.addEllipse(QRectF(2, 2, 52, 52))
        p.save()
        p.setClipPath(circle)
        if self.pm:
            s = min(self.pm.width(), self.pm.height())
            src = QRectF((self.pm.width() - s) / 2, (self.pm.height() - s) / 2, s, s)
            p.drawPixmap(QRectF(2, 2, 52, 52), self.pm, src)
        else:
            g = QLinearGradient(0, 0, 0, 56)
            g.setColorAt(0, QColor("#46597d"))
            g.setColorAt(1, QColor("#1b2538"))
            p.fillRect(QRectF(0, 0, 56, 56), QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2b3550"))
            p.drawEllipse(QRectF(6, 38, 44, 34))
            p.setBrush(QColor("#c99a7c"))
            p.drawRect(QRectF(23, 30, 10, 12))
            p.setBrush(QColor("#d9ad8e"))
            p.drawEllipse(QRectF(17, 11, 22, 26))
            p.setBrush(QColor("#1c1817"))
            hair = QPainterPath()
            hair.addEllipse(QRectF(16, 8, 24, 16))
            p.drawPath(hair)
        p.restore()
        p.setPen(QPen(QColor("#a9b8d2"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(1.5, 1.5, 53, 53))


# ───────────────────────────── card de arquivo ─────────────────────────────
class FileCard(QFrame):
    selectionChanged = pyqtSignal(object, bool)
    opened = pyqtSignal(object)

    # (margem topo, altura do ícone, espaço, altura do card)
    LAYOUTS = {
        "folder": (24, 130, 4, 223),
        "folder_photos": (24, 130, 4, 223),
        "folder_shared": (24, 130, 4, 223),
        "pdf": (28, 98, 4, 188),
        "image": (25, 138, 14, 244),
        "zip": (25, 138, 14, 244),
        "doc": (25, 138, 14, 244),
    }

    def __init__(self, d):
        super().__init__()
        self.d = d
        self.kind = d["kind"]
        self.cat = d["cat"]
        self.shared = d.get("shared", False)
        self.fav = d.get("fav", False)
        self.selected = False
        self.hover = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        top, ih, gap, height = self.LAYOUTS[self.kind]
        self.setFixedHeight(height)
        self.setMinimumWidth(150)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, top, 22, 0)
        lay.setSpacing(0)
        lay.addWidget(BigIcon(self.kind, d.get("pixmap"), ih))
        lay.addSpacing(gap)
        self.name_lbl = QLabel(d["name"])
        self.name_lbl.setStyleSheet("color:#ffffff;font-size:16px;font-weight:700;background:transparent;")
        self.name_lbl.setFixedHeight(22)
        self.name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.meta_lbl = QLabel(d["meta"])
        self.meta_lbl.setStyleSheet(f"color:{MUTED};font-size:14px;background:transparent;")
        self.meta_lbl.setFixedHeight(22)
        self.meta_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for lb in (self.name_lbl, self.meta_lbl):
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.name_lbl)
        lay.addSpacing(4)
        lay.addWidget(self.meta_lbl)
        lay.addStretch(1)

        self.checkbox = CheckBox(self)
        self.checkbox.move(21, 18)
        self.checkbox.toggled.connect(self._on_toggle)
        self.menu_btn = IconButton("dots", 22, (32, 26), "#e1e7f5", parent=self)
        if d.get("selected"):
            self.set_selected(True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.menu_btn.move(self.width() - 52, 17)

    def _on_toggle(self, on):
        self.selected = on
        self.update()
        self.selectionChanged.emit(self, on)

    def set_selected(self, on):
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(on)
        self.checkbox.blockSignals(False)
        self.selected = on
        self.update()

    def set_name(self, name):
        self.d["name"] = name
        self.name_lbl.setText(name)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.checkbox.click()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.selected:
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor("#101c38"))
            g.setColorAt(1, QColor("#0d1528"))
            p.setBrush(QBrush(g))
            for i, a in ((4, 18), (3, 30), (2, 55)):
                p.setPen(QPen(QColor(47, 123, 255, a), i))
                p.drawRoundedRect(r.adjusted(i / 2, i / 2, -i / 2, -i / 2), 16, 16)
            p.setPen(QPen(QColor(ACCENT), 1.6))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 16, 16)
        else:
            p.setBrush(QColor("#111a2d" if self.hover else "#0e1627"))
            p.setPen(QPen(QColor("#26324d" if self.hover else "#1b2539"), 1))
            p.drawRoundedRect(r, 16, 16)
        if self.fav:
            Icons.paint(p, "star_fill", QRectF(self.width() - 84, 18, 22, 22), "#f5b942", 1.4)


# ───────────────────────────── barra de ações ─────────────────────────────
class ActionItem(QAbstractButton):
    def __init__(self, icon, label):
        super().__init__()
        self.icon_name = icon
        self.label = label
        self.setFixedHeight(61)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hov = self.underMouse()
        if hov:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 10, 10)
        col = "#ffffff" if hov else "#d3dbeb"
        Icons.paint(p, self.icon_name, QRectF((self.width() - 22) / 2, 9, 22, 22), col, 1.8)
        p.setPen(QColor(col))
        p.setFont(mkfont(12, semi=True))
        p.drawText(QRectF(0, 36, self.width(), 18), AL_C, self.label)


class ActionBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(73)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(0)
        self.btns = {}
        for key, icon, label in (("download", "download", "Baixar"), ("share", "share", "Compart."),
                                 ("fav", "star", "Favorito"), ("rename", "pencil", "Renomear")):
            b = ActionItem(icon, label)
            lay.addWidget(b)
            self.btns[key] = b
        self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor("#0b1428"))
        for i, a in ((4, 20), (2, 50)):
            p.setPen(QPen(QColor(47, 123, 255, a), i))
            p.drawRoundedRect(r.adjusted(i / 2, i / 2, -i / 2, -i / 2), 16, 16)
        p.setPen(QPen(QColor(ACCENT), 1.4))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 16, 16)
        p.setPen(QPen(QColor("#1f2c4a"), 1))
        keys = list(self.btns.values())
        for b in keys[1:]:
            p.drawLine(b.x(), 20, b.x(), self.height() - 20)


# ───────────────────────────── painéis de armazenamento ─────────────────────────────
def draw_progress(p, rect, ratio):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1a2336"))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    fw = max(rect.height(), rect.width() * ratio)
    fr = QRectF(rect.left(), rect.top(), fw, rect.height())
    g = QLinearGradient(fr.left(), 0, fr.right(), 0)
    g.setColorAt(0, QColor("#2f7bff"))
    g.setColorAt(1, QColor("#62aaff"))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(fr, rect.height() / 2, rect.height() / 2)


def _ratio(used, free):
    total = used + free
    return min(1.0, used / total) if total > 0 else 0.0


class StoragePanel(QFrame):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.used = 0
        self.free = 0

    def set_usage(self, used, free):
        self.used, self.free = used, free
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor("#1b2539"), 1))
        p.setBrush(QColor("#0d1527"))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
        Icons.paint(p, "database", QRectF(26, 26, 44, 44), "#3b8bff", 1.5)
        f1, f2 = mkfont(18), mkfont(20, bold=True)
        p.setFont(f1)
        p.setPen(QColor("#ffffff"))
        t1 = "Uso de armazenamento: "
        w1 = QFontMetrics(f1).horizontalAdvance(t1)
        p.drawText(QRectF(81, 24, w1 + 4, 32), AL_VL, t1)
        p.setFont(f2)
        p.setPen(QColor("#3b8bff"))
        p.drawText(QRectF(81 + w1, 24, 260, 32), AL_VL, f"{fmt_size(self.used)} usados")
        p.setFont(mkfont(14))
        p.setPen(QColor("#c5cee0"))
        p.drawText(QRectF(w - 280, 24, 208, 32), AL_VR, f"{fmt_size(self.free)} livres nos discos")
        Icons.paint(p, "chevron_right", QRectF(w - 46, 40, 24, 24), "#c5cee0", 1.9)
        draw_progress(p, QRectF(84, 63, w - 84 - 74, 15), _ratio(self.used, self.free))


class SideStorage(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(142)
        self.used = 0
        self.free = 0

    def set_usage(self, used, free):
        self.used, self.free = used, free
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor("#1c2639"), 1))
        p.setBrush(QColor("#0d1424"))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
        Icons.paint(p, "cloud", QRectF(24, 30, 46, 46), "#3b8bff", 1.5)
        p.setPen(QColor("#ffffff"))
        p.setFont(mkfont(20, bold=True))
        p.drawText(QRectF(86, 28, w - 96, 28), AL_VL, fmt_size(self.used))
        p.setFont(mkfont(13))
        p.setPen(QColor("#aab4c8"))
        p.drawText(QRectF(86, 54, w - 96, 22), AL_VL, "usados na nuvem")
        draw_progress(p, QRectF(23, 90, w - 46, 13), _ratio(self.used, self.free))
        p.setFont(mkfont(14))
        p.setPen(QColor("#aab4c8"))
        p.drawText(QRectF(23, 108, w - 46, 26), AL_VL, f"{fmt_size(self.free)} livres nos discos")


# ───────────────────────────── sidebar ─────────────────────────────
class Logo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.compact = False
        self.setFixedSize(240, 60)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_compact(self, v):
        self.compact = v
        self.setFixedSize(58 if v else 240, 60)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.save()
        p.translate(0, 1)
        p.scale(58 / 24, 58 / 24)
        g = QLinearGradient(0, 0, 24, 24)
        g.setColorAt(0, QColor("#3fd3ff"))
        g.setColorAt(1, QColor("#2f6bff"))
        pen = QPen(QBrush(g), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(_cloud_path())
        pen2 = QPen(QBrush(g), 2.0)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen2)
        _poly(p, [(8, 16.3), (12, 8.4), (16, 16.3)])
        p.drawLine(QPointF(9.8, 13.6), QPointF(14.2, 13.6))
        p.restore()
        if not self.compact:
            p.setPen(QColor("#ffffff"))
            p.setFont(mkfont(23, bold=True))
            p.drawText(QRectF(73, 0, 170, 60), AL_VL, "AndreyCloud")


class NavItem(QAbstractButton):
    def __init__(self, icon, text):
        super().__init__()
        self.icon_name = icon
        self.label = text
        self.collapsed = False
        self.setCheckable(True)
        self.setFixedHeight(59)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        if on:
            for i, a in ((6, 14), (3, 28)):
                p.setPen(QPen(QColor(47, 123, 255, a), i))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r, 14, 14)
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor("#2a6be4"))
            g.setColorAt(1, QColor("#1c52b9"))
            p.setPen(QPen(QColor("#4d90ff"), 1))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r, 14, 14)
            col = "#ffffff"
        else:
            if self.underMouse():
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 10))
                p.drawRoundedRect(r, 14, 14)
            col = "#c5cee0"
        name = self.icon_name
        icol = col
        if on and name == "folder":
            name, icol = "folder_fill", "#8cc4ff"
        ix = 25 if not self.collapsed else (self.width() - 26) / 2
        Icons.paint(p, name, QRectF(ix, (self.height() - 26) / 2, 26, 26), icol, 1.7)
        if not self.collapsed:
            p.setPen(QColor("#ffffff" if on else "#dfe5f2"))
            p.setFont(mkfont(17, semi=on))
            p.drawText(QRectF(73, 0, self.width() - 73, self.height()), AL_VL, self.label)


class Sidebar(QWidget):
    navChanged = pyqtSignal(str)
    toggled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(295)
        self.collapsed = False
        self.logo = Logo(self)
        self.logo.move(30, 70)
        self.collapse_btn = IconButton("chevron_left2", 20, (38, 38), "#c5cee0", bordered=True, parent=self)
        self.collapse_btn.move(238, 61)
        self.collapse_btn.clicked.connect(self.toggle)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(17, 177, 19, 27)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.items = []
        for icon, text in (("home", "Início"), ("folder", "Arquivos"), ("image", "Fotos"),
                           ("users", "Compart."), ("star", "Favoritos"), ("trash", "Lixeira")):
            it = NavItem(icon, text)
            self.group.addButton(it)
            lay.addWidget(it)
            self.items.append(it)
            it.clicked.connect(lambda _=False, t=text: self.navChanged.emit(t))
        self.items[1].setChecked(True)
        lay.addStretch(1)
        self.storage = SideStorage()
        lay.addWidget(self.storage)

    def select(self, name):
        for it in self.items:
            if it.label == name:
                it.setChecked(True)

    def toggle(self):
        self.collapsed = not self.collapsed
        c = self.collapsed
        self.setFixedWidth(96 if c else 295)
        for it in self.items:
            it.collapsed = c
            it.update()
        self.logo.set_compact(c)
        self.storage.setVisible(not c)
        if c:
            self.logo.move(19, 36)
            self.collapse_btn.move(29, 102)
            self.collapse_btn.set_name("chevron_right2")
        else:
            self.logo.move(30, 70)
            self.collapse_btn.move(238, 61)
            self.collapse_btn.set_name("chevron_left2")
        self.toggled.emit()


# ───────────────────────────── configuração ─────────────────────────────
DEFAULT_CONFIG = {"drives": [], "share_port": 8765}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    cfg.pop("root", None)  # versão antiga (uma pasta só)
    drives = cfg.get("drives")
    cfg["drives"] = [d for d in drives if isinstance(d, str)] if isinstance(drives, list) else []
    return cfg


def save_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ───────────────────────────── armazenamento local (backend) ─────────────────────────────
# ───────────────────────────── discos / partições ─────────────────────────────
def mount_label(mp):
    mp = str(mp)
    if os.name == "nt":
        return f"Disco {mp[:2].upper()}"
    return mp


def drive_key(mp):
    """Prefixo curto que identifica o disco dentro dos caminhos da nuvem."""
    mp = str(mp)
    if os.name == "nt":
        return mp[:2].upper()
    return os.path.basename(mp.rstrip("/")) or "raiz"


def parent_of(rel):
    """Pasta-mãe de um item. Itens na raiz de um disco pertencem à visão geral ("")."""
    par = rel.rpartition("/")[0]
    return par if "/" in par else ""


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def same_mount(a, b):
    return _norm(a) == _norm(b)


def mount_ok(mp):
    try:
        if not os.path.isdir(mp):
            return False
        return os.name == "nt" or os.path.ismount(mp)
    except OSError:
        return False


def make_root(mp):
    """Cria (se preciso) a pasta AndreyCloud dentro do disco `mp` e devolve o caminho.
    Se o disco não permitir escrita na raiz (comum no Linux/Mac) e o seu usuário
    morar nele, usa ~/AndreyCloud nesse mesmo disco."""
    cands = [Path(mp) / "AndreyCloud"]
    home = Path.home()
    try:
        common = os.path.commonpath([os.path.abspath(mp), str(home)])
        if _norm(common) == _norm(mp):
            cands.append(home / "AndreyCloud")
    except ValueError:
        pass
    last = None
    for c in cands:
        try:
            c.mkdir(parents=True, exist_ok=True)
            (c / ".trash").mkdir(exist_ok=True)
            return c
        except OSError as ex:
            last = ex
    raise last or OSError("sem permissão")


def list_drives():
    """Lista as partições disponíveis: [{mount, name, total, free}]."""
    found = []
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetErrorMode(1)  # não mostrar "insira um disco" em leitores vazios
        mask = k32.GetLogicalDrives()
        for i in range(26):
            if not mask & (1 << i):
                continue
            mp = f"{chr(65 + i)}:\\"
            if k32.GetDriveTypeW(mp) not in (2, 3, 4):  # removível, fixo, rede
                continue
            buf = ctypes.create_unicode_buffer(261)
            ok = k32.GetVolumeInformationW(mp, buf, 261, None, None, None, None, 0)
            label = buf.value if ok else ""
            found.append((mp, f"Disco {chr(65 + i)}:" + (f" ({label})" if label else "")))
    else:
        seen = set()
        try:
            lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for ln in lines:
            parts = ln.split()
            if len(parts) < 3:
                continue
            dev, mp = parts[0], parts[1].replace("\\040", " ")
            if not dev.startswith("/dev/") or dev.startswith("/dev/loop"):
                continue
            if mp.startswith(("/boot", "/snap", "/var/lib", "/run/snapd")) or dev in seen:
                continue
            seen.add(dev)
            found.append((mp, mp))
        if not found:  # macOS e afins
            found.append(("/", "/"))
            try:
                for c in sorted(Path("/Volumes").iterdir()):
                    if c.is_dir() and os.path.ismount(c):
                        found.append((str(c), str(c)))
            except OSError:
                pass
    out = []
    for mp, name in found:
        try:
            u = shutil.disk_usage(mp)
        except OSError:
            continue
        out.append(dict(mount=mp, name=name, total=u.total, free=u.free))
    return out


IMG_EXT = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "svg"}
ARC_EXT = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"}
VID_EXT = {"mp4", "mkv", "avi", "mov", "webm", "wmv", "flv"}
DOC_EXT = {"doc", "docx", "txt", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "csv", "md", "rtf"}


def classify(name, is_dir=False):
    """Devolve (kind, categoria) a partir do nome."""
    if is_dir:
        return "folder", "Pastas"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        return "pdf", "Documentos"
    if ext in IMG_EXT:
        return "image", "Imagens"
    if ext in ARC_EXT:
        return "zip", "Compactados"
    if ext in VID_EXT:
        return "doc", "Vídeos"
    if ext in DOC_EXT:
        return "doc", "Documentos"
    return "doc", "Outros"


def dir_size(path):
    total = 0
    for r, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


def tree_size(path):
    try:
        return dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
    except OSError:
        return 0


def zip_dir(src, target):
    """Compacta uma pasta (inclui a própria pasta como raiz do zip)."""
    src = Path(src)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for r, dirs, files in os.walk(src):
            rel = os.path.relpath(r, src)
            arc_dir = src.name if rel == "." else f"{src.name}/{rel}".replace("\\", "/")
            if not dirs and not files and rel != ".":
                z.writestr(arc_dir + "/", "")
            for f in files:
                full = os.path.join(r, f)
                arc = os.path.join(src.name, os.path.relpath(full, src))
                try:
                    z.write(full, arc)
                except OSError:
                    pass


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


_thumb_cache = {}


def load_thumb(path, mtime):
    key = (path, mtime)
    if key in _thumb_cache:
        return _thumb_cache[key]
    r = QImageReader(path)
    r.setAutoTransform(True)
    sz = r.size()
    if sz.isValid() and sz.width() > 0 and sz.height() > 0:
        r.setScaledSize(sz.scaled(404, 276, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
    img = r.read()
    pm = QPixmap.fromImage(img) if not img.isNull() else None
    if len(_thumb_cache) > 400:
        _thumb_cache.clear()
    _thumb_cache[key] = pm
    return pm


class CloudStore:
    """Tudo que a nuvem guarda: arquivos reais na pasta "AndreyCloud" de cada disco
    escolhido + um JSON (em ~/.andreycloud/meta.json) com favoritos, links de
    compartilhamento e itens da lixeira.

    Todo caminho relativo ("rel") começa com a chave do disco: "C:/Fotos/a.jpg"."""

    def __init__(self, mounts):
        self.roots = {}    # chave -> pasta AndreyCloud daquele disco
        self.mounts = {}   # chave -> ponto de montagem / letra do disco
        self.errors = []
        self.meta_path = CONFIG_DIR / "meta.json"
        self.lock = threading.RLock()
        self.meta = {"items": {}, "trash": {}}
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            self.meta["items"] = dict(data.get("items", {}))
            self.meta["trash"] = dict(data.get("trash", {}))
        except (OSError, ValueError, AttributeError):
            pass
        self._open_roots(mounts)

    def _open_roots(self, mounts):
        for mp in mounts:
            if any(same_mount(mp, m) for m in self.mounts.values()):
                continue
            if not mount_ok(mp):
                self.errors.append(f"{mount_label(mp)}: disco indisponível no momento.")
                continue
            try:
                root = make_root(mp)
            except OSError as ex:
                self.errors.append(f"{mount_label(mp)}: não consegui criar a pasta AndreyCloud ({ex}).")
                continue
            key = base = drive_key(mp)
            i = 2
            while key in self.roots:
                key = f"{base}{i}"
                i += 1
            self.roots[key] = root
            self.mounts[key] = mp

    # ── persistência
    def save(self):
        with self.lock:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.meta_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.meta_path)

    # ── caminhos
    def split(self, rel):
        key, _, sub = rel.partition("/")
        if key not in self.roots:
            raise ValueError("Esse disco não está selecionado ou está indisponível.")
        return key, sub

    def p(self, rel):
        key, sub = self.split(rel)
        return self.roots[key] / sub if sub else self.roots[key]

    def abs(self, rel):
        key, sub = self.split(rel)
        base = self.roots[key].resolve()
        p = (base / sub).resolve() if sub else base
        if p != base and base not in p.parents:
            raise ValueError("Caminho fora da pasta da nuvem.")
        return p

    def trash_dir(self, key):
        return self.roots[key] / ".trash"

    @staticmethod
    def valid_name(name):
        name = name.strip().rstrip(". ")
        if not name or name in (".", "..") or any(ch in name for ch in '<>:"/\\|?*\0'):
            raise ValueError('Nome inválido. Evite os caracteres  < > : " / \\ | ? *')
        return name

    @staticmethod
    def unique(folder, name, is_dir=False):
        folder = Path(folder)
        cand = folder / name
        if not cand.exists():
            return cand
        stem, ext = (name, "") if is_dir else os.path.splitext(name)
        i = 1
        while True:
            cand = folder / f"{stem} ({i}){ext}"
            if not cand.exists():
                return cand
            i += 1

    @staticmethod
    def _rm(path):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                os.remove(path)
        except OSError:
            pass

    # ── espaço em disco (soma só os discos selecionados, sem contar o mesmo disco duas vezes)
    def _dev(self, key):
        root = self.roots[key]
        if os.name == "nt":
            return os.path.splitdrive(str(root))[0].upper()
        return os.stat(root).st_dev

    def disk_report(self):
        out, seen = [], set()
        for key, root in self.roots.items():
            try:
                dev = self._dev(key)
                if dev in seen:
                    continue
                seen.add(dev)
                u = shutil.disk_usage(root)
                out.append((self.mounts[key], u.total, u.free))
            except OSError:
                pass
        return out

    def free_space(self):
        return sum(free for _mp, _total, free in self.disk_report())

    def best_key(self):
        """Disco com mais espaço livre (destino padrão dos uploads na visão geral)."""
        best, best_free = None, -1
        for key, root in self.roots.items():
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                free = 0
            if free > best_free:
                best, best_free = key, free
        return best

    # ── listagem
    @staticmethod
    def _peek(p):
        n, img = 0, False
        try:
            with os.scandir(p) as it:
                for de in it:
                    n += 1
                    if not img and n <= 60 and not de.is_dir() and classify(de.name)[1] == "Imagens":
                        img = True
        except OSError:
            pass
        return n, img

    def entry(self, rel):
        try:
            p = self.p(rel)
            st = p.stat()
        except (OSError, ValueError):
            return None
        is_dir = p.is_dir()
        kind, cat = classify(p.name, is_dir)
        m = self.meta["items"].get(rel, {})
        date = datetime.date.fromtimestamp(st.st_mtime)
        e = dict(rel=rel, name=p.name, path=str(p), is_dir=is_dir, kind=kind, cat=cat,
                 date=date, mtime=st.st_mtime, fav=bool(m.get("fav")), shared=bool(m.get("share")),
                 parent=parent_of(rel), size=0)
        if is_dir:
            n, has_img = self._peek(p)
            e["meta"] = f"{n} arquivo{'s' if n != 1 else ''}"
            if len(self.roots) > 1:
                e["meta"] += f"  •  {rel.partition('/')[0]}"
            if has_img:
                e["kind"] = "folder_photos"
            if e["shared"]:
                e["kind"] = "folder_shared"
        else:
            e["size"] = st.st_size
            e["meta"] = f"{fmt_size(st.st_size)}  •  {fmt_date(date)}"
        return e

    def walk_all(self):
        out, stack = [], list(self.roots)
        while stack:
            rel = stack.pop()
            try:
                names = os.listdir(self.p(rel))
            except (OSError, ValueError):
                continue
            for n in names:
                if n.startswith("."):
                    continue
                r = f"{rel}/{n}"
                e = self.entry(r)
                if e is None:
                    continue
                out.append(e)
                if e["is_dir"] and not os.path.islink(e["path"]):
                    stack.append(r)
        existing = {e["rel"] for e in out}
        with self.lock:
            # só limpa dados de itens dos discos ativos (discos desmarcados guardam os seus)
            stale = [k for k in self.meta["items"]
                     if k.partition("/")[0] in self.roots and k not in existing]
            for k in stale:
                self.meta["items"].pop(k, None)
            if stale:
                self.save()
        return out

    # ── criar / importar
    def mkdir(self, parent_rel, name):
        name = self.valid_name(name)
        target = self.abs(parent_rel) / name
        if target.exists():
            raise FileExistsError("Já existe um item com esse nome aqui.")
        target.mkdir()
        return f"{parent_rel}/{name}"

    @staticmethod
    def _copy_file(src, dst, cb):
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while True:
                buf = fi.read(1 << 20)
                if not buf:
                    break
                fo.write(buf)
                if cb and cb(len(buf)) is False:
                    raise InterruptedError("cancelado")

    def _copy_tree(self, src, dst, cb):
        os.makedirs(dst, exist_ok=True)
        for r, _dirs, files in os.walk(src):
            rel = os.path.relpath(r, src)
            tdir = dst if rel == "." else os.path.join(dst, rel)
            os.makedirs(tdir, exist_ok=True)
            for f in files:
                self._copy_file(os.path.join(r, f), os.path.join(tdir, f), cb)

    def import_paths(self, parent_rel, paths, cb=None):
        dest_dir = self.abs(parent_rel)
        guards = [r.resolve() for r in self.roots.values()]
        names = []
        for src in paths:
            src = os.path.abspath(src)
            if not os.path.exists(src):
                continue
            rs = Path(src).resolve()
            if any(rs == g or g in rs.parents or rs in g.parents for g in guards):
                raise ValueError("Esse item já está dentro da pasta da nuvem (ou contém a nuvem).")
            is_dir = os.path.isdir(src)
            dest = self.unique(dest_dir, os.path.basename(src.rstrip("\\/")) or "item", is_dir)
            try:
                if is_dir:
                    self._copy_tree(src, str(dest), cb)
                else:
                    self._copy_file(src, str(dest), cb)
            except BaseException:
                self._rm(dest)
                raise
            names.append(dest.name)
        return names

    # ── renomear / mover
    def _move_meta(self, old, new):
        with self.lock:
            items = self.meta["items"]
            for k in list(items):
                if k == old or k.startswith(old + "/"):
                    items[new + k[len(old):]] = items.pop(k)
            self.save()

    def rename(self, rel, new_name):
        new_name = self.valid_name(new_name)
        src = self.p(rel)
        dst = src.with_name(new_name)
        if dst.exists() and os.path.normcase(str(dst)) != os.path.normcase(str(src)) \
                and not os.path.samefile(dst, src):
            raise FileExistsError("Já existe um item com esse nome aqui.")
        os.rename(src, dst)
        parent = rel.rpartition("/")[0]
        new_rel = f"{parent}/{new_name}"
        self._move_meta(rel, new_rel)
        return new_rel

    def move(self, rel, dest_parent):
        src = self.abs(rel)
        dest_dir = self.abs(dest_parent)
        if src.is_dir() and (dest_dir == src or src in dest_dir.parents):
            raise ValueError("Não dá para mover uma pasta para dentro dela mesma.")
        dst = dest_dir / src.name
        if dst.exists():
            raise FileExistsError("Já existe um item com esse nome na pasta de destino.")
        shutil.move(str(src), str(dst))
        new_rel = f"{dest_parent}/{src.name}"
        self._move_meta(rel, new_rel)
        return new_rel

    # ── favoritos / compartilhamento
    def set_fav(self, rel, on):
        with self.lock:
            m = self.meta["items"].setdefault(rel, {})
            if on:
                m["fav"] = True
            else:
                m.pop("fav", None)
            if not m:
                self.meta["items"].pop(rel, None)
            self.save()

    def get_share(self, rel):
        return self.meta["items"].get(rel, {}).get("share")

    def set_share(self, rel):
        with self.lock:
            m = self.meta["items"].setdefault(rel, {})
            if not m.get("share"):
                m["share"] = secrets.token_urlsafe(9)
            self.save()
            return m["share"]

    def unshare(self, rel):
        with self.lock:
            m = self.meta["items"].get(rel)
            if m is not None:
                m.pop("share", None)
                if not m:
                    self.meta["items"].pop(rel, None)
                self.save()

    def has_shares(self):
        with self.lock:
            return any(m.get("share") and k.partition("/")[0] in self.roots
                       for k, m in self.meta["items"].items())

    def path_for_token(self, token):
        with self.lock:
            for rel, m in self.meta["items"].items():
                if m.get("share") == token:
                    try:
                        p = self.p(rel)
                    except ValueError:
                        return None
                    return str(p) if p.exists() else None
        return None

    # ── exportar (baixar)
    def export(self, rel, dest):
        src = self.p(rel)
        if src.is_dir():
            zip_dir(src, dest)
        else:
            shutil.copy2(src, dest)

    # ── lixeira (cada disco tem a sua pasta .trash, então mover é instantâneo)
    def trash_item(self, rel):
        key, _ = self.split(rel)
        p = self.p(rel)
        is_dir = p.is_dir()
        tid = uuid.uuid4().hex[:12]
        tdir = self.trash_dir(key)
        tdir.mkdir(exist_ok=True)
        with self.lock:
            items = self.meta["items"]
            fav = bool(items.get(rel, {}).get("fav"))
            shutil.move(str(p), str(tdir / tid))
            for k in list(items):
                if k == rel or k.startswith(rel + "/"):
                    items.pop(k)
            self.meta["trash"][tid] = dict(
                name=p.name, orig=rel, key=key, is_dir=is_dir, fav=fav,
                deleted=datetime.datetime.now().isoformat(timespec="seconds"))
            self.save()

    def trash_entries(self):
        with self.lock:
            tmeta = dict(self.meta["trash"])
        out = []
        for tid, info in tmeta.items():
            key = info.get("key")
            if key not in self.roots:
                continue
            p = self.trash_dir(key) / tid
            if not p.exists():
                continue
            is_dir = p.is_dir()
            kind, cat = classify(info.get("name", tid), is_dir)
            try:
                dt = datetime.datetime.fromisoformat(info["deleted"])
            except (KeyError, ValueError):
                dt = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            size = dir_size(p) if is_dir else p.stat().st_size
            out.append(dict(
                rel="", trash_id=tid, name=info.get("name", tid), path=str(p), is_dir=is_dir,
                kind=kind, cat=cat, date=dt.date(), mtime=dt.timestamp(), size=size,
                fav=False, shared=False, parent="",
                meta=f"{fmt_size(size)}  •  Excluído em {fmt_date(dt.date())}"))
        return out

    def restore(self, tid):
        with self.lock:
            info = self.meta["trash"].get(tid)
            if info is None or info.get("key") not in self.roots:
                raise ValueError("Item não encontrado na lixeira.")
            key = info["key"]
            parent = info.get("orig", key).rpartition("/")[0] or key
            dest_dir = self.p(parent)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = self.unique(dest_dir, info["name"], info.get("is_dir", False))
            shutil.move(str(self.trash_dir(key) / tid), str(dest))
            new_rel = f"{parent}/{dest.name}"
            if info.get("fav"):
                self.meta["items"][new_rel] = {"fav": True}
            self.meta["trash"].pop(tid, None)
            self.save()
            return new_rel

    def purge(self, tid):
        with self.lock:
            info = self.meta["trash"].get(tid, {})
            if info.get("key") in self.roots:
                self._rm(self.trash_dir(info["key"]) / tid)
                self.meta["trash"].pop(tid, None)
                self.save()

    def empty_trash(self):
        with self.lock:
            for key in self.roots:
                try:
                    for child in list(self.trash_dir(key).iterdir()):
                        self._rm(child)
                except OSError:
                    pass
            for tid in [t for t, i in self.meta["trash"].items() if i.get("key") in self.roots]:
                self.meta["trash"].pop(tid, None)
            self.save()


# ───────────────────────────── servidor de compartilhamento (rede local) ─────────────────────────────
class _ShareHandler(BaseHTTPRequestHandler):
    server_ref = None
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _target(self):
        parts = [unquote(x) for x in urlparse(self.path).path.split("/") if x]
        if len(parts) >= 2 and parts[0] == "s":
            return self.server_ref.get_store().path_for_token(parts[1])
        return None

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def _serve(self, with_body):
        path = self._target()
        if not path or not os.path.exists(path):
            self.send_error(404, "Not found")
            return
        try:
            if os.path.isdir(path):
                self._send_folder(path, with_body)
            else:
                self._send_file(path, with_body)
        except OSError:
            pass

    def _headers(self, ctype, size, filename, inline):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("X-Content-Type-Options", "nosniff")
        disp = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{quote(filename)}")
        self.end_headers()

    def _send_file(self, path, with_body):
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        inline = ctype == "application/pdf" or (
            ctype.startswith(("image/", "video/", "audio/", "text/")) and ctype != "text/html")
        self._headers(ctype, os.path.getsize(path), os.path.basename(path), inline)
        if with_body:
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _send_folder(self, path, with_body):
        with tempfile.TemporaryFile() as tmp:
            zip_dir(path, tmp)
            size = tmp.tell()
            tmp.seek(0)
            self._headers("application/zip", size, os.path.basename(path) + ".zip", False)
            if with_body:
                shutil.copyfileobj(tmp, self.wfile, 1 << 20)


class ShareServer:
    def __init__(self, get_store):
        self.get_store = get_store
        self.httpd = None
        self.port = None

    @property
    def running(self):
        return self.httpd is not None

    def start(self, port):
        if self.httpd:
            return self.port
        handler = type("ShareHandler", (_ShareHandler,), {"server_ref": self})
        last = None
        for p in range(port, port + 10):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", p), handler)
                self.port = p
                break
            except OSError as ex:
                last = ex
        if self.httpd is None:
            raise OSError(f"Não consegui abrir uma porta para compartilhar ({last}).")
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


# ───────────────────────────── página "Meus Arquivos" ─────────────────────────────
class DriveDialog(QDialog):
    """Lista as partições do PC e deixa marcar quais a nuvem vai usar."""

    def __init__(self, parent, current, first_run=False):
        super().__init__(parent)
        self.setWindowTitle("Escolher discos")
        self.setMinimumWidth(620)
        cur = {_norm(m) for m in current}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(10)
        title = QLabel("Onde sua nuvem vai guardar os arquivos?" if first_run else "Discos da nuvem")
        title.setStyleSheet("color:#ffffff;font-size:19px;font-weight:700;")
        lay.addWidget(title)
        info = QLabel("Marque os discos/partições que quiser usar. Vou criar a pasta “AndreyCloud” "
                      "dentro de cada um e somar o espaço livre de todos. Você pode mudar isso "
                      "quando quiser em Configurações.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{MUTED};font-size:13px;")
        lay.addWidget(info)
        lay.addSpacing(6)

        self.rows, self.free = [], {}
        drives = list_drives()
        known = {_norm(d["mount"]) for d in drives}
        for d in drives:
            cb = QCheckBox(f"{d['name']}   —   {fmt_size(d['free'])} livres de {fmt_size(d['total'])}")
            cb.setChecked(_norm(d["mount"]) in cur)
            cb.toggled.connect(self._update)
            lay.addWidget(cb)
            self.rows.append((cb, d["mount"]))
            self.free[d["mount"]] = d["free"]
        for m in current:  # discos já escolhidos que não estão conectados agora
            if _norm(m) not in known:
                cb = QCheckBox(f"{mount_label(m)}   —   indisponível agora (continua na lista)")
                cb.setChecked(True)
                cb.toggled.connect(self._update)
                lay.addWidget(cb)
                self.rows.append((cb, m))
        if not self.rows:
            lay.addWidget(QLabel("Não encontrei nenhum disco."))

        lay.addSpacing(6)
        self.total = QLabel()
        self.total.setStyleSheet("color:#8fb8ff;font-size:14px;font-weight:600;")
        lay.addWidget(self.total)
        lay.addSpacing(8)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.b_cancel = QPushButton("Sair" if first_run else "Cancelar")
        self.b_ok = QPushButton("Continuar" if first_run else "Salvar")
        brow.addWidget(self.b_cancel)
        brow.addWidget(self.b_ok)
        lay.addLayout(brow)
        self.b_cancel.clicked.connect(self.reject)
        self.b_ok.clicked.connect(self.accept)
        self._update()

    def selected(self):
        return [m for cb, m in self.rows if cb.isChecked()]

    def _update(self, *_):
        sel = self.selected()
        total = sum(self.free.get(m, 0) for m in sel)
        n = len(sel)
        self.total.setText(f"Espaço livre somado: {fmt_size(total)}  "
                           f"({n} disco{'s' if n != 1 else ''} marcado{'s' if n != 1 else ''})")
        self.b_ok.setEnabled(n > 0)


CHIP_QSS = """
QPushButton{background:#0e1525;color:#cfd6e6;border:1px solid #1f2a40;border-radius:15px;
            padding:0 22px;font-size:15px;}
QPushButton:hover{background:#141d33;}
QPushButton:checked{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #3f8dff,stop:1 #1f6bf0);
            border:1px solid #5aa0ff;color:white;font-weight:600;}
"""

TITLES = {"Início": "Início", "Arquivos": "Meus Arquivos", "Fotos": "Fotos",
          "Compart.": "Compartilhados", "Favoritos": "Favoritos", "Lixeira": "Lixeira"}
SUBTITLES = {"Início": "Seus arquivos mais recentes.",
             "Arquivos": "Seus arquivos, organizados e sempre com você.",
             "Fotos": "Todas as imagens da sua nuvem.",
             "Compart.": "Itens com link ativo na sua rede local.",
             "Favoritos": "Os itens que você marcou com estrela.",
             "Lixeira": "Itens excluídos. Restaure ou apague de vez."}
EMPTY_MSG = {"Início": "Sua nuvem está vazia.\nArraste arquivos para cá ou clique em Upload.",
             "Arquivos": "Nenhum arquivo por aqui.\nArraste arquivos para esta janela ou clique em Upload.",
             "Fotos": "Nenhuma foto na sua nuvem ainda.",
             "Compart.": "Nada compartilhado ainda.\nUse o botão Compart. em qualquer item.",
             "Favoritos": "Você ainda não favoritou nada.",
             "Lixeira": "A lixeira está vazia."}
MAX_CARDS = 300


class FilesPage(QWidget):
    navRequest = pyqtSignal(str)
    usageChanged = pyqtSignal(object, object)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.store = CloudStore(cfg.get("drives", []))
        self.share = ShareServer(lambda: self.store)
        self.cards = []
        self.cols = 3
        self.nav = "Arquivos"
        self.cur = ""
        self.chip = "Todos"
        self.query = ""
        self.sort_mode = "Nome"
        self.active = None
        self.all_entries = []
        self.trash_list = []
        self.usage = (0, 0)
        self.activity = collections.deque(maxlen=40)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(33, 32, 29, 30)
        root.setSpacing(0)

        # ── barra superior
        top = QHBoxLayout()
        top.setSpacing(0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar...")
        self.search.setFixedSize(544, 56)
        self.search.setStyleSheet(
            "QLineEdit{background:#0e1525;border:1px solid #1d2840;border-radius:28px;"
            "padding-left:64px;padding-right:20px;color:#ffffff;font-size:17px;}"
            "QLineEdit:focus{border:1px solid #2f7bff;}")
        pal = self.search.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, QColor("#8b96ab"))
        self.search.setPalette(pal)
        self.search.textChanged.connect(self._on_search)
        ic = IconButton("search", 26, (30, 30), "#c5cee0", parent=self.search)
        ic.move(21, 13)
        ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        top.addWidget(self.search)
        top.addStretch(1)
        self.bell = IconButton("bell", 28, (40, 40), "#c5cee0", badge=False)
        self.gear = IconButton("gear", 28, (40, 40), "#c5cee0")
        self.avatar = Avatar()
        self.chev = IconButton("chevron_down", 22, (32, 40), "#c5cee0")
        self.bell.clicked.connect(self._show_activity)
        self.gear.clicked.connect(self._settings)
        self.chev.clicked.connect(self._user_menu)
        top.addWidget(self.bell)
        top.addSpacing(26)
        top.addWidget(self.gear)
        top.addSpacing(32)
        top.addWidget(self.avatar)
        top.addSpacing(13)
        top.addWidget(self.chev)
        root.addLayout(top)
        root.addSpacing(57)

        # ── cabeçalho
        hdr = QHBoxLayout()
        hdr.setSpacing(0)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title = QLabel("Meus Arquivos")
        self.title.setStyleSheet("color:#ffffff;font-size:36px;font-weight:800;background:transparent;")
        self.sub = QLabel(SUBTITLES["Arquivos"])
        self.sub.setStyleSheet(f"color:{MUTED};font-size:17px;background:transparent;")
        self.sub.setFixedHeight(26)
        self.sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.crumb = QWidget()
        self.crumb.setFixedHeight(26)
        self.crumb.setStyleSheet("background:transparent;")
        self.crumb_lay = QHBoxLayout(self.crumb)
        self.crumb_lay.setContentsMargins(0, 0, 0, 0)
        self.crumb_lay.setSpacing(4)
        self.crumb.hide()
        left.addWidget(self.title)
        left.addWidget(self.sub)
        left.addWidget(self.crumb)
        hdr.addLayout(left, 1)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_upload = PillButton("Upload", "upload", 150, 18, 54, "chevron_down", 24, primary=True)
        self.btn_selall = PillButton("Selecionar tudo", "check", 178, 16, 50)
        self.btn_folder = PillButton("Nova Pasta", "folder_plus", 158, 16, 50)
        self.btn_delete = PillButton("Excluir", "trash", 158, 16, 50)
        self.btn_empty = PillButton("Esvaziar", "trash", 140, 16, 50)
        self.btn_view = PillButton("Visualização", "grid", 172, 16, 50, "chevron_down", 18)
        for b in (self.btn_upload, self.btn_selall, self.btn_folder, self.btn_delete,
                  self.btn_empty, self.btn_view):
            btns.addWidget(b)
        self.btn_empty.hide()
        self.btn_delete.hide()
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 8, 0, 0)
        wrap.addLayout(btns)
        wrap.addStretch(1)
        hdr.addLayout(wrap)
        root.addLayout(hdr)
        root.addSpacing(28)
        self.btn_upload.clicked.connect(self._upload_menu)
        self.btn_folder.clicked.connect(self.new_folder)
        self.btn_empty.clicked.connect(self.empty_trash)
        self.btn_view.clicked.connect(self._view_menu)
        self.btn_selall.clicked.connect(lambda _=False: self._toggle_select_all())
        self.btn_delete.clicked.connect(self._delete_selected)

        # ── chips + ordenar
        row = QHBoxLayout()
        row.setSpacing(12)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for name in ("Todos", "Pastas", "Documentos", "Imagens", "Vídeos", "Compactados", "Outros"):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFixedHeight(41)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(CHIP_QSS)
            b.setChecked(name == "Todos")
            self.chip_group.addButton(b)
            row.addWidget(b)
            b.clicked.connect(lambda _=False, n=name: self._set_chip(n))
        row.addStretch(1)
        self.sort_btn = SortButton("Nome")
        self.sort_btn.clicked.connect(self._sort_menu)
        row.addWidget(self.sort_btn)
        row.addSpacing(6)
        sep = QFrame()
        sep.setFixedSize(1, 28)
        sep.setStyleSheet("background:#1f2a40;")
        row.addWidget(sep)
        row.addSpacing(6)
        self.list_btn = IconButton("list", 24, (40, 40), "#c5cee0")
        self.list_btn.clicked.connect(self._view_menu)
        row.addWidget(self.list_btn)
        root.addLayout(row)
        root.addSpacing(27)

        # ── grade de arquivos (com scroll)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:8px;margin:0;}"
            "QScrollBar::handle:vertical{background:#26324d;border-radius:4px;min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}")
        self.scroll.viewport().setAutoFillBackground(False)
        self.host = QWidget()
        self.host.setObjectName("host")
        self.host.setStyleSheet("#host{background:transparent;}")
        hl = QVBoxLayout(self.host)
        hl.setContentsMargins(0, 0, 0, 21)
        hl.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(21)
        self.grid.setVerticalSpacing(21)
        hl.addLayout(self.grid)
        self.empty = QLabel("")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet(f"color:{MUTED};font-size:17px;background:transparent;padding:60px;")
        hl.addWidget(self.empty)
        self.more = QLabel("")
        self.more.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.more.setStyleSheet(f"color:{MUTED};font-size:14px;background:transparent;padding:20px;")
        self.more.hide()
        hl.addWidget(self.more)
        hl.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        # ── painel de armazenamento
        self.storage = StoragePanel()
        self.storage.clicked.connect(self._storage_info)
        root.addWidget(self.storage)

        # ── barra de ações (flutua sobre o card selecionado)
        self.bar = ActionBar(self)
        self.bar.btns["download"].clicked.connect(self._act_download)
        self.bar.btns["share"].clicked.connect(self._act_share)
        self.bar.btns["fav"].clicked.connect(self._act_fav)
        self.bar.btns["rename"].clicked.connect(self._act_rename)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self._reposition_bar())

        # ── atalhos
        for seq, fn in (("Delete", self._kb_delete), ("F2", self._act_rename), ("F5", self.reload),
                        ("Ctrl+F", self.search.setFocus), ("Alt+Left", self.go_up),
                        ("Ctrl+A", self._kb_select_all)):
            QShortcut(QKeySequence(seq), self).activated.connect(fn)

        self._ready = False
        self.reload()
        self._ready = True
        QApplication.instance().applicationStateChanged.connect(self._app_state)
        if self.store.has_shares():
            try:
                self._ensure_server()
            except OSError:
                pass
        if self.store.errors:
            msg = "\n".join(self.store.errors)
            QTimer.singleShot(400, lambda: QMessageBox.warning(self, "AndreyCloud", msg))

    # ─────────── dados
    def reload(self):
        self.all_entries = self.store.walk_all()
        self.trash_list = self.store.trash_entries()
        used = sum(e["size"] for e in self.all_entries if not e["is_dir"]) + \
            sum(e["size"] for e in self.trash_list)
        free = self.store.free_space()
        self.usage = (used, free)
        self.storage.set_usage(used, free)
        self.usageChanged.emit(used, free)
        self._refresh()

    def _app_state(self, state):
        if self._ready and state == Qt.ApplicationState.ApplicationActive:
            QTimer.singleShot(150, self.reload)

    def _view_entries(self):
        nav, q = self.nav, self.query
        allv = self.all_entries
        if nav == "Lixeira":
            base = list(self.trash_list)
        elif nav == "Início":
            base = sorted((e for e in allv if not e["is_dir"]), key=lambda e: -e["mtime"])
        elif nav == "Fotos":
            base = [e for e in allv if e["cat"] == "Imagens"]
        elif nav == "Compart.":
            base = [e for e in allv if e["shared"]]
        elif nav == "Favoritos":
            base = [e for e in allv if e["fav"]]
        else:
            base = list(allv) if q else [e for e in allv if e["parent"] == self.cur]
        if self.chip != "Todos":
            base = [e for e in base if e["cat"] == self.chip]
        if q:
            base = [e for e in base if q in e["name"].lower()]
        if nav == "Início" and not q:
            base = base[:24]
        if self.sort_mode == "Nome":
            base.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        elif self.sort_mode == "Data":
            base.sort(key=lambda e: -e["mtime"])
        else:
            base.sort(key=lambda e: -e["size"])
        return base

    # ─────────── cards
    def _make_card(self, e):
        kind, pm = e["kind"], None
        if kind == "image":
            pm = load_thumb(e["path"], e["mtime"])
            if pm is None:
                kind = "doc"
        meta = e["meta"]
        if e["shared"] and not e["is_dir"]:
            meta += "  •  Compartilhado"
        card = FileCard(dict(kind=kind, name=e["name"], meta=meta, cat=e["cat"],
                             pixmap=pm, shared=e["shared"], fav=e["fav"]))
        card.entry = e
        card.setToolTip(e["path"])
        card.selectionChanged.connect(self._on_selected)
        card.opened.connect(self._open_card)
        card.menu_btn.clicked.connect(lambda _=False, c=card: self._card_menu(c))
        card.setParent(self.host)
        self.cards.append(card)
        return card

    def _refresh(self):
        while self.grid.count():
            self.grid.takeAt(0)
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        self.active = None
        ents = self._view_entries()
        total = len(ents)
        for i, e in enumerate(ents[:MAX_CARDS]):
            c = self._make_card(e)
            self.grid.addWidget(c, i // self.cols, i % self.cols, Qt.AlignmentFlag.AlignTop)
            c.show()
        for col in range(6):
            self.grid.setColumnStretch(col, 1 if col < self.cols else 0)
        if total == 0:
            self.empty.setText(f"Nenhum resultado para “{self.query}”" if self.query
                               else EMPTY_MSG.get(self.nav, ""))
        self.empty.setVisible(total == 0)
        self.more.setText(f"Mostrando {MAX_CARDS} de {total} itens — use a busca ou os filtros para refinar.")
        self.more.setVisible(total > MAX_CARDS)
        self._update_header(total)
        QTimer.singleShot(0, self._reposition_bar)

    def _update_header(self, total):
        nav = self.nav
        crumbs = nav == "Arquivos" and bool(self.cur) and not self.query
        title = self.cur.rpartition("/")[2] if crumbs else TITLES.get(nav, nav)
        self.title.setText(title)
        if self.query:
            self.sub.setText(f"{total} resultado{'s' if total != 1 else ''} para “{self.query}”")
        else:
            self.sub.setText(SUBTITLES.get(nav, ""))
        self.sub.setVisible(not crumbs)
        self.crumb.setVisible(crumbs)
        if crumbs:
            self._rebuild_crumb()
        trash = nav == "Lixeira"
        self.btn_upload.setVisible(not trash)
        self.btn_empty.setVisible(trash and bool(self.trash_list))
        self._sync_selection_ui()

    def _rebuild_crumb(self):
        while self.crumb_lay.count():
            it = self.crumb_lay.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
                it.widget().deleteLater()

        def link(text, rel, last):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFlat(True)
            b.setStyleSheet(
                f"QPushButton{{color:{'#ffffff' if last else '#8fb8ff'};font-size:17px;border:none;"
                f"background:transparent;padding:0 2px;{'font-weight:700;' if last else ''}}}"
                "QPushButton:hover{color:#ffffff;}")
            b.clicked.connect(lambda _=False, r=rel: self.go_folder(r))
            self.crumb_lay.addWidget(b)

        parts = [x for x in self.cur.split("/") if x]
        key, rest = parts[0], parts[1:]
        link("Meus Arquivos", "", not rest)
        acc = key
        for i, part in enumerate(rest):
            sep = QLabel("›")
            sep.setStyleSheet(f"color:{MUTED};font-size:17px;background:transparent;")
            self.crumb_lay.addWidget(sep)
            acc = f"{acc}/{part}"
            link(part, acc, i == len(rest) - 1)
        where = QLabel(f"  em {mount_label(self.store.mounts.get(key, key))}")
        where.setStyleSheet(f"color:{MUTED};font-size:14px;background:transparent;")
        self.crumb_lay.addWidget(where)
        self.crumb_lay.addStretch(1)

    def selected_cards(self):
        return [c for c in self.cards if c.selected]

    def _targets(self, c):
        sel = self.selected_cards()
        return sel if c in sel else [c]

    def _on_selected(self, card, on):
        if on:
            self.active = card
        elif self.active is card:
            self.active = next((c for c in self.cards if c.selected), None)
        self._sync_selection_ui()
        self._reposition_bar()

    def _reselect(self, rel):
        for c in self.cards:
            if c.entry.get("rel") == rel:
                c.set_selected(True)
                self.active = c
                break
        QTimer.singleShot(0, self._reposition_bar)
        QTimer.singleShot(60, self._reposition_bar)

    def _reposition_bar(self):
        c = self.active
        if (c is None or self.nav == "Lixeira" or not c.isVisible()
                or not c.selected or c.height() == 0):
            self.bar.hide()
            return
        tl = c.mapTo(self, QPoint(0, 0))
        vp = self.scroll.geometry()
        if tl.y() < vp.top() - 5 or tl.y() + c.height() > vp.bottom() + 30:
            self.bar.hide()
            return
        self.bar.btns["fav"].icon_name = "star_fill" if c.fav else "star"
        self.bar.btns["fav"].update()
        self.bar.setGeometry(tl.x() - 11, tl.y() + c.height() - 3, c.width() + 22, 73)
        self.bar.show()
        self.bar.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._reposition_bar)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._reposition_bar)
        QTimer.singleShot(60, self._reposition_bar)

    # ─────────── navegação / filtros
    def set_nav(self, name):
        self.nav = name
        if name == "Arquivos":
            self.cur = ""
        self.reload()

    def go_folder(self, rel):
        self.nav = "Arquivos"
        self.cur = rel
        self.reload()

    def go_up(self):
        if self.nav == "Arquivos" and self.cur:
            self.go_folder(parent_of(self.cur))

    def open_folder(self, rel):
        self.query = ""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.navRequest.emit("Arquivos")
        self.go_folder(rel)

    def _set_chip(self, name):
        self.chip = name
        self._refresh()

    def _on_search(self, text):
        self.query = text.strip().lower()
        self._refresh()

    # ─────────── menus
    def _card_menu(self, c):
        e = c.entry
        m = QMenu(self)
        pos = c.menu_btn.mapToGlobal(QPoint(0, c.menu_btn.height()))
        if e.get("trash_id"):
            a_res = m.addAction("Restaurar")
            m.addSeparator()
            a_purge = m.addAction("Excluir definitivamente")
            act = m.exec(pos)
            if act == a_res:
                self._restore(self._targets(c))
            elif act == a_purge:
                self._purge(self._targets(c))
            return
        a_open = m.addAction("Abrir")
        a_dl = m.addAction("Baixar" if not e["is_dir"] else "Baixar como ZIP")
        a_sh = m.addAction("Gerenciar compartilhamento" if e["shared"] else "Compartilhar")
        a_fav = m.addAction("Remover dos favoritos" if e["fav"] else "Adicionar aos favoritos")
        a_ren = m.addAction("Renomear")
        a_mov = m.addAction("Mover para…")
        m.addSeparator()
        a_del = m.addAction("Mover para a lixeira")
        act = m.exec(pos)
        if act == a_open:
            self._open_card(c)
        elif act == a_dl:
            self._download(c)
        elif act == a_sh:
            self._share(c)
        elif act == a_fav:
            self._toggle_fav(c)
        elif act == a_ren:
            self._rename(c)
        elif act == a_mov:
            self._move(c)
        elif act == a_del:
            self._trash_cards(self._targets(c))

    def _sort_menu(self):
        m = QMenu(self)
        acts = {m.addAction(n): n for n in ("Nome", "Data", "Tamanho")}
        act = m.exec(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())))
        if act in acts:
            self.sort_mode = acts[act]
            self.sort_btn.value = self.sort_mode
            self.sort_btn.update()
            self._refresh()

    def _view_menu(self):
        m = QMenu(self)
        acts = {m.addAction("Grade ampla (2 colunas)"): 2,
                m.addAction("Grade padrão (3 colunas)"): 3,
                m.addAction("Grade compacta (4 colunas)"): 4}
        act = m.exec(self.btn_view.mapToGlobal(QPoint(0, self.btn_view.height())))
        if act in acts:
            self.cols = acts[act]
            self._refresh()

    def _upload_menu(self):
        m = QMenu(self)
        a_files = m.addAction("Enviar arquivos…")
        a_dir = m.addAction("Enviar pasta…")
        act = m.exec(self.btn_upload.mapToGlobal(QPoint(0, self.btn_upload.height())))
        if act == a_files:
            paths, _ = QFileDialog.getOpenFileNames(self, "Enviar arquivos")
            self._import(paths)
        elif act == a_dir:
            d = QFileDialog.getExistingDirectory(self, "Enviar pasta")
            if d:
                self._import([d])

    def _user_menu(self):
        m = QMenu(self)
        a_photo = m.addAction("Trocar foto de perfil…")
        a_open = m.addAction("Abrir pasta da nuvem")
        a_cfg = m.addAction("Configurações")
        a_about = m.addAction("Sobre")
        m.addSeparator()
        a_quit = m.addAction("Sair")
        act = m.exec(self.chev.mapToGlobal(QPoint(0, self.chev.height())))
        if act == a_photo:
            f, _ = QFileDialog.getOpenFileName(self, "Escolher foto", "",
                                               "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)")
            pm = QPixmap(f) if f else QPixmap()
            if not pm.isNull():
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                pm.save(str(CONFIG_DIR / "avatar.png"), "PNG")
                self.avatar.reload()
        elif act == a_open:
            self._open_cloud_folder()
        elif act == a_cfg:
            self._settings()
        elif act == a_about:
            QMessageBox.about(
                self, "Sobre o AndreyCloud",
                "<b>AndreyCloud</b><br>Nuvem pessoal que roda localmente no seu PC.<br>"
                "100% gratuita e open source.<br><br>"
                "Seus arquivos ficam em:<br>" + "<br>".join(str(r) for r in self.store.roots.values()))
        elif act == a_quit:
            self.window().close()

    # ─────────── utilidades de UI
    def _try(self, fn, *args):
        try:
            return fn(*args)
        except InterruptedError:
            return None
        except (OSError, ValueError, shutil.Error) as ex:
            QMessageBox.warning(self, "AndreyCloud", str(ex))
            return None

    def _log(self, text):
        self.activity.appendleft(f"{datetime.datetime.now():%H:%M}  —  {text}")
        self.bell.badge = True
        self.bell.update()

    def _show_activity(self):
        self.bell.badge = False
        self.bell.update()
        body = "\n".join(self.activity) if self.activity else "Nenhuma atividade nesta sessão."
        QMessageBox.information(self, "Atividade recente", body)

    def _open_cloud_folder(self):
        roots = list(self.store.roots.items())
        if not roots:
            return
        if len(roots) == 1:
            target = roots[0][1]
        else:
            m = QMenu(self)
            acts = {m.addAction(f"{mount_label(self.store.mounts[k])}  —  {r}"): r for k, r in roots}
            act = m.exec(QCursor.pos())
            if act not in acts:
                return
            target = acts[act]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _pick_root(self, text):
        keys = list(self.store.roots)
        if len(keys) == 1:
            return keys[0]
        labels = {f"{mount_label(self.store.mounts[k])}  —  {self.store.roots[k]}": k for k in keys}
        choice, ok = QInputDialog.getItem(self, "Escolher disco", text, list(labels), 0, False)
        return labels[choice] if ok else None

    def _storage_info(self):
        used, free = self.usage
        lines = [f"Sua nuvem está usando {fmt_size(used)}.",
                 f"Espaço livre somado dos discos selecionados: {fmt_size(free)}.", ""]
        for mp, total, fr in self.store.disk_report():
            lines.append(f"• {mount_label(mp)}: {fmt_size(fr)} livres de {fmt_size(total)}")
        lines.append("")
        lines.extend(str(r) for r in self.store.roots.values())
        box = QMessageBox(self)
        box.setWindowTitle("Armazenamento")
        box.setText("\n".join(lines))
        b_open = box.addButton("Abrir pasta", QMessageBox.ButtonRole.AcceptRole)
        b_drives = box.addButton("Gerenciar discos…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            self._open_cloud_folder()
        elif box.clickedButton() is b_drives:
            self._settings()

    def _settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Configurações")
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Discos da nuvem"))
        sel = {"mounts": list(self.cfg.get("drives", []))}
        row = QHBoxLayout()
        summary = QLabel()
        summary.setWordWrap(True)
        btn = QPushButton("Escolher discos…")
        row.addWidget(summary, 1)
        row.addWidget(btn)
        lay.addLayout(row)
        hint = QLabel("A pasta “AndreyCloud” é criada em cada disco marcado. Desmarcar um disco "
                      "só o esconde aqui: os arquivos dele continuam na pasta e voltam se você "
                      "marcá-lo de novo.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(hint)
        lay.addSpacing(6)
        lay.addWidget(QLabel("Porta do compartilhamento na rede local"))
        spin = QSpinBox()
        spin.setRange(1024, 65535)
        spin.setValue(int(self.cfg.get("share_port", 8765)))
        lay.addWidget(spin)
        lay.addSpacing(10)
        brow = QHBoxLayout()
        brow.addStretch(1)
        b_cancel = QPushButton("Cancelar")
        b_ok = QPushButton("Salvar")
        brow.addWidget(b_cancel)
        brow.addWidget(b_ok)
        lay.addLayout(brow)

        def refresh():
            summary.setText(", ".join(mount_label(m) for m in sel["mounts"]) or "Nenhum disco")

        def pick():
            d = DriveDialog(dlg, sel["mounts"])
            if d.exec() == QDialog.DialogCode.Accepted:
                sel["mounts"] = d.selected()
                refresh()

        refresh()
        btn.clicked.connect(pick)
        b_cancel.clicked.connect(dlg.reject)
        b_ok.clicked.connect(dlg.accept)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        port, mounts = spin.value(), sel["mounts"]

        def norm(ms):
            return {_norm(m) for m in ms}

        changed = norm(mounts) != norm(self.cfg.get("drives", []))
        had_server = self.share.running
        if changed:
            new_store = CloudStore(mounts)
            if not new_store.roots:
                QMessageBox.warning(self, "AndreyCloud",
                                    "\n".join(new_store.errors) or "Escolha pelo menos um disco.")
                return
            if new_store.errors:
                QMessageBox.warning(self, "AndreyCloud", "\n".join(new_store.errors))
            self.store = new_store
            self.cfg["drives"] = list(mounts)
            self.cur = ""
        if port != self.cfg.get("share_port") or changed:
            self.cfg["share_port"] = port
            self.share.stop()
            if had_server or self.store.has_shares():
                self._try(self._ensure_server)
        save_config(self.cfg)
        self.reload()

    # ─────────── ações sobre itens
    def _open_card(self, c):
        e = c.entry
        if e.get("trash_id"):
            QMessageBox.information(self, "Lixeira", "Restaure o item para poder abri-lo.")
        elif e["is_dir"]:
            self.open_folder(e["rel"])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(e["path"]))

    def _tree_size(self, p):
        return tree_size(p)

    def _import(self, paths):
        paths = [p for p in paths if p]
        if not paths:
            return
        parent = self.cur if (self.nav == "Arquivos" and self.cur) else self.store.best_key()
        total = max(1, sum(self._tree_size(p) for p in paths))
        dlg = QProgressDialog("Enviando…", "Cancelar", 0, 1000, self)
        dlg.setWindowTitle("Upload")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        done = [0]

        def cb(n):
            done[0] += n
            dlg.setValue(min(999, done[0] * 1000 // total))
            QApplication.processEvents()
            return not dlg.wasCanceled()

        names = []
        try:
            names = self.store.import_paths(parent, paths, cb)
        except InterruptedError:
            self._log("Upload cancelado")
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "AndreyCloud", str(ex))
        finally:
            dlg.close()
        if names:
            self._log("Enviado: " + ", ".join(names[:3]) + (f" e mais {len(names) - 3}" if len(names) > 3 else ""))
        self.reload()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self.nav != "Lixeira":
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        e.acceptProposedAction()
        if paths:
            QTimer.singleShot(0, lambda: self._import(paths))

    def new_folder(self):
        parent = self.cur
        if not parent:
            parent = self._pick_root("Criar a pasta em qual disco?")
            if not parent:
                return
        name, ok = QInputDialog.getText(self, "Nova pasta", "Nome da pasta:")
        if ok and name.strip():
            if self._try(self.store.mkdir, parent, name) is not None:
                self._log(f"Pasta criada: {name.strip()}")
                self.reload()

    def _download(self, c):
        e = c.entry
        if e["is_dir"]:
            dest, _ = QFileDialog.getSaveFileName(self, "Baixar pasta como ZIP", e["name"] + ".zip", "ZIP (*.zip)")
        else:
            dest, _ = QFileDialog.getSaveFileName(self, "Salvar cópia", e["name"])
        if dest:
            self._try(self.store.export, e["rel"], dest)
            self._log(f"Baixado: {e['name']}")
            QMessageBox.information(self, "Baixar", f"Cópia salva em:\n{dest}")

    def _ensure_server(self):
        if not self.share.running:
            self.share.start(int(self.cfg.get("share_port", 8765)))

    def _share(self, c):
        e = c.entry
        rel = e["rel"]
        if not e["shared"]:
            ok = QMessageBox.question(
                self, "Compartilhar",
                f"Vou criar um link para “{e['name']}”, acessível por qualquer pessoa na sua "
                "rede local (Wi-Fi/LAN) enquanto o AndreyCloud estiver aberto.\n\nContinuar?")
            if ok != QMessageBox.StandardButton.Yes:
                return
            token = self.store.set_share(rel)
            try:
                self._ensure_server()
            except OSError as ex:
                self.store.unshare(rel)
                QMessageBox.warning(self, "AndreyCloud", str(ex))
                return
            self._log(f"Compartilhado: {e['name']}")
            first = True
        else:
            token = self.store.get_share(rel)
            self._ensure_server()
            first = False
        url = f"http://{lan_ip()}:{self.share.port}/s/{token}/{quote(e['name'] + ('.zip' if e['is_dir'] else ''))}"
        if first:
            QApplication.clipboard().setText(url)
        box = QMessageBox(self)
        box.setWindowTitle("Compartilhar")
        box.setText(f"Link de “{e['name']}”{' (copiado)' if first else ''}:\n{url}")
        box.setInformativeText("Só funciona para dispositivos na mesma rede. Para acessar de fora de casa, "
                               "use uma VPN como o Tailscale.")
        b_copy = box.addButton("Copiar link", QMessageBox.ButtonRole.AcceptRole)
        b_stop = box.addButton("Parar de compartilhar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_copy:
            QApplication.clipboard().setText(url)
        elif clicked is b_stop:
            self.store.unshare(rel)
            self._log(f"Compartilhamento encerrado: {e['name']}")
        self.reload()
        self._reselect(rel)

    def _toggle_fav(self, c):
        e = c.entry
        self.store.set_fav(e["rel"], not e["fav"])
        self.reload()
        self._reselect(e["rel"])

    def _rename(self, c):
        e = c.entry
        name, ok = QInputDialog.getText(self, "Renomear", "Novo nome:", text=e["name"])
        if ok and name.strip() and name.strip() != e["name"]:
            new_rel = self._try(self.store.rename, e["rel"], name)
            if new_rel:
                self._log(f"Renomeado: {e['name']} → {name.strip()}")
                self.reload()
                self._reselect(new_rel)

    def _move(self, c):
        e = c.entry
        folders = list(self.store.roots) + [x["rel"] for x in self.all_entries if x["is_dir"]]
        actual_parent = e["rel"].rpartition("/")[0]
        folders = [f for f in folders if f != actual_parent
                   and not (e["is_dir"] and (f == e["rel"] or f.startswith(e["rel"] + "/")))]
        if not folders:
            QMessageBox.information(self, "Mover", "Não há outra pasta de destino disponível.")
            return
        labels = {("Meus Arquivos / " + f.replace("/", " / ")): f
                  for f in sorted(folders, key=str.lower)}
        choice, ok = QInputDialog.getItem(self, "Mover", "Mover para:", list(labels), 0, False)
        if ok:
            new_rel = self._try(self.store.move, e["rel"], labels[choice])
            if new_rel:
                self._log(f"Movido: {e['name']}")
                self.reload()

    def _trash_cards(self, cards):
        if not cards:
            return
        n = len(cards)
        msg = f"Mover “{cards[0].entry['name']}” para a lixeira?" if n == 1 \
            else f"Mover {n} itens para a lixeira?"
        if QMessageBox.question(self, "Excluir", msg) != QMessageBox.StandardButton.Yes:
            return
        for c in cards:
            self._try(self.store.trash_item, c.entry["rel"])
        self._log(f"Na lixeira: {cards[0].entry['name']}" + (f" e mais {n - 1}" if n > 1 else ""))
        self.reload()

    def _restore(self, cards):
        for c in cards:
            self._try(self.store.restore, c.entry["trash_id"])
        self._log(f"Restaurado: {cards[0].entry['name']}" + (f" e mais {len(cards) - 1}" if len(cards) > 1 else ""))
        self.reload()

    def _purge(self, cards):
        n = len(cards)
        msg = f"Excluir “{cards[0].entry['name']}” para sempre? Isso não dá para desfazer." if n == 1 \
            else f"Excluir {n} itens para sempre? Isso não dá para desfazer."
        if QMessageBox.question(self, "Excluir definitivamente", msg) != QMessageBox.StandardButton.Yes:
            return
        for c in cards:
            self._try(self.store.purge, c.entry["trash_id"])
        self.reload()

    def empty_trash(self, _=False):
        if not self.trash_list:
            return
        if QMessageBox.question(self, "Esvaziar lixeira",
                                "Apagar tudo da lixeira para sempre? Isso não dá para desfazer.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._try(self.store.empty_trash)
        self._log("Lixeira esvaziada")
        self.reload()

    def _sync_selection_ui(self):
        """Mostra/esconde Excluir e Nova Pasta e ajusta o texto do Selecionar tudo."""
        n, total = len(self.selected_cards()), len(self.cards)
        self.btn_delete.label = f"Excluir ({n if n < 100 else '99+'})"
        self.btn_delete.setVisible(n > 0)
        self.btn_folder.setVisible(self.nav == "Arquivos" and n == 0)
        self.btn_selall.label = "Desmarcar tudo" if total and n == total else "Selecionar tudo"
        self.btn_selall.update()
        self.btn_delete.update()

    def _toggle_select_all(self, on=None):
        if not self.cards:
            return
        if not isinstance(on, bool):
            on = not all(c.selected for c in self.cards)
        for c in self.cards:
            c.set_selected(on)
        self.active = None  # com vários marcados, a barra flutuante de um card só atrapalha
        self._sync_selection_ui()
        self._reposition_bar()

    def _kb_select_all(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        self._toggle_select_all(True)

    def _delete_selected(self):
        sel = self.selected_cards()
        if sel:
            (self._purge if self.nav == "Lixeira" else self._trash_cards)(sel)

    def _kb_delete(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        sel = self.selected_cards()
        if sel:
            (self._purge if self.nav == "Lixeira" else self._trash_cards)(sel)

    def _act_download(self):
        if self.active:
            self._download(self.active)

    def _act_share(self):
        if self.active:
            self._share(self.active)

    def _act_fav(self):
        if self.active:
            self._toggle_fav(self.active)

    def _act_rename(self):
        if self.active and self.nav != "Lixeira":
            self._rename(self.active)


# ───────────────────────────── janela principal ─────────────────────────────
class AppFrame(QFrame):
    def __init__(self, root, cfg):
        super().__init__()
        self.root = root
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar()
        self.page = FilesPage(cfg)
        lay.addWidget(self.sidebar)
        lay.addWidget(self.page, 1)
        self.sidebar.navChanged.connect(self.page.set_nav)
        self.sidebar.toggled.connect(self.update)
        self.page.navRequest.connect(self.sidebar.select)
        self.page.usageChanged.connect(self.sidebar.storage.set_usage)
        self.sidebar.storage.set_usage(*self.page.usage)

        self.lights = []
        for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            b = TrafficLight(col, self)
            b.move(22 + i * 30, 14)
            self.lights.append(b)
        self.lights[0].clicked.connect(lambda: self.window().close())
        self.lights[1].clicked.connect(lambda: self.window().showMinimized())
        self.lights[2].clicked.connect(self._toggle_max)

    def _toggle_max(self):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 100:
            h = self.window().windowHandle()
            if h:
                h.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < 100:
            self._toggle_max()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 26, 26)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#0c1322"))
        g.setColorAt(1, QColor("#080d18"))
        p.fillPath(path, QBrush(g))
        sw = self.sidebar.width()
        p.fillRect(QRectF(0, 0, sw, h), QColor(255, 255, 255, 5))
        glow = QRadialGradient(sw + 300, 0, 520)
        glow.setColorAt(0, QColor(40, 90, 200, 28))
        glow.setColorAt(1, QColor(40, 90, 200, 0))
        p.fillRect(QRectF(sw, 0, w - sw, h), QBrush(glow))
        p.setPen(QPen(QColor("#151e33"), 1))
        p.drawLine(QPointF(sw, 0), QPointF(sw, h))
        p.drawLine(QPointF(sw, 108), QPointF(w, 108))
        p.drawLine(QPointF(16, 150), QPointF(sw - 16, 150))
        p.setClipping(False)
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0, QColor("#3d7bea"))
        bg.setColorAt(0.5, QColor("#1c3f86"))
        bg.setColorAt(1, QColor("#2a66d8"))
        p.setPen(QPen(QBrush(bg), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class Root(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.setWindowTitle("AndreyCloud")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1360, int(scr.width() * 0.97)), min(970, int(scr.height() * 0.97)))
        self.setMinimumSize(1300, 780)
        self.lay = QVBoxLayout(self)
        self.frame = AppFrame(self, cfg)
        self.lay.addWidget(self.frame)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(18, 18)
        self._margins()

    def _margins(self):
        self.lay.setContentsMargins(0, 0, 0, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._margins()
        self.grip.move(self.width() - 20, self.height() - 20)
        self.grip.raise_()


GLOBAL_QSS = """
QMenu{background:#0e1627;border:1px solid #26324d;border-radius:10px;padding:6px;color:#e4eaf7;font-size:14px;}
QMenu::item{padding:8px 22px;border-radius:6px;}
QMenu::item:selected{background:#1f5bd0;color:white;}
QMenu::separator{height:1px;background:#1f2a40;margin:5px 8px;}
QMessageBox,QInputDialog,QDialog{background:#0e1627;}
QMessageBox QLabel,QInputDialog QLabel{color:#e4eaf7;font-size:14px;}
QDialog QLineEdit{background:#0a101e;border:1px solid #26324d;border-radius:8px;padding:8px 10px;color:white;}
QDialog QPushButton{background:#2f7bff;color:white;border:none;border-radius:8px;padding:8px 20px;font-weight:600;}
QDialog QPushButton:hover{background:#4a8fff;}
QDialog QLabel{color:#e4eaf7;font-size:14px;}
QDialog QSpinBox,QDialog QComboBox{background:#0a101e;border:1px solid #26324d;border-radius:8px;padding:6px 10px;color:white;}
QComboBox QAbstractItemView{background:#0e1627;color:#e4eaf7;selection-background-color:#1f5bd0;border:1px solid #26324d;}
QCheckBox{color:#e4eaf7;font-size:14px;spacing:10px;padding:5px 0;}
QCheckBox::indicator{width:18px;height:18px;border:1px solid #59647d;border-radius:5px;background:#0a101e;}
QCheckBox::indicator:checked{background:#2f7bff;border:1px solid #74adff;}
QProgressBar{background:#0a101e;border:1px solid #26324d;border-radius:8px;text-align:center;color:white;height:16px;}
QProgressBar::chunk{background:#2f7bff;border-radius:7px;}
"""


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("AndreyCloud")
    app.setFont(mkfont(15))
    app.setStyleSheet(GLOBAL_QSS)
    cfg = load_config()
    while True:  # primeira execução (ou discos sumiram): escolher onde guardar
        probe = CloudStore(cfg.get("drives", []))
        if probe.roots:
            break
        if probe.errors:
            QMessageBox.warning(None, "AndreyCloud", "\n".join(probe.errors))
        dlg = DriveDialog(None, cfg.get("drives", []), first_run=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        cfg["drives"] = dlg.selected()
        save_config(cfg)
    w = Root(cfg)
    scr = QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.center() - w.rect().center())
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
