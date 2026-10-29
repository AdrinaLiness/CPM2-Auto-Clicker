#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АвтоКликер CPM2 — запись и воспроизведение действий мыши и клавиатуры
+ режим «ЗРЕНИЕ»: программа сама видит экран и действует по обстановке.

Возможности:
  • Запись движения мыши, кликов (ЛКМ/ПКМ/СКМ), прокрутки и нажатий клавиш
  • Воспроизведение со скоростью 0.1x–4x, числом повторов (в т.ч. бесконечно)
  • Случайное отклонение задержек (джиттер ±%) — повторения выглядят «живее»
  • Задержка перед стартом (чтобы успеть переключиться в игру) и пауза между повторами
  • Сохранение/загрузка макросов в JSON (папка macros рядом с программой)
  • Плейлист уровней: очередь макросов, каждый играется N раз подряд —
    под лимит «2 прохождения на уровень»; очередь хранится в playlist.json
  • Статистика сессии: повторы, завершённые макросы, время
  • ЗРЕНИЕ (v2.0): программа делает снимок экрана и ищет на нём
    ваши картинки-шаблоны (кнопки, экраны победы/аварии). Нашла —
    выполняет действие: клик, запуск макроса или клик+макрос.
    Так собирается полный автомат: старт уровня → макрос едет →
    победа → «Далее» → следующий уровень. Шаблоны: templates/*.png,
    правила: macros/vision.json
  • AI-ВОДИТЕЛЬ (v2.1): робот сам ВИДИТ машину и зону парковки на экране
    (по цвету, калибровка в два клика по снимку экрана) и сам ВЕДЁТ машину:
    руль, газ, тормоз, «застрял — сдаю назад», точный заезд на финише.
    Лучше всего работает с камерой «сверху» (top-down).
    Настройки: macros/driver.json
  • БИБЛИОТЕКИ (v2.2): при запуске программа сама проверяет нужные
    библиотеки (pynput, numpy, opencv-python, mss) и сама устанавливает
    недостающее через pip — вручную ничего ставить не обязательно.
    Обновление — кнопкой в карточке «Библиотеки» или автоматически
    при запуске (галочка). Настройки: macros/libs.json
  • Глобальные горячие клавиши (работают, даже когда окно свернуто):
      F8  — запустить / остановить AI-водителя
      F9  — начать / остановить запись
      F10 — начать воспроизведение
      F11 — запустить / остановить «Зрение»
      F12 — экстренный стоп всего

Требуется: Python 3.9+. Библиотеки (pynput, numpy, opencv-python, mss)
программа установит сама при первом запуске; вручную:
    pip install pynput opencv-python mss numpy
Запуск:    python autoclicker_cpm2.py
"""

import base64
import importlib
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    from pynput import mouse, keyboard
    from pynput.keyboard import Key, KeyCode
    PYNPUT_OK = True
    PYNPUT_ERROR = ""
except Exception as _e:  # pynput не установлен
    PYNPUT_OK = False
    PYNPUT_ERROR = str(_e)

try:
    import numpy as np
    NUMPY_OK = True
except Exception:
    NUMPY_OK = False

try:
    import cv2
    CV_OK = True
except Exception:
    CV_OK = False

try:
    import mss
    MSS_OK = True
except Exception:
    MSS_OK = False

# ------------------------------------------------- библиотеки (v2.2)
# Программа проверяет эти библиотеки при запуске, сама ставит
# недостающее через pip и умеет их обновлять.
REQUIRED_LIBS = (
    # (имя для import, имя пакета в pip, обязательная — без неё нет записи/воспроизведения)
    ("pynput", "pynput", True),
    ("numpy", "numpy", False),
    ("cv2", "opencv-python", False),
    ("mss", "mss", False),
)
MANUAL_PIP_CMD = "pip install pynput opencv-python mss numpy"


def _pkg_version(pip_name):
    try:
        from importlib import metadata as _md
        return _md.version(pip_name)
    except Exception:
        return ""


def lib_status():
    """Проверка всех нужных библиотек.
    → [{"import": "cv2", "pip": "opencv-python", "ok": True,
        "version": "4.13.0", "core": False}, ...]"""
    out = []
    for imp, pip_name, core in REQUIRED_LIBS:
        try:
            importlib.import_module(imp)
            ok = True
        except Exception:
            ok = False
        out.append({"import": imp, "pip": pip_name, "ok": ok,
                    "version": _pkg_version(pip_name) if ok else "",
                    "core": core})
    return out


def pick_missing(status):
    """pip-имена тех библиотек, которых нет (мусор на входе → [])."""
    if not isinstance(status, (list, tuple)):
        return []
    out = []
    for s in status:
        if isinstance(s, dict) and not s.get("ok") and s.get("pip"):
            out.append(s["pip"])
    return out


def libs_report(status=None):
    """Одна строка про все библиотеки — для карточки «Библиотеки».
    Пример:  pynput 1 ✓   numpy 2 ✓   opencv-python ✗   mss 10 ✓"""
    st = lib_status() if status is None else status
    parts = []
    for s in st:
        if s.get("ok"):
            ver = str(s.get("version", "") or "").split(".")
            major = ver[0] if ver and ver[0] else ""
            parts.append(("%s %s ✓" % (s.get("pip", "?"), major)) if major
                         else "%s ✓" % s.get("pip", "?"))
        else:
            parts.append("%s ✗" % s.get("pip", "?"))
    return "   ".join(parts)


def build_pip_cmd(pips, upgrade=False):
    """Аргументы для pip: install (опционально --upgrade) + имена пакетов.
    Пустые и мусорные имена отбрасываются."""
    args = ["install"]
    if upgrade:
        args.append("--upgrade")
    for p in pips or ():
        if isinstance(p, str) and p.strip():
            args.append(p.strip())
    return args


def run_pip(args, on_line=None, popen=None):
    """Запускает `python -m pip <args>`, построчно отдаёт вывод в on_line.
    → True, если код возврата 0. Исключений не бросает."""
    if popen is None:
        popen = subprocess.Popen
    cmd = [sys.executable, "-m", "pip"] + [str(a) for a in args]
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  text=True, encoding="utf-8", errors="replace", bufsize=1)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = popen(cmd, **kwargs)
    except Exception as _e:
        if on_line:
            on_line("[ошибка запуска pip] %s" % _e)
            on_line("Попробуйте вручную:  %s" % MANUAL_PIP_CMD)
        return False
    try:
        for line in proc.stdout:
            if on_line:
                on_line(str(line).rstrip())
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
    try:
        rc = proc.wait()
    except Exception:
        rc = -1
    return rc == 0


def normalize_libs_cfg(data):
    """libs.json → {"auto_install": bool, "auto_update": bool}."""
    d = data if isinstance(data, dict) else {}

    def _flag(key, dflt):
        v = d.get(key, dflt)
        if isinstance(v, str):
            v = v.strip().lower() in ("1", "true", "yes", "on", "да")
        return bool(v)

    return {"auto_install": _flag("auto_install", True),
            "auto_update": _flag("auto_update", False)}


def libs_cfg_path():
    return os.path.join(macro_dir(), "libs.json")


def read_json_safe(path):
    """Читает JSON-файл; любая ошибка → {} (не бросает исключений)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _import_libs():
    """Повторный импорт библиотек после их установки: обновляет сами
    модули и флаги PYNPUT_OK / NUMPY_OK / CV_OK / MSS_OK."""
    global PYNPUT_OK, PYNPUT_ERROR, NUMPY_OK, CV_OK, MSS_OK
    global np, cv2, mss, mouse, keyboard, Key, KeyCode
    try:
        import numpy as _np
        np, NUMPY_OK = _np, True
    except Exception:
        NUMPY_OK = False
    try:
        import cv2 as _cv
        cv2, CV_OK = _cv, True
    except Exception:
        CV_OK = False
    try:
        import mss as _mss
        mss, MSS_OK = _mss, True
    except Exception:
        MSS_OK = False
    try:
        from pynput import mouse as _mouse, keyboard as _kb
        from pynput.keyboard import Key as _Key, KeyCode as _KeyCode
        mouse, keyboard, Key, KeyCode = _mouse, _kb, _Key, _KeyCode
        PYNPUT_OK, PYNPUT_ERROR = True, ""
    except Exception as _e:
        PYNPUT_OK, PYNPUT_ERROR = False, str(_e)

APP_NAME = "АвтоКликер CPM2"
VERSION = "2.2"

# ----------------------------------------------------------------- палитра
BG      = "#141519"   # фон окна
PANEL   = "#1d1e24"   # фон карточек
PANEL2  = "#24252d"   # фон полей
FG      = "#ececf1"   # основной текст
MUTED   = "#9b9ba6"   # вторичный текст
BORDER  = "#31323c"
RED     = "#ff6b6f"
GREEN   = "#3dd68c"
AMBER   = "#ffb224"
BLUE    = "#5b9cf6"

BTN_BG      = "#2a2b34"
BTN_ACTIVE  = "#383945"
REC_BG      = "#8c2f33"
REC_ACTIVE  = "#b23b40"
PLAY_BG     = "#1f6f47"
PLAY_ACTIVE = "#268557"
STOP_BG     = "#4a4b57"
STOP_ACTIVE = "#5a5b68"

MAX_TREE_ROWS = 2000
TYPE_RUS = {"move": "Мышь", "click": "Клик", "scroll": "Скролл", "key": "Клавиша"}
BUTTON_RUS = {"left": "ЛКМ", "right": "ПКМ", "middle": "СКМ"}

# ----------------------------------------------------------------- зрение
VISION_ACTIONS = ("click", "macro", "click_macro", "notify")
ACTION_RUS = {
    "click": "Кликнуть",
    "macro": "Запустить макрос",
    "click_macro": "Клик + макрос",
    "notify": "Только показать",
}
VISION_SCALES_MULTI = (0.75, 0.85, 1.0, 1.15, 1.3)


def base_dir():
    """Папка программы (корректно и для .py, и для .exe собранного PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def macro_dir():
    return os.path.join(base_dir(), "macros")


def template_dir():
    return os.path.join(base_dir(), "templates")


def vision_missing():
    """Список библиотек, без которых режим «Зрение» не заработает."""
    parts = []
    if not NUMPY_OK:
        parts.append("numpy")
    if not CV_OK:
        parts.append("opencv-python")
    if not MSS_OK:
        parts.append("mss")
    if not PYNPUT_OK:
        parts.append("pynput")
    return parts


def scale_list(multiscale):
    """Масштабы поиска шаблона: обычный или «разных размеров»."""
    return VISION_SCALES_MULTI if multiscale else (1.0,)


def normalize_rules(data):
    """vision.json / список → валидные правила зрения.
    Правило: имя, картинка-шаблон, действие, макрос, порог, кулдаун,
    задержка, смещение клика, включённость. Мусор отбрасывается."""
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        image = it.get("image")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(image, str) or not image.strip():
            continue
        action = it.get("action")
        if action not in VISION_ACTIONS:
            action = "click"
        macro = it.get("macro")
        macro = os.path.basename(macro.strip()) if isinstance(macro, str) else ""

        def _num(key, default, lo, hi, _it=it):
            try:
                v = float(_it.get(key, default))
            except (ValueError, TypeError):
                v = float(default)
            return min(hi, max(lo, v))

        out.append({
            "name": name.strip(),
            "image": os.path.basename(image.strip()),
            "action": action,
            "macro": macro,
            "threshold": _num("threshold", 0.85, 0.05, 0.99),
            "cooldown": _num("cooldown", 2.0, 0.0, 600.0),
            "delay": _num("delay", 0.0, 0.0, 60.0),
            "dx": int(_num("dx", 0, -5000, 5000)),
            "dy": int(_num("dy", 0, -5000, 5000)),
            "enabled": bool(it.get("enabled", True)),
        })
    return out


def find_template(screen_bgr, tmpl_bgr, threshold, scales=(1.0,)):
    """Ищет картинку-шаблон на снимке экрана.
    Возвращает (score, x, y, w, h) в координатах снимка либо None.
    Перебирает масштабы и берёт лучшее совпадение (score 0..1)."""
    if screen_bgr is None or tmpl_bgr is None:
        return None
    try:
        g1 = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
        t0 = cv2.cvtColor(tmpl_bgr, cv2.COLOR_BGR2GRAY)
    except Exception:
        return None
    gh, gw = g1.shape[:2]
    th0, tw0 = t0.shape[:2]
    if th0 < 4 or tw0 < 4 or gh < 4 or gw < 4:
        return None
    if float(t0.std()) < 2.0:          # однотонный шаблон ничего не находит
        return None
    best = None
    for s in scales:
        try:
            if abs(s - 1.0) < 1e-6:
                t = t0
            else:
                t = cv2.resize(t0, (max(2, int(round(tw0 * s))),
                                    max(2, int(round(th0 * s)))))
            th, tw = t.shape[:2]
            if th > gh or tw > gw or th < 3 or tw < 3:
                continue
            res = cv2.matchTemplate(g1, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx != mx:               # NaN (пустой результат)
                continue
            if best is None or mx > best[0]:
                best = (float(mx), int(loc[0]), int(loc[1]), int(tw), int(th))
        except Exception:
            continue
    if best and best[0] >= threshold:
        return best
    return None


def rule_allowed(rule, busy, clicks_during_play, now, last_exec):
    """Можно ли выполнять правило прямо сейчас: приоритеты, занятость,
    кулдаун. busy = идёт запись/воспроизведение макроса."""
    act = rule.get("action")
    if busy:
        if act in ("macro", "click_macro"):
            return False
        if act == "click" and not clicks_during_play:
            return False
    last = last_exec.get(rule.get("name"))
    if last is None:
        return True
    return (now - last) >= float(rule.get("cooldown", 0.0))


def to_global(x, y, area, dx=0, dy=0):
    """Точка в координатах области захвата → глобальные координаты экрана
    (плюс смещение клика dx/dy от центра шаблона)."""
    ox = int(area.get("left", 0)) if isinstance(area, dict) else 0
    oy = int(area.get("top", 0)) if isinstance(area, dict) else 0
    return int(x) + ox + int(dx), int(y) + oy + int(dy)


# =================================================== AI-водитель: математика
def wrap_angle(deg):
    """Нормализация угла в диапазон [-180, 180)."""
    return (float(deg) + 180.0) % 360.0 - 180.0


def angle_diff(target_deg, from_deg):
    """Знаковая разница: на сколько градусов повернуть от from к target.
    Плюс — по часовой стрелке на экране (y растёт вниз)."""
    return wrap_angle(target_deg - from_deg)


def bearing_deg(cx, cy, tx, ty):
    """Азимут на цель в экранных координатах: 0° — вправо, 90° — вниз."""
    return math.degrees(math.atan2(float(ty) - float(cy),
                                   float(tx) - float(cx)))


def rect_axis_deg(box):
    """Угол длинной оси повёрнутого прямоугольника (4 угла от cv2.boxPoints),
    приведённый к [-90, 90). Даёт ЛИНИЮ курса машины, но не направление
    «перед/зад» — его выбирает pick_heading()."""
    pts = [(float(p[0]), float(p[1])) for p in box]
    if len(pts) != 4:
        return 0.0
    edges = []
    for i in range(4):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % 4]
        edges.append((x1 - x0, y1 - y0))
    ex, ey = max(edges, key=lambda e: e[0] * e[0] + e[1] * e[1])
    if ex == 0.0 and ey == 0.0:
        return 0.0
    a = math.degrees(math.atan2(ey, ex))
    if a >= 90.0:
        a -= 180.0
    elif a < -90.0:
        a += 180.0
    return a


def pick_heading(axis_deg, motion_deg, moving, last_heading, toward_deg,
                 invert=False):
    """Выбирает направление курса (куда смотрит «перед» машины).
    Едет — курс по факту движения; стоит с известным курсом — держим его;
    первый кадр — разворачиваем ось в сторону цели (если угадали неверно,
    помогает галочка «Инвертировать курс»)."""
    if moving:
        h = float(motion_deg)
    elif last_heading is not None:
        h = float(last_heading)
        if abs(angle_diff(axis_deg, h)) > 90.0:
            h = wrap_angle(h + 180.0)
    else:
        h = float(axis_deg)
        if abs(angle_diff(toward_deg, h)) > 90.0:
            h = wrap_angle(h + 180.0)
    if invert:
        h = wrap_angle(h + 180.0)
    return wrap_angle(h)


def hsv_pairs(center_h, hue_tol):
    """Диапазон(ы) тона OpenCV (0–179) с заворотом через 0/180.
    Возвращает список пар (lower_h, upper_h)."""
    h = int(round(float(center_h))) % 180
    t = int(max(0, min(89, hue_tol)))
    lo, hi = h - t, h + t
    if lo < 0:
        return [(0, hi), (180 + lo, 179)]
    if hi > 179:
        return [(lo, 179), (0, hi - 180)]
    return [(lo, hi)]


def sample_patch_hsv(bgr, x, y, radius=5):
    """Медианный HSV пятна вокруг точки снимка (устойчиво к шуму сжатия)."""
    if bgr is None or not CV_OK or not NUMPY_OK:
        return None
    h, w = bgr.shape[:2]
    x0, x1 = max(0, int(x) - radius), min(w, int(x) + radius + 1)
    y0, y1 = max(0, int(y) - radius), min(h, int(y) + radius + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    try:
        patch = bgr[y0:y1, x0:x1].reshape(-1, 1, 3)
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        med = np.median(hsv, axis=0)
        return [int(med[0]), int(med[1]), int(med[2])]
    except Exception:
        return None


def find_color_blob(hsv, center_hsv, hue_tol, s_min, v_min, min_area, max_area):
    """Самый крупный контур заданного цвета на HSV-кадре.
    min_area / max_area — в пикселях (защита от шума и «заливки всего экрана»).
    Возвращает dict {cx, cy, w, h, area, axis} либо None."""
    if hsv is None or center_hsv is None or not CV_OK or not NUMPY_OK:
        return None
    try:
        ch, cs, cvv = center_hsv
        s_lo = max(0, int(s_min))
        v_lo = max(0, int(v_min))
        mask = None
        for lo_h, hi_h in hsv_pairs(ch, hue_tol):
            lower = np.array([lo_h, s_lo, v_lo], dtype=np.uint8)
            upper = np.array([hi_h, 255, 255], dtype=np.uint8)
            m = cv2.inRange(hsv, lower, upper)
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        if mask is None:
            return None
        k_small = np.ones((3, 3), np.uint8)
        k_big = np.ones((9, 9), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_small)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_big)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            a = float(cv2.contourArea(c))
            if a < max(30.0, float(min_area)) or a > float(max_area):
                continue
            if best is None or a > best[0]:
                best = (a, c)
        if best is None:
            return None
        rect = cv2.minAreaRect(best[1])
        (cx, cy), (rw, rh), _ang = rect
        return {"cx": float(cx), "cy": float(cy),
                "w": float(rw), "h": float(rh),
                "area": float(best[0]), "axis": rect_axis_deg(cv2.boxPoints(rect))}
    except Exception:
        return None


# ------------------------------------------------ решение AI-водителя (шаг)
DRIVER_STUCK_SPEED = 12.0      # px/s — медленнее этого считаем «стоим»
DRIVER_MOVE_SPEED = 20.0       # px/s — быстрее этого считаем «едем»
DRIVER_MODE_RUS = {"search": "поиск", "drive": "еду", "final": "заезд",
                   "reverse": "назад", "done": "готово", "lost": "потерял"}


def drive_step(obs, cfg, st):
    """Один такт «мозга» AI-водителя. Чистая функция (без cv2/экрана) —
    легко тестировать и настраивать.

    obs: {"car": dict|None, "target": dict|None, "frame_w", "frame_h",
          "dt", "speed" (px/s мгновенная), "motion_deg", "moving"}
    cfg: пороги/настройки (stop_dist_frac, steer_deadzone, max_speed_px,
          creep_speed, stuck_time, recover_time, lost_time, invert_heading)
    st:  изменяемое состояние между тактами (mode, speed, heading, pos,
          stuck_t, recover_t, lost_t, want_move, err)

    Возвращает {"steer": -1|0|+1, "throttle": -1|0|+1, "mode", "done",
                "msg", "err", "dist_frac"}.
    steer +1 = вправо (клавиша D), throttle +1 = вперёд (W), -1 = назад (S).
    """
    car = obs.get("car")
    tgt = obs.get("target")
    fw = max(1, int(obs.get("frame_w", 1) or 1))
    fh = max(1, int(obs.get("frame_h", 1) or 1))

    def _f(v, default=0.0):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    dt = min(0.5, max(0.01, _f(obs.get("dt"), 0.1)))
    raw_speed = _f(obs.get("speed"))

    def result(steer, throttle, mode, done, msg, err, dist_frac):
        st["mode"] = mode
        st["want_move"] = (mode in ("drive", "final") and throttle > 0)
        return {"steer": steer, "throttle": throttle, "mode": mode,
                "done": bool(done), "msg": msg, "err": float(err),
                "dist_frac": float(dist_frac)}

    if car is None or tgt is None:
        st["lost_t"] = float(st.get("lost_t", 0.0)) + dt
        if car is None and tgt is None:
            miss = "машина и цель"
        elif car is None:
            miss = "машина"
        else:
            miss = "цель (зона парковки)"
        if st["lost_t"] > float(cfg.get("lost_time", 3.0)):
            return result(0, 0, "lost", True,
                          "Не вижу %s дольше %d с — стоп" % (miss, int(st["lost_t"])),
                          0.0, 1.0)
        return result(0, 0, "search", False, "Ищу %s…" % miss, 0.0, 1.0)

    st["lost_t"] = 0.0
    try:
        cx = float(car["cx"])
        cy = float(car["cy"])
        tx = float(tgt["cx"])
        ty = float(tgt["cy"])
    except (ValueError, TypeError, KeyError):
        st["lost_t"] = 99.0
        return result(0, 0, "lost", True, "Битые данные наблюдения — стоп",
                      0.0, 1.0)
    diag = math.hypot(fw, fh) or 1.0
    dist = math.hypot(tx - cx, ty - cy)
    dist_frac = dist / diag
    toward = bearing_deg(cx, cy, tx, ty)

    # сглаженная скорость по смещению центра машины
    prev = st.get("pos")
    inst = raw_speed
    if prev is not None and obs.get("moving") is not None:
        inst = math.hypot(cx - prev[0], cy - prev[1]) / dt
    st["speed"] = 0.6 * float(st.get("speed", 0.0)) + 0.4 * inst
    speed_s = float(st["speed"])
    st["pos"] = (cx, cy)

    heading = pick_heading(_f(car.get("axis"), 0.0),
                           _f(obs.get("motion_deg"), toward),
                           bool(obs.get("moving", False)),
                           st.get("heading"), toward,
                           bool(cfg.get("invert_heading", False)))
    st["heading"] = heading
    err = angle_diff(toward, heading)
    st["err"] = err

    stop_frac = float(cfg.get("stop_dist_frac", 0.04))
    dead = float(cfg.get("steer_deadzone", 8.0))
    max_sp = float(cfg.get("max_speed_px", 450.0))
    creep = float(cfg.get("creep_speed", 80.0))
    stuck_sp = float(cfg.get("stuck_speed", DRIVER_STUCK_SPEED))

    # --- застряли? газуем, а машина почти не движется ---
    if st.get("mode") in ("drive", "final") and st.get("want_move") \
            and speed_s < stuck_sp:
        st["stuck_t"] = float(st.get("stuck_t", 0.0)) + dt
    else:
        st["stuck_t"] = 0.0

    if st.get("mode") == "reverse" or \
            st["stuck_t"] > float(cfg.get("stuck_time", 2.0)):
        if st.get("mode") != "reverse":
            st["mode"] = "reverse"
            st["recover_t"] = float(cfg.get("recover_time", 1.2))
            st["stuck_t"] = 0.0
        st["recover_t"] = float(st.get("recover_t", 0.0)) - dt
        if st["recover_t"] <= 0.0:
            st["mode"] = "drive"
            st["recover_t"] = 0.0
            return result(0, 0, "drive", False, "Выхожу из заноса", err, dist_frac)
        sgn = 1.0 if err >= 0.0 else -1.0     # задним ходом руль зеркален
        steer = int(-sgn) if abs(err) > dead else 0
        return result(steer, -1, "reverse", False, "Сдаю назад…", err, dist_frac)

    # --- успех: центр машины на цели и скорость упала ---
    if dist_frac <= stop_frac and speed_s < max(stuck_sp * 2.0, 30.0):
        return result(0, 0, "done", True, "Парковка завершена!", err, dist_frac)

    # --- финальный заезд: близко, нужны мелкие движения ---
    if dist_frac <= stop_frac * 2.5:
        if abs(err) > 100.0:
            return result(1 if err < 0 else -1, -1, "final", False,
                          "Разворот на месте…", err, dist_frac)
        steer = 1 if err > dead * 2.0 else (-1 if err < -dead * 2.0 else 0)
        throttle = 1 if (dist_frac > stop_frac * 0.7 and speed_s < creep) else 0
        return result(steer, throttle, "final", False, "Доезжаю точно…",
                      err, dist_frac)

    # --- обычная езда к цели ---
    steer = 1 if err > dead else (-1 if err < -dead else 0)
    aligned = abs(err) < 65.0
    throttle = 1 if (aligned and speed_s < max_sp) else 0
    return result(steer, throttle, "drive", False,
                  "" if aligned else "Доворачиваю…", err, dist_frac)


# ------------------------------------------------------- сериализация клавиш
def key_to_dict(key):
    """pynput-клавиша → JSON-словарь."""
    if isinstance(key, Key):
        return {"special": key.name}
    d = {}
    ch = getattr(key, "char", None)
    vk = getattr(key, "vk", None)
    if ch is not None:
        d["char"] = ch
    if vk is not None:
        d["vk"] = vk
    return d or {"char": "?"}


def dict_to_key(d):
    """JSON-словарь → pynput-клавиша (или None, если восстановить нельзя)."""
    if not isinstance(d, dict):
        return None
    sp = d.get("special")
    if sp:
        try:
            return Key[sp]
        except KeyError:
            return None
    vk = d.get("vk")
    ch = d.get("char")
    if vk is not None:
        try:
            return KeyCode(vk=vk, char=ch)
        except Exception:
            pass
    if ch:
        try:
            return KeyCode.from_char(ch)
        except Exception:
            return None
    return None


def key_display(d):
    """Короткое текстовое представление клавиши для таблицы событий."""
    if not isinstance(d, dict):
        return "?"
    if d.get("special"):
        return "<%s>" % d["special"]
    ch = d.get("char")
    if ch and ch.strip():
        return "'%s'" % ch
    if d.get("vk") is not None:
        return "vk%s" % d["vk"]
    return "?"


def normalize_queue(data):
    """playlist.json / список → валидная очередь [{"file": str, "repeats": int >= 1}]."""
    if isinstance(data, dict):
        items = data.get("jobs")
    elif isinstance(data, list):
        items = data
    else:
        items = None
    out = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            f = it.get("file")
            if not isinstance(f, str) or not f.strip():
                continue
            try:
                reps = int(float(it.get("repeats", 2)))
            except (ValueError, TypeError):
                reps = 2
            out.append({"file": os.path.basename(f.strip()), "repeats": max(1, reps)})
    return out


def _fmt_duration(sec):
    """Секунды → «1ч 02м 05с» / «2м 05с» / «45с»."""
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dч %02dм %02dс" % (h, m, s)
    if m:
        return "%dм %02dс" % (m, s)
    return "%dс" % s


# ----------------------------------------------------------------- приложение
class App:
    def __init__(self, root):
        self.root = root
        root.title("%s v%s" % (APP_NAME, VERSION))
        root.configure(bg=BG)
        root.geometry("740x1360")
        root.minsize(660, 1200)

        # --- состояние ---
        self.events = []
        self.stats = {"move": 0, "click": 0, "scroll": 0, "key": 0}
        self.ev_lock = threading.Lock()
        self.recording = False
        self.playing = False
        self.t0 = 0.0
        self.duration = 0.0
        self.stop_flag = threading.Event()
        self.play_prog = {}             # прогресс воспроизведения (словарь)
        self._rows_shown = 0
        self._pressed_keys = set()
        self.macro_name = "(новый макрос)"

        # плейлист и статистика сессии
        self.queue_jobs = []            # [{"file": имя.json, "repeats": N}]
        self.sess_started = None
        self.sess_repeats = 0
        self.sess_jobs = 0

        # переключатели записи (дублируются обычными атрибутами для потоков)
        self.rec_moves = True
        self.rec_clicks = True
        self.rec_keys = True
        self.rec_scroll = False

        # --- режим «Зрение» (v2.0) ---
        self.vision_on = False            # работает ли поток зрения
        self.vision_rules = []            # [{name,image,action,macro,...}]
        self.vision_cfg = {"interval": 0.5, "monitor": 1, "multiscale": False,
                           "clicks_during_play": True, "preview": False, "area": None}
        self.vision_state = {}            # последний кадр: найденное, счётчики, превью
        self.vision_lock = threading.Lock()
        self._vision_last_exec = {}       # имя правила → время последнего срабатывания
        self._tmpl_cache = {}             # имя шаблона → (картинка, mtime)
        self.preview_win = None
        self.preview_canvas = None
        self._preview_img = None
        self._preview_ts = 0.0
        self.load_vision_cfg()

        # --- AI-водитель (v2.1) ---
        self.driver_on = False            # работает ли поток водителя
        self.driver_state = {}            # последний такт: режим, ошибки, превью
        self.drv_prev_win = None
        self.drv_prev_canvas = None
        self._drv_prev_img = None
        self._drv_prev_ts = 0.0
        self._driver_held = set()         # зажатые водителем клавиши-действия
        self.load_driver_cfg()

        # --- библиотеки (v2.2) ---
        self.libs_cfg = normalize_libs_cfg(read_json_safe(libs_cfg_path()))
        self.libs_log_q = queue.Queue()   # вывод pip из фонового потока
        self._libs_busy = False
        self._pynput_at_start = PYNPUT_OK

        self.cmd_q = queue.Queue()
        self.status_q = queue.Queue()

        if PYNPUT_OK:
            self.mouse_ctrl = mouse.Controller()
            self.kb_ctrl = keyboard.Controller()
            self._start_listeners()

        self._build_style()
        self._build_ui()
        self._poll()

    # ------------------------------------------------------------ слушатели
    def _start_listeners(self):
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

        self._kb_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._kb_listener.daemon = True
        self._kb_listener.start()

    def _now(self):
        return time.perf_counter() - self.t0

    def _add_event(self, ev):
        with self.ev_lock:
            self.events.append(ev)
            self.stats[ev["type"]] = self.stats.get(ev["type"], 0) + 1

    def _on_move(self, x, y):
        if not self.recording or not self.rec_moves:
            return
        with self.ev_lock:
            last = self.events[-1] if self.events else None
            if last is not None and last.get("type") == "move" \
                    and last.get("x") == x and last.get("y") == y:
                return  # курсор не сдвинулся — не пишем дубль
        self._add_event({"type": "move", "t": round(self._now(), 4),
                         "x": int(x), "y": int(y)})

    def _on_click(self, x, y, button, pressed):
        if not self.recording or not self.rec_clicks:
            return
        self._add_event({"type": "click", "t": round(self._now(), 4),
                         "x": int(x), "y": int(y),
                         "button": getattr(button, "name", "left"),
                         "pressed": bool(pressed)})

    def _on_scroll(self, x, y, dx, dy):
        if not self.recording or not self.rec_scroll:
            return
        self._add_event({"type": "scroll", "t": round(self._now(), 4),
                         "dx": int(dx), "dy": int(dy)})

    def _on_press(self, key):
        try:
            # горячие клавиши никогда не попадают в макрос
            if key == Key.f9:
                self.cmd_q.put("toggle_record")
                return
            if key == Key.f10:
                self.cmd_q.put("start_play")
                return
            if key == Key.f11:
                self.cmd_q.put("toggle_vision")
                return
            if key == Key.f8:
                self.cmd_q.put("toggle_driver")
                return
            if key == Key.f12:
                self.request_stop()
                return
            if self.recording and self.rec_keys:
                k = key_to_dict(key)
                sig = json.dumps(k, sort_keys=True)
                with self.ev_lock:
                    if sig in self._pressed_keys:
                        return  # автоповтор зажатой клавиши не пишем
                    self._pressed_keys.add(sig)
                self._add_event({"type": "key", "t": round(self._now(), 4),
                                 "action": "press", "key": k})
        except Exception:
            pass

    def _on_release(self, key):
        try:
            if key in (Key.f9, Key.f10, Key.f11, Key.f12, Key.f8):
                return
            if self.recording and self.rec_keys:
                k = key_to_dict(key)
                sig = json.dumps(k, sort_keys=True)
                with self.ev_lock:
                    self._pressed_keys.discard(sig)
                self._add_event({"type": "key", "t": round(self._now(), 4),
                                 "action": "release", "key": k})
        except Exception:
            pass

    # -------------------------------------------------------------- запись
    def toggle_record(self):
        if self.driver_on:
            self.q_status("Остановите AI-водителя (F8) перед записью", AMBER)
            return
        if self.vision_on:
            self.q_status("Остановите зрение (F11) перед записью", AMBER)
            return
        if self.playing:
            self.q_status("Сначала остановите воспроизведение (F12)", AMBER)
            return
        if self.recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        with self.ev_lock:
            self.events = []
            self.stats = {"move": 0, "click": 0, "scroll": 0, "key": 0}
            self._pressed_keys.clear()
        self.duration = 0.0
        self.t0 = time.perf_counter()
        self.recording = True
        self._rows_shown = 0
        self._clear_tree()
        self.macro_name = "(новый макрос)"
        self.name_var.set(self.macro_name)
        self.prog_var.set("—")
        self.q_status("● ИДЁТ ЗАПИСЬ — нажмите F9, чтобы остановить", RED)

    def _stop_record(self):
        self.recording = False
        self.duration = time.perf_counter() - self.t0
        with self.ev_lock:
            n = len(self.events)
        self.q_status("Запись остановлена: %d событий за %.1f с" % (n, self.duration), FG)

    def request_stop(self):
        """F12 — экстренный стоп записи/воспроизведения/зрения/водителя."""
        self.vision_on = False
        self.driver_on = False
        self._driver_release_now()
        self.stop_flag.set()
        if self.recording:
            self.cmd_q.put("toggle_record")

    # -------------------------------------------------------- воспроизведение
    def start_play(self):
        if self.driver_on:
            self.q_status("Остановите AI-водителя (F8) перед воспроизведением", AMBER)
            return
        if self.recording:
            self.q_status("Идёт запись — сначала остановите её (F9)", AMBER)
            return
        if self.playing:
            return
        try:
            speed = float(self.speed_var.get())
            jitter = int(float(self.jitter_var.get()))
            start_delay = float(self.delay_var.get())
            pause = float(self.pause_var.get())
            use_q = bool(self.use_queue_var.get())
        except (ValueError, TypeError):
            self.q_status("Проверьте параметры воспроизведения", AMBER)
            return
        speed = min(4.0, max(0.1, speed))
        jitter = min(50, max(0, jitter))
        start_delay = min(30.0, max(0.0, start_delay))
        pause = min(60.0, max(0.0, pause))

        if use_q and self.queue_jobs:
            jobs, missing = self._load_jobs_events(self.queue_jobs)
            if missing:
                self.q_status("Файлы не найдены (пропущены): %s" % ", ".join(missing), AMBER)
            if not jobs:
                return
            mode_text = "плейлист из %d макросов" % len(jobs)
            loop = bool(self.q_loop_var.get())
        else:
            if use_q and not self.queue_jobs:
                self.q_status("Очередь пуста — играю текущий макрос", AMBER)
            with self.ev_lock:
                events = list(self.events)
            if not events:
                self.q_status("Макрос пуст — сначала запишите действия (F9) или загрузите профиль", AMBER)
                return
            try:
                repeats = int(float(self.repeats_var.get()))
            except (ValueError, TypeError):
                repeats = 1
            repeats = max(0, repeats)          # 0 = бесконечно
            jobs = [{"name": self.macro_name, "events": events, "repeats": repeats}]
            loop = False
            mode_text = "макрос"

        self._launch_playback(jobs, speed, jitter, start_delay, pause, loop, mode_text)

    def _launch_playback(self, jobs, speed, jitter, start_delay, pause, loop, mode_text):
        """Общий запуск потока воспроизведения (из F10 и из режима «Зрение»)."""
        self.stop_flag.clear()
        self.playing = True
        self.sess_started = time.time()
        self.sess_repeats = 0
        self.sess_jobs = 0
        self.play_prog = {"jobs": len(jobs), "idx": 0, "name": jobs[0]["name"],
                          "rep": 0, "reps": jobs[0]["repeats"], "done": 0, "total": 0}
        threading.Thread(target=self._play_worker, daemon=True,
                         args=(jobs, speed, jitter, start_delay, pause, loop)).start()
        self.q_status("▶ Старт: %s" % mode_text, GREEN)

    def vision_play_macro(self, fname):
        """Зрение нашло совпадение и запускает макрос (без задержки старта)."""
        if self.playing or self.recording or not self.vision_on:
            return
        loaded, _missing = self._load_jobs_events(
            [{"file": os.path.basename(str(fname)), "repeats": 1}])
        if not loaded:
            self.q_status("Зрение: макрос не найден или пуст: %s" % fname, RED)
            return
        try:
            speed = min(4.0, max(0.1, float(self.speed_var.get())))
        except (ValueError, TypeError):
            speed = 1.0
        try:
            jitter = min(50, max(0, int(float(self.jitter_var.get()))))
        except (ValueError, TypeError):
            jitter = 0
        try:
            pause = min(60.0, max(0.0, float(self.pause_var.get())))
        except (ValueError, TypeError):
            pause = 1.0
        self._launch_playback(loaded, speed, jitter, 0.0, pause, False,
                              "макрос по зрению: %s" % loaded[0]["name"])

    def _sleep_stop(self, seconds):
        """Сон, который прерывается флагом stop_flag (точность ~2 мс)."""
        if seconds <= 0:
            return
        end = time.perf_counter() + seconds
        while not self.stop_flag.is_set():
            remain = end - time.perf_counter()
            if remain <= 0:
                return
            if remain > 0.05:
                time.sleep(0.025)
            elif remain > 0.004:
                time.sleep(remain - 0.002)
            else:
                time.sleep(0.001)

    def _execute(self, ev):
        et = ev.get("type")
        if et == "move":
            self.mouse_ctrl.position = (int(ev.get("x", 0)), int(ev.get("y", 0)))
        elif et == "click":
            name = ev.get("button", "left")
            try:
                btn = mouse.Button[name]
            except KeyError:
                btn = mouse.Button.left
            if ev.get("pressed", True):
                self.mouse_ctrl.press(btn)
            else:
                self.mouse_ctrl.release(btn)
        elif et == "scroll":
            self.mouse_ctrl.scroll(int(ev.get("dx", 0)), int(ev.get("dy", 0)))
        elif et == "key":
            k = dict_to_key(ev.get("key") or {})
            if k is None:
                return
            if ev.get("action", "press") == "press":
                self.kb_ctrl.press(k)
            else:
                self.kb_ctrl.release(k)

    def _play_worker(self, jobs, speed, jitter, start_delay, pause, loop):
        n_jobs = len(jobs)
        try:
            if start_delay > 0:
                end = time.perf_counter() + start_delay
                while not self.stop_flag.is_set():
                    remain = end - time.perf_counter()
                    if remain <= 0:
                        break
                    self.q_status("▶ Старт через %.0f с… переключитесь в игру!" % max(1.0, remain), GREEN)
                    time.sleep(0.2)
            while True:  # круги плейлиста (если включено «по кругу»)
                for ji, job in enumerate(jobs):
                    events = job["events"]
                    reps = job["repeats"]
                    total = len(events)
                    rep = 0
                    while True:
                        if self.stop_flag.is_set():
                            return
                        rep += 1
                        self.sess_repeats += 1
                        self.play_prog = {"jobs": n_jobs, "idx": ji + 1,
                                          "name": job["name"], "rep": rep,
                                          "reps": reps, "done": 0, "total": total}
                        self.q_status("▶ ВОСПРОИЗВЕДЕНИЕ — F12 — стоп", GREEN)
                        prev = 0.0
                        for i, ev in enumerate(events):
                            if self.stop_flag.is_set():
                                return
                            t = float(ev.get("t", prev) or 0.0)
                            delay = (t - prev) / speed
                            if delay < 0:
                                delay = 0.0
                            if jitter > 0 and delay > 0:
                                delay *= 1.0 + random.uniform(-jitter, jitter) / 100.0
                            self._sleep_stop(delay)
                            prev = t
                            try:
                                self._execute(ev)
                            except Exception:
                                pass
                            self.play_prog = {"jobs": n_jobs, "idx": ji + 1,
                                              "name": job["name"], "rep": rep,
                                              "reps": reps, "done": i + 1, "total": total}
                        if reps > 0 and rep >= reps:
                            break
                        if pause > 0:
                            self._sleep_stop(pause)
                    self.sess_jobs += 1
                    if pause > 0:
                        self._sleep_stop(pause)
                if not loop:
                    return
        finally:
            self.playing = False
            if self.stop_flag.is_set():
                self.q_status("■ Остановлено (F12). %s" % self._session_text(), AMBER)
            else:
                self.q_status("✓ Завершено. %s" % self._session_text(), GREEN)

    # ------------------------------------------------------------- профили
    def refresh_profiles(self):
        d = macro_dir()
        try:
            os.makedirs(d, exist_ok=True)
            files = sorted((f for f in os.listdir(d) if f.lower().endswith(".json")),
                           key=lambda f: -os.path.getmtime(os.path.join(d, f)))
        except OSError:
            files = []
        self.profile_box["values"] = files
        if files and not self.profile_box.get():
            self.profile_box.set(files[0])

    def save_profile(self):
        if self.playing or self.recording:
            self.q_status("Дождитесь окончания текущей операции", AMBER)
            return
        with self.ev_lock:
            events = list(self.events)
        if not events:
            self.q_status("Макрос пуст — нечего сохранять", AMBER)
            return
        self.refresh_profiles()
        suggested = datetime.now().strftime("уровень_%H-%M-%S.json")
        path = filedialog.asksaveasfilename(
            title="Сохранить макрос", initialdir=macro_dir(), initialfile=suggested,
            defaultextension=".json", filetypes=[("Макросы JSON", "*.json")])
        if not path:
            return
        data = {"app": APP_NAME, "version": VERSION,
                "created": datetime.now().isoformat(timespec="seconds"),
                "duration": round(self.duration, 3), "count": len(events),
                "events": events}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            self.q_status("Ошибка сохранения: %s" % e, RED)
            return
        self.macro_name = os.path.basename(path)
        self.name_var.set(self.macro_name)
        self.refresh_profiles()
        self.profile_box.set(self.macro_name)
        self.q_status("Макрос сохранён: %s (%d событий)" % (self.macro_name, len(events)), GREEN)

    def load_profile(self):
        if self.playing or self.recording:
            self.q_status("Дождитесь окончания текущей операции", AMBER)
            return
        name = self.profile_box.get()
        if name:
            path = os.path.join(macro_dir(), name)
        else:
            path = filedialog.askopenfilename(
                title="Загрузить макрос", initialdir=macro_dir(),
                filetypes=[("Макросы JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ev = data.get("events")
            if not isinstance(ev, list):
                raise ValueError("неверный формат файла")
            clean = [e for e in ev if isinstance(e, dict) and e.get("type") in TYPE_RUS]
        except Exception as e:
            self.q_status("Не удалось загрузить: %s" % e, RED)
            return
        with self.ev_lock:
            self.events = clean
            self.stats = {"move": 0, "click": 0, "scroll": 0, "key": 0}
            for e in clean:
                self.stats[e["type"]] = self.stats.get(e["type"], 0) + 1
        self.duration = float(data.get("duration") or 0.0)
        self.macro_name = os.path.basename(path)
        self.name_var.set(self.macro_name)
        self._rows_shown = 0
        self._clear_tree()
        self.q_status("Загружен макрос «%s»: %d событий" % (self.macro_name, len(clean)), GREEN)

    def delete_profile(self):
        name = self.profile_box.get()
        if not name:
            self.q_status("Выберите профиль в списке", AMBER)
            return
        path = os.path.join(macro_dir(), name)
        if not os.path.isfile(path):
            self.q_status("Файл не найден: %s" % name, RED)
            return
        if not messagebox.askyesno(APP_NAME, "Удалить профиль «%s»?" % name):
            return
        try:
            os.remove(path)
        except Exception as e:
            self.q_status("Ошибка удаления: %s" % e, RED)
            return
        self.refresh_profiles()
        self.q_status("Профиль удалён: %s" % name, FG)

    # ------------------------------------------------------------- плейлист
    def add_to_queue(self):
        if self.playing or self.recording:
            self.q_status("Дождитесь окончания текущей операции", AMBER)
            return
        name = self.profile_box.get()
        if not name:
            self.q_status("Сначала выберите профиль в списке (или сохраните текущий)", AMBER)
            return
        try:
            reps = max(1, int(float(self.q_repeats_var.get())))
        except (ValueError, TypeError):
            reps = 2
        self.queue_jobs.append({"file": name, "repeats": reps})
        self._render_queue()
        self._save_queue()
        self.q_status("В очередь: %s ×%d (заданий: %d)" % (name, reps, len(self.queue_jobs)), FG)

    def remove_from_queue(self):
        if self.playing:
            self.q_status("Нельзя менять очередь во время воспроизведения", AMBER)
            return
        sel = self.queue_list.curselection()
        if not sel:
            self.q_status("Выберите задание в очереди", AMBER)
            return
        del self.queue_jobs[sel[0]]
        self._render_queue()
        self._save_queue()

    def clear_queue(self):
        if self.playing:
            self.q_status("Нельзя менять очередь во время воспроизведения", AMBER)
            return
        if not self.queue_jobs:
            return
        if not messagebox.askyesno(APP_NAME, "Очистить всю очередь плейлиста?"):
            return
        self.queue_jobs = []
        self._render_queue()
        self._save_queue()
        self.q_status("Очередь очищена", FG)

    def _render_queue(self):
        self.queue_list.delete(0, "end")
        for i, j in enumerate(self.queue_jobs):
            self.queue_list.insert("end", "%2d. %s   ×%d" % (i + 1, j["file"], j["repeats"]))

    def _queue_path(self):
        return os.path.join(macro_dir(), "playlist.json")

    def _save_queue(self):
        try:
            os.makedirs(macro_dir(), exist_ok=True)
            with open(self._queue_path(), "w", encoding="utf-8") as f:
                json.dump({"jobs": self.queue_jobs,
                           "loop": bool(self.q_loop_var.get()),
                           "use_f10": bool(self.use_queue_var.get())},
                          f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _load_queue(self):
        try:
            with open(self._queue_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.queue_jobs = normalize_queue(data)
        self.q_loop_var.set(bool(data.get("loop", False)) if isinstance(data, dict) else False)
        self.use_queue_var.set(bool(data.get("use_f10", True)) if isinstance(data, dict) else True)
        self._render_queue()

    def _load_jobs_events(self, jobs):
        """Читает события каждого макроса очереди; битые/отсутствующие файлы пропускает."""
        loaded, missing = [], []
        for j in jobs:
            path = os.path.join(macro_dir(), j["file"])
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ev = [e for e in data.get("events", [])
                      if isinstance(e, dict) and e.get("type") in TYPE_RUS]
                if not ev:
                    raise ValueError("пустой макрос")
                loaded.append({"name": j["file"], "events": ev,
                               "repeats": max(1, int(j.get("repeats", 2)))})
            except Exception:
                missing.append(j["file"])
        return loaded, missing

    def _session_text(self):
        parts = ["повторов: %d" % self.sess_repeats,
                 "макросов завершено: %d" % self.sess_jobs]
        if self.sess_started:
            parts.append("время: %s" % _fmt_duration(time.time() - self.sess_started))
        return "Сессия — " + ", ".join(parts)

    # ================================================================== ЗРЕНИЕ
    def toggle_vision(self):
        """F11 — включить/выключить режим, в котором программа сама смотрит
        на экран и выполняет правила."""
        if self.vision_on:
            self.vision_on = False
            return
        miss = vision_missing()
        if miss:
            self.q_status("Зрению нужны библиотеки:  pip install %s" % " ".join(miss), RED)
            return
        if self.recording:
            self.q_status("Остановите запись (F9) перед запуском зрения", AMBER)
            return
        self._vision_apply_ui()
        self._vision_last_exec.clear()
        self.vision_on = True
        threading.Thread(target=self._vision_worker, daemon=True).start()
        self.q_status("👁 Зрение запущено — смотрю на экран. F11/F12 — стоп", GREEN)

    # --- настройки -----------------------------------------------------
    def _vision_path(self):
        return os.path.join(macro_dir(), "vision.json")

    def save_vision_cfg(self):
        try:
            os.makedirs(macro_dir(), exist_ok=True)
            data = dict(self.vision_cfg)
            data.pop("preview", None)          # превью — временная настройка
            data["rules"] = self.vision_rules
            with open(self._vision_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def load_vision_cfg(self):
        try:
            with open(self._vision_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        area = data.get("area")
        if not (isinstance(area, dict)
                and all(k in area for k in ("left", "top", "width", "height"))):
            area = None
        try:
            interval = min(5.0, max(0.1, float(data.get("interval", 0.5))))
        except (ValueError, TypeError):
            interval = 0.5
        try:
            monitor = max(1, int(data.get("monitor", 1)))
        except (ValueError, TypeError):
            monitor = 1
        self.vision_cfg = {
            "interval": interval,
            "monitor": monitor,
            "multiscale": bool(data.get("multiscale", False)),
            "clicks_during_play": bool(data.get("clicks_during_play", True)),
            "preview": False,
            "area": area,
        }
        self.vision_rules = normalize_rules(data.get("rules"))

    def _vision_apply_ui(self):
        """Переносит значения полей карточки «Зрение» в конфиг (перед стартом)."""
        try:
            self.vision_cfg["interval"] = min(5.0, max(0.1, float(
                str(self.vision_interval_var.get()).replace(",", "."))))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            self.vision_cfg["monitor"] = max(1, int(float(self.vision_mon_var.get() or 1)))
        except (ValueError, TypeError, AttributeError):
            self.vision_cfg["monitor"] = 1
        self.save_vision_cfg()

    def _vision_flags(self):
        self.vision_cfg["multiscale"] = bool(self.v_multi_var.get())
        self.vision_cfg["clicks_during_play"] = bool(self.v_clicks_play_var.get())
        self.save_vision_cfg()

    def _vision_cfg_snapshot(self):
        with self.vision_lock:
            return dict(self.vision_cfg)

    def _vision_rules_snapshot(self):
        with self.vision_lock:
            return [dict(r) for r in self.vision_rules]

    # --- захват экрана и шаблоны ---------------------------------------
    def _grab_screen(self, cfg):
        """Снимок экрана (или области поиска). Возвращает
        (bgr-массив, offset_x, offset_y) либо (None, 0, 0)."""
        if not (MSS_OK and NUMPY_OK):
            return None, 0, 0
        try:
            with mss.mss() as sct:
                mons = sct.monitors
                idx = int(cfg.get("monitor", 1))
                if len(mons) <= 1:
                    idx = 0
                else:
                    idx = min(max(1, idx), len(mons) - 1)
                base = mons[idx]
                area = cfg.get("area")
                box = None
                if isinstance(area, dict):
                    try:
                        l = max(int(base["left"]), int(area["left"]))
                        t = max(int(base["top"]), int(area["top"]))
                        r = min(int(base["left"]) + int(base["width"]),
                                int(area["left"]) + int(area["width"]))
                        b = min(int(base["top"]) + int(base["height"]),
                                int(area["top"]) + int(area["height"]))
                        if r - l >= 10 and b - t >= 10:
                            box = {"left": l, "top": t, "width": r - l, "height": b - t}
                    except (ValueError, TypeError, KeyError):
                        box = None
                if box is None:
                    box = {"left": int(base["left"]), "top": int(base["top"]),
                           "width": int(base["width"]), "height": int(base["height"])}
                raw = sct.grab(box)
        except Exception as e:
            self.q_status("Зрение: не удалось снять экран: %s" % e, RED)
            return None, 0, 0
        img = np.asarray(raw)[:, :, :3]           # BGRA → BGR
        return np.ascontiguousarray(img), box["left"], box["top"]

    def _load_template(self, fname):
        """Картинка шаблона с кэшем; unicode-пути через imdecode (Windows)."""
        path = os.path.join(template_dir(), fname)
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._tmpl_cache.get(fname)
        if cached and cached[1] == mt:
            return cached[0]
        try:
            buf = np.fromfile(path, dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            return None
        if img is None:
            return None
        self._tmpl_cache[fname] = (img, mt)
        return img

    # --- рабочий поток ---------------------------------------------------
    def _vision_worker(self):
        try:
            while not self.stop_flag.is_set() and self.vision_on:
                tick0 = time.time()
                cfg = self._vision_cfg_snapshot()
                interval = min(5.0, max(0.1, float(cfg.get("interval", 0.5))))
                rules = self._vision_rules_snapshot()
                shot, ox, oy = self._grab_screen(cfg)
                if shot is None:
                    time.sleep(1.0)
                    continue
                scales = scale_list(bool(cfg.get("multiscale")))
                busy = self.playing or self.recording or self.driver_on
                cd_play = bool(cfg.get("clicks_during_play", True))
                t_now = time.time()
                found = []
                hit = None
                for r in rules:
                    if not r.get("enabled", True):
                        continue
                    if not rule_allowed(r, busy, cd_play, t_now, self._vision_last_exec):
                        continue
                    tmpl = self._load_template(r["image"])
                    if tmpl is None:
                        continue
                    m = find_template(shot, tmpl, r["threshold"], scales)
                    if m:
                        found.append({"name": r["name"], "score": m[0], "box": m[1:]})
                        if hit is None:
                            hit = (r, m)
                st = {"found": found,
                      "checks": self.vision_state.get("checks", 0) + 1,
                      "actions": self.vision_state.get("actions", 0),
                      "last": self.vision_state.get("last", ""),
                      "ts": t_now, "preview": None,
                      "size": (int(shot.shape[1]), int(shot.shape[0]))}
                if cfg.get("preview"):
                    st["preview"] = self._make_preview(shot, found, hit)
                with self.vision_lock:
                    self.vision_state = st
                if hit:
                    self._vision_execute(hit[0], hit[1], ox, oy)
                spent = time.time() - tick0
                if interval - spent > 0:
                    self._sleep_stop(interval - spent)
        finally:
            self.vision_on = False
            self.q_status("■ Зрение остановлено", FG)

    def _vision_execute(self, rule, m, ox, oy):
        score, x, y, w, h = m
        self._vision_last_exec[rule["name"]] = time.time()
        if float(rule.get("delay", 0.0)) > 0:
            self._sleep_stop(float(rule["delay"]))
            if self.stop_flag.is_set() or not self.vision_on:
                return
        act = rule["action"]
        if act in ("click", "click_macro"):
            gx, gy = to_global(x + w // 2, y + h // 2,
                               {"left": ox, "top": oy},
                               rule.get("dx", 0), rule.get("dy", 0))
            try:
                self.mouse_ctrl.position = (gx, gy)
                time.sleep(0.05)
                self.mouse_ctrl.press(mouse.Button.left)
                time.sleep(0.04)
                self.mouse_ctrl.release(mouse.Button.left)
                self.q_status("👁 Зрение: «%s» → клик (%d, %d), точность %d%%"
                              % (rule["name"], gx, gy, round(score * 100)), BLUE)
            except Exception as e:
                self.q_status("Зрение: клик не удался: %s" % e, RED)
        if act in ("macro", "click_macro") and rule.get("macro"):
            self.vision_play_macro(rule["macro"])
        elif act == "notify":
            self.q_status("👁 Зрение: вижу «%s» (точность %d%%)"
                          % (rule["name"], round(score * 100)), AMBER)
        with self.vision_lock:
            st = dict(self.vision_state)
            st["actions"] = st.get("actions", 0) + 1
            st["last"] = "%s (%d%%)" % (rule["name"], round(score * 100))
            self.vision_state = st

    def _make_preview(self, shot, found, hit):
        """Уменьшенный кадр с рамками найденных шаблонов (PNG в base64)."""
        try:
            W = 480
            h, w = shot.shape[:2]
            ph = max(1, int(round(W * h / w)))
            small = cv2.resize(shot, (W, ph))
            kx, ky = W / float(w), ph / float(h)
            hit_name = hit[0]["name"] if hit else None
            for f in found:
                x, y, bw, bh = f["box"]
                p1 = (int(x * kx), int(y * ky))
                p2 = (int((x + bw) * kx), int((y + bh) * ky))
                col = (0, 220, 120) if f["name"] == hit_name else (100, 100, 120)
                cv2.rectangle(small, p1, p2, col, 2)
                cv2.putText(small, "%d%%" % round(f["score"] * 100),
                            (p1[0], max(14, p1[1] - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
            ok, buf = cv2.imencode(".png", small)
            return base64.b64encode(buf.tobytes()) if ok else None
        except Exception:
            return None

    # --- правила: список, редактор, шаблоны -----------------------------
    def _render_vision_rules(self):
        self.vision_list.delete(0, "end")
        for i, r in enumerate(self.vision_rules):
            mark = "▶" if r.get("enabled", True) else "○"
            act = ACTION_RUS.get(r.get("action"), str(r.get("action")))
            extra = ""
            if r.get("action") in ("macro", "click_macro") and r.get("macro"):
                extra = " → " + r["macro"]
            self.vision_list.insert(
                "end", "%2d. %s %s — %s%s (порог %.2f)"
                % (i + 1, mark, r.get("name", "?"), act, extra,
                   float(r.get("threshold", 0.85))))
        self._update_area_label()

    def _update_area_label(self):
        a = self.vision_cfg.get("area")
        if not a:
            self.vision_area_lbl.config(text="Область поиска: весь монитор")
        else:
            self.vision_area_lbl.config(
                text="Область поиска: %d×%d от (%d, %d)"
                     % (a.get("width", 0), a.get("height", 0),
                        a.get("left", 0), a.get("top", 0)))

    def _select_region_dialog(self, shot_bgr, title):
        """Показывает снимок экрана; пользователь обводит область мышью.
        Возвращает (x, y, w, h) в координатах снимка или None."""
        h0, w0 = shot_bgr.shape[:2]
        scale = min(1.0, 1000.0 / w0, 560.0 / h0)
        disp = cv2.resize(shot_bgr, (max(1, int(w0 * scale)), max(1, int(h0 * scale)))) \
            if scale < 1.0 else shot_bgr
        try:
            ok, buf = cv2.imencode(".png", disp)
        except Exception:
            ok = False
        if not ok:
            self.q_status("Не удалось подготовить снимок", RED)
            return None
        photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.transient(self.root)
        top._photo = photo                        # защита от сборщика мусора
        tk.Label(top, text="Зажмите ЛКМ и обведите нужную область (кнопку, окно игры)",
                 bg=BG, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 4))
        cv = tk.Canvas(top, width=disp.shape[1], height=disp.shape[0],
                       highlightthickness=1, highlightbackground=BORDER,
                       cursor="crosshair", bg="#000000")
        cv.pack(padx=10, pady=(0, 8))
        cv.create_image(0, 0, image=photo, anchor="nw")
        sel = {"box": None}
        st = {"x0": 0, "y0": 0, "id": None}

        def press(e):
            st["x0"], st["y0"] = e.x, e.y
            if st["id"]:
                cv.delete(st["id"])
            st["id"] = None

        def drag(e):
            if st["id"]:
                cv.delete(st["id"])
            st["id"] = cv.create_rectangle(st["x0"], st["y0"], e.x, e.y,
                                           outline=GREEN, width=2)

        def release(e):
            x0, x1 = sorted((st["x0"], e.x))
            y0, y1 = sorted((st["y0"], e.y))
            if x1 - x0 > 4 and y1 - y0 > 4:
                sel["box"] = (x0, y0, x1, y1)

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", release)

        done = {"go": False}

        def confirm():
            if sel["box"]:
                done["go"] = True
                top.destroy()

        row = tk.Frame(top, bg=BG)
        row.pack(pady=(0, 10))
        tk.Button(row, text="Готово", command=confirm, bg=PLAY_BG, fg="#dcffe9",
                  activebackground=PLAY_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0).pack(side="left", padx=4)
        tk.Button(row, text="Отмена", command=top.destroy, bg=BTN_BG, fg=FG,
                  activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0).pack(side="left", padx=4)
        top.grab_set()
        top.wait_window()
        if not done["go"] or not sel["box"]:
            return None
        x0, y0, x1, y1 = sel["box"]
        x = int(min(x0, x1) / scale)
        y = int(min(y0, y1) / scale)
        w = int((x1 - x0) / scale)
        h = int((y1 - y0) / scale)
        w = max(4, min(w, w0 - x))
        h = max(4, min(h, h0 - y))
        return (x, y, w, h)

    def vision_new_template(self):
        """Снимает экран → пользователь обводит элемент → сохраняется шаблон
        и создаётся правило."""
        if vision_missing():
            self.q_status("Сначала установите:  pip install %s"
                          % " ".join(vision_missing()), RED)
            return
        if self.recording or self.playing:
            self.q_status("Дождитесь окончания записи/воспроизведения", AMBER)
            return
        self._vision_apply_ui()
        cfg = dict(self.vision_cfg)
        cfg["area"] = None                        # снимаем весь монитор
        shot, ox, oy = self._grab_screen(cfg)
        if shot is None:
            return
        box = self._select_region_dialog(shot, "Новый шаблон — выделите элемент")
        if not box:
            return
        x, y, w, h = box
        crop = shot[y:y + h, x:x + w].copy()
        name = simpledialog.askstring(
            "Новый шаблон", "Как назвать элемент?\n(например: Кнопка Далее)",
            parent=self.root)
        if not name or not name.strip():
            return
        safe = "".join(ch for ch in name.strip() if ch not in '\\/:*?"<>|').strip() or "шаблон"
        d = template_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            self.q_status("Не создать папку templates: %s" % e, RED)
            return
        fname = safe + ".png"
        i = 2
        while os.path.exists(os.path.join(d, fname)):
            fname = "%s_%d.png" % (safe, i)
            i += 1
        try:
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                raise ValueError("ошибка кодирования PNG")
            buf.tofile(os.path.join(d, fname))
        except Exception as e:
            self.q_status("Не удалось сохранить шаблон: %s" % e, RED)
            return
        self.vision_rules.append({
            "name": safe, "image": fname, "action": "click", "macro": "",
            "threshold": 0.85, "cooldown": 2.0, "delay": 0.0,
            "dx": 0, "dy": 0, "enabled": True})
        self._tmpl_cache.pop(fname, None)
        self._render_vision_rules()
        self.save_vision_cfg()
        self.q_status("Шаблон сохранён: templates/%s — настройте правило (✎ Править)"
                      % fname, GREEN)
        self.vision_edit_rule(len(self.vision_rules) - 1)

    def vision_edit_rule(self, index=None):
        if index is None:
            sel = self.vision_list.curselection()
            index = sel[0] if sel else None
        if index is None or index < 0 or index >= len(self.vision_rules):
            self.q_status("Выберите правило в списке", AMBER)
            return
        r = self.vision_rules[index]
        act_rev = {v: k for k, v in ACTION_RUS.items()}
        top = tk.Toplevel(self.root)
        top.title("Правило: %s" % r.get("name", "?"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.transient(self.root)
        grid = tk.Frame(top, bg=BG)
        grid.pack(padx=12, pady=10)

        def lab(row, text):
            tk.Label(grid, text=text, bg=BG, fg=MUTED).grid(row=row, column=0,
                                                            sticky="w", pady=3)

        def cell(row):
            f = tk.Frame(grid, bg=BG)
            f.grid(row=row, column=1, sticky="w", padx=(10, 0))
            return f

        lab(0, "Имя:")
        name_var = tk.StringVar(value=r.get("name", ""))
        ttk.Entry(cell(0), textvariable=name_var, width=28).pack(side="left")

        lab(1, "Шаблон (картинка):")
        tk.Label(cell(1), text="templates/" + r.get("image", "?"), bg=BG, fg=FG).pack(side="left")

        lab(2, "Действие:")
        act_var = tk.StringVar(value=ACTION_RUS.get(r.get("action"), "Кликнуть"))
        ttk.Combobox(cell(2), textvariable=act_var, values=list(ACTION_RUS.values()),
                     state="readonly", width=24).pack(side="left")

        lab(3, "Макрос (для действий с макросом):")
        mac_var = tk.StringVar(value=r.get("macro", ""))
        macs = [""] + list(self.profile_box["values"])
        ttk.Combobox(cell(3), textvariable=mac_var, values=macs, width=26).pack(side="left")

        lab(4, "Порог совпадения (0.50–0.99):")
        th_var = tk.StringVar(value="%.2f" % float(r.get("threshold", 0.85)))
        ttk.Spinbox(cell(4), from_=0.5, to=0.99, increment=0.01,
                    textvariable=th_var, width=7).pack(side="left")

        lab(5, "Кулдаун, с (пауза между срабатываниями):")
        cd_var = tk.StringVar(value="%g" % float(r.get("cooldown", 2.0)))
        ttk.Spinbox(cell(5), from_=0, to=600, increment=0.5,
                    textvariable=cd_var, width=7).pack(side="left")

        lab(6, "Задержка перед действием, с:")
        dl_var = tk.StringVar(value="%g" % float(r.get("delay", 0.0)))
        ttk.Spinbox(cell(6), from_=0, to=60, increment=0.5,
                    textvariable=dl_var, width=7).pack(side="left")

        lab(7, "Смещение клика от центра шаблона, X и Y:")
        p7 = cell(7)
        dx_var = tk.StringVar(value=str(int(r.get("dx", 0))))
        dy_var = tk.StringVar(value=str(int(r.get("dy", 0))))
        ttk.Spinbox(p7, from_=-5000, to=5000, increment=2, textvariable=dx_var,
                    width=6).pack(side="left")
        ttk.Spinbox(p7, from_=-5000, to=5000, increment=2, textvariable=dy_var,
                    width=6).pack(side="left", padx=(6, 0))

        en_var = tk.BooleanVar(value=bool(r.get("enabled", True)))
        ttk.Checkbutton(grid, text="Правило включено", variable=en_var)\
            .grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def save():
            nm = name_var.get().strip()
            if not nm:
                messagebox.showwarning(APP_NAME, "Введите имя правила", parent=top)
                return
            act = act_rev.get(act_var.get(), "click")
            mac_raw = mac_var.get().strip()
            mac = os.path.basename(mac_raw) if mac_raw else ""
            if act in ("macro", "click_macro") and not mac:
                messagebox.showwarning(APP_NAME,
                                       "Для этого действия выберите макрос", parent=top)
                return
            try:
                th = min(0.99, max(0.5, float(str(th_var.get()).replace(",", "."))))
            except ValueError:
                th = 0.85
            try:
                cd = min(600.0, max(0.0, float(str(cd_var.get()).replace(",", "."))))
            except ValueError:
                cd = 2.0
            try:
                dl = min(60.0, max(0.0, float(str(dl_var.get()).replace(",", "."))))
            except ValueError:
                dl = 0.0
            try:
                dxi = int(float(dx_var.get()))
                dyi = int(float(dy_var.get()))
            except ValueError:
                dxi = dyi = 0
            r.update({"name": nm, "action": act, "macro": mac, "threshold": th,
                      "cooldown": cd, "delay": dl, "dx": dxi, "dy": dyi,
                      "enabled": bool(en_var.get())})
            self._render_vision_rules()
            self.save_vision_cfg()
            top.destroy()
            self.q_status("Правило обновлено: %s" % nm, GREEN)

        brow = tk.Frame(top, bg=BG)
        brow.pack(pady=(4, 10))
        tk.Button(brow, text="Сохранить", command=save, bg=PLAY_BG, fg="#dcffe9",
                  activebackground=PLAY_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0).pack(side="left", padx=4)
        tk.Button(brow, text="Отмена", command=top.destroy, bg=BTN_BG, fg=FG,
                  activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0).pack(side="left", padx=4)

    def vision_delete_rule(self):
        sel = self.vision_list.curselection()
        if not sel:
            self.q_status("Выберите правило в списке", AMBER)
            return
        i = sel[0]
        if not messagebox.askyesno(APP_NAME, "Удалить правило «%s»? (файл шаблона останется)"
                                   % self.vision_rules[i].get("name", "?")):
            return
        del self.vision_rules[i]
        self._render_vision_rules()
        self.save_vision_cfg()

    def vision_move_rule(self, delta):
        """Сдвиг правила вверх/вниз — выше в списке = выше приоритет."""
        sel = self.vision_list.curselection()
        if not sel:
            self.q_status("Выберите правило в списке", AMBER)
            return
        i = sel[0]
        j = i + delta
        if j < 0 or j >= len(self.vision_rules):
            return
        self.vision_rules[i], self.vision_rules[j] = \
            self.vision_rules[j], self.vision_rules[i]
        self._render_vision_rules()
        self.save_vision_cfg()
        self.vision_list.selection_clear(0, "end")
        self.vision_list.selection_set(j)

    def vision_test(self):
        """Разовая проверка: какие правила сейчас найдены на экране."""
        if vision_missing():
            self.q_status("Сначала установите:  pip install %s"
                          % " ".join(vision_missing()), RED)
            return
        self._vision_apply_ui()
        cfg = self._vision_cfg_snapshot()
        shot, _ox, _oy = self._grab_screen(cfg)
        if shot is None:
            return
        scales = scale_list(bool(cfg.get("multiscale")))
        res = []
        for r in self.vision_rules:
            if not r.get("enabled", True):
                continue
            tmpl = self._load_template(r["image"])
            if tmpl is None:
                res.append("«%s» — нет файла шаблона" % r["name"])
                continue
            m = find_template(shot, tmpl, r["threshold"], scales)
            res.append("«%s» — %s" % (r["name"],
                       ("найден %d%%" % round(m[0] * 100)) if m else "не найден"))
        self.q_status("Тест зрения: " + ("; ".join(res) if res else "нет правил"), BLUE)

    def vision_pick_area(self):
        """Выбор области поиска (окна игры) — быстрее и меньше ложных находок."""
        if vision_missing():
            self.q_status("Сначала установите:  pip install %s"
                          % " ".join(vision_missing()), RED)
            return
        self._vision_apply_ui()
        cfg = dict(self.vision_cfg)
        cfg["area"] = None
        shot, ox, oy = self._grab_screen(cfg)
        if shot is None:
            return
        box = self._select_region_dialog(shot, "Область поиска — обведите окно игры")
        if not box:
            return
        x, y, w, h = box
        self.vision_cfg["area"] = {"left": ox + x, "top": oy + y,
                                   "width": w, "height": h}
        self.save_vision_cfg()
        self._update_area_label()
        self.q_status("Область поиска задана", GREEN)

    def vision_reset_area(self):
        self.vision_cfg["area"] = None
        self.save_vision_cfg()
        self._update_area_label()

    def vision_toggle_preview(self):
        """Окно «что видит робот» — живой кадр с рамками найденного."""
        if self.preview_win is not None and self.preview_win.winfo_exists():
            self.preview_win.destroy()
            self.preview_win = None
            self.preview_canvas = None
            self.vision_cfg["preview"] = False
            return
        if not CV_OK:
            self.q_status("Превью требует opencv-python", AMBER)
            return
        self.vision_cfg["preview"] = True
        w = tk.Toplevel(self.root)
        w.title("Что видит робот")
        w.configure(bg=BG)
        w.attributes("-topmost", True)
        self.preview_canvas = tk.Canvas(w, width=484, height=300, bg="#000000",
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.preview_canvas.pack(padx=8, pady=(8, 2))
        tk.Label(w, text="Зелёная рамка — правило, которое выполнится",
                 bg=BG, fg=MUTED).pack(pady=(0, 8))
        self.preview_win = w

    # ============================================================== AI-ВОДИТЕЛЬ
    def _driver_path(self):
        return os.path.join(macro_dir(), "driver.json")

    def _driver_defaults(self):
        return {
            "keys": {"gas": "w", "brake": "s", "left": "a", "right": "d"},
            "car_hsv": None, "car_tol": 14, "car_s_min": 60, "car_v_min": 60,
            "target_hsv": None, "target_tol": 14, "target_s_min": 60,
            "target_v_min": 60,
            "min_frac": 0.002, "max_frac": 0.25,
            "stop_dist_frac": 0.04, "steer_deadzone": 8.0,
            "max_speed_px": 450.0, "creep_speed": 80.0,
            "invert_heading": False,
            "stuck_time": 2.0, "recover_time": 1.2, "lost_time": 3.0,
            "interval": 0.06, "monitor": 1, "area": None, "preview": False,
        }

    def load_driver_cfg(self):
        cfg = self._driver_defaults()
        try:
            with open(self._driver_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

        def _num(key, lo, hi, default):
            try:
                v = float(data.get(key, default))
            except (ValueError, TypeError):
                v = float(default)
            return min(hi, max(lo, v))

        cfg["car_tol"] = int(_num("car_tol", 1, 90, 14))
        cfg["target_tol"] = int(_num("target_tol", 1, 90, 14))
        cfg["car_s_min"] = int(_num("car_s_min", 0, 255, 60))
        cfg["car_v_min"] = int(_num("car_v_min", 0, 255, 60))
        cfg["target_s_min"] = int(_num("target_s_min", 0, 255, 60))
        cfg["target_v_min"] = int(_num("target_v_min", 0, 255, 60))
        cfg["min_frac"] = _num("min_frac", 0.0001, 0.5, 0.002)
        cfg["max_frac"] = _num("max_frac", 0.01, 0.95, 0.25)
        cfg["stop_dist_frac"] = _num("stop_dist_frac", 0.005, 0.3, 0.04)
        cfg["steer_deadzone"] = _num("steer_deadzone", 1.0, 60.0, 8.0)
        cfg["max_speed_px"] = _num("max_speed_px", 30.0, 3000.0, 450.0)
        cfg["creep_speed"] = _num("creep_speed", 10.0, 1000.0, 80.0)
        cfg["stuck_time"] = _num("stuck_time", 0.5, 30.0, 2.0)
        cfg["recover_time"] = _num("recover_time", 0.3, 10.0, 1.2)
        cfg["lost_time"] = _num("lost_time", 1.0, 30.0, 3.0)
        cfg["interval"] = _num("interval", 0.03, 1.0, 0.06)
        cfg["monitor"] = max(1, int(_num("monitor", 1, 8, 1)))
        cfg["invert_heading"] = bool(data.get("invert_heading", False))
        cfg["preview"] = False                      # превью — временная настройка

        keys = data.get("keys")
        if isinstance(keys, dict):
            for k in ("gas", "brake", "left", "right"):
                v = keys.get(k)
                if isinstance(v, str) and v.strip():
                    cfg["keys"][k] = v.strip().lower()[:8]

        for name in ("car_hsv", "target_hsv"):
            v = data.get(name)
            if (isinstance(v, (list, tuple)) and len(v) == 3
                    and all(isinstance(x, (int, float)) for x in v)):
                cfg[name] = [int(v[0]) % 180, int(v[1]) % 256, int(v[2]) % 256]

        area = data.get("area")
        if isinstance(area, dict) and all(
                k in area for k in ("left", "top", "width", "height")):
            cfg["area"] = area
        self.driver_cfg = cfg

    def save_driver_cfg(self):
        try:
            os.makedirs(macro_dir(), exist_ok=True)
            data = dict(self.driver_cfg)
            data.pop("preview", None)
            with open(self._driver_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _driver_apply_ui(self):
        """Значения полей карточки AI-водителя → конфиг (перед стартом)."""
        c = self.driver_cfg
        ks = c["keys"]
        for name, var in (("gas", self.d_gas_var), ("brake", self.d_brake_var),
                          ("left", self.d_left_var), ("right", self.d_right_var)):
            try:
                v = str(var.get()).strip().lower()
                if v:
                    ks[name] = v[:8]
            except (AttributeError, ValueError):
                pass
        try:
            c["car_tol"] = int(float(self.d_car_tol_var.get()))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["target_tol"] = int(float(self.d_tgt_tol_var.get()))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["stop_dist_frac"] = min(0.3, max(0.005,
                                      float(str(self.d_stop_var.get()).replace(",", "."))) / 100.0)
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["steer_deadzone"] = min(60.0, max(1.0,
                                      float(str(self.d_dead_var.get()).replace(",", "."))))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["max_speed_px"] = min(3000.0, max(30.0,
                                    float(str(self.d_maxsp_var.get()).replace(",", "."))))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["min_frac"] = min(0.5, max(0.0001,
                                float(str(self.d_minf_var.get()).replace(",", "."))) / 100.0)
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            c["monitor"] = max(1, int(float(self.d_mon_var.get() or 1)))
        except (ValueError, TypeError, AttributeError):
            c["monitor"] = 1
        c["invert_heading"] = bool(self.d_inv_var.get())
        self.save_driver_cfg()

    def char_to_key(self, s):
        """Строка из поля настроек → pynput-клавиша (буква или спецклавиша)."""
        s = str(s or "").strip().lower()
        if not s:
            return None
        special = {"up": "up", "down": "down", "left": "left", "right": "right",
                   "space": "space", "shift": "shift", "ctrl": "ctrl",
                   "alt": "alt", "enter": "enter", "tab": "tab"}
        if s in special and PYNPUT_OK:
            try:
                return Key[special[s]]
            except KeyError:
                return None
        if not PYNPUT_OK:
            return None
        try:
            return KeyCode.from_char(s[0])
        except Exception:
            return None

    def _driver_keymap(self):
        ks = self.driver_cfg["keys"]
        return {"gas": self.char_to_key(ks.get("gas")),
                "brake": self.char_to_key(ks.get("brake")),
                "left": self.char_to_key(ks.get("left")),
                "right": self.char_to_key(ks.get("right"))}

    def _driver_holds(self, held, want, keymap):
        """Зажимает/отпускает клавиши так, чтобы набор совпадал с want."""
        for act, key in keymap.items():
            if key is None:
                continue
            if act in want and act not in held:
                try:
                    self.kb_ctrl.press(key)
                    held.add(act)
                except Exception:
                    pass
            elif act not in want and act in held:
                try:
                    self.kb_ctrl.release(key)
                    held.discard(act)
                except Exception:
                    pass

    def _driver_release_now(self):
        """Мгновенно отпустить всё, что зажал водитель (F12/выход)."""
        held = getattr(self, "_driver_held", None)
        if not held or not PYNPUT_OK:
            return
        keymap = self._driver_keymap()
        for act in list(held):
            key = keymap.get(act)
            if key is not None:
                try:
                    self.kb_ctrl.release(key)
                except Exception:
                    pass
        held.clear()

    def toggle_driver(self):
        """F8 — включить/выключить режим, в котором робот сам ведёт машину."""
        if self.driver_on:
            self.driver_on = False
            return
        miss = vision_missing()
        if miss:
            self.q_status("AI-водителю нужны библиотеки:  pip install %s"
                          % " ".join(miss), RED)
            return
        if self.recording:
            self.q_status("Остановите запись (F9) перед запуском водителя", AMBER)
            return
        if self.playing:
            self.q_status("Остановите воспроизведение (F12) перед запуском водителя", AMBER)
            return
        if not self.driver_cfg.get("car_hsv") or not self.driver_cfg.get("target_hsv"):
            self.q_status("Сначала калибровка: клик по машине и клик по зоне парковки "
                          "(кнопка «Калибровка цветов»)", AMBER)
            return
        self._driver_apply_ui()
        self.driver_on = True
        threading.Thread(target=self._driver_worker, daemon=True).start()
        self.q_status("🤖 AI-водитель поехал — F8/F12 стоп. Лучше всего видит "
                      "с камерой «сверху»", GREEN)

    def _driver_worker(self):
        """Рабочий цикл водителя: снимок экрана → найти машину и цель →
        решение → зажать/отпустить клавиши. ~15 кадров в секунду."""
        keymap = self._driver_keymap()
        held = self._driver_held
        st = {"mode": "search", "lost_t": 0.0, "stuck_t": 0.0, "recover_t": 0.0,
              "heading": None, "pos": None, "speed": 0.0, "err": 0.0,
              "want_move": False}
        prev_pos = None
        last_t = time.perf_counter()
        checks = 0
        try:
            while not self.stop_flag.is_set() and self.driver_on:
                t0 = time.perf_counter()
                cfg = dict(self.driver_cfg)
                interval = min(1.0, max(0.03, float(cfg.get("interval", 0.06))))
                shot, _ox, _oy = self._grab_screen(
                    {"monitor": cfg.get("monitor", 1), "area": cfg.get("area")})
                if shot is None:
                    time.sleep(1.0)
                    last_t = time.perf_counter()
                    continue
                hsv = cv2.cvtColor(shot, cv2.COLOR_BGR2HSV)
                fh, fw = hsv.shape[:2]
                px_area = float(fw * fh)
                car = target = None
                if cfg.get("car_hsv"):
                    car = find_color_blob(
                        hsv, cfg["car_hsv"], cfg.get("car_tol", 14),
                        cfg.get("car_s_min", 60), cfg.get("car_v_min", 60),
                        px_area * float(cfg.get("min_frac", 0.002)),
                        px_area * float(cfg.get("max_frac", 0.25)))
                if cfg.get("target_hsv"):
                    target = find_color_blob(
                        hsv, cfg["target_hsv"], cfg.get("target_tol", 14),
                        cfg.get("target_s_min", 60), cfg.get("target_v_min", 60),
                        px_area * float(cfg.get("min_frac", 0.002)),
                        px_area * float(cfg.get("max_frac", 0.25)))

                now_t = time.perf_counter()
                dt = min(0.5, max(0.01, now_t - last_t))
                last_t = now_t

                moving = False
                motion_deg = float(st.get("heading") or 0.0)
                if car is not None and prev_pos is not None:
                    jump = math.hypot(car["cx"] - prev_pos[0],
                                      car["cy"] - prev_pos[1])
                    if jump > max(1.5, dt * 10.0):
                        moving = True
                        motion_deg = bearing_deg(prev_pos[0], prev_pos[1],
                                                 car["cx"], car["cy"])
                prev_pos = (car["cx"], car["cy"]) if car is not None else None

                dec = drive_step(
                    {"car": car, "target": target, "frame_w": fw, "frame_h": fh,
                     "dt": dt, "speed": 0.0, "motion_deg": motion_deg,
                     "moving": moving},
                    cfg, st)

                want = set()
                if dec["throttle"] > 0:
                    want.add("gas")
                elif dec["throttle"] < 0:
                    want.add("brake")
                if dec["steer"] > 0:
                    want.add("right")
                elif dec["steer"] < 0:
                    want.add("left")
                self._driver_holds(held, want, keymap)
                checks += 1

                self.driver_state = {
                    "mode": dec["mode"], "msg": dec["msg"], "done": dec["done"],
                    "err": dec["err"], "dist": dec["dist_frac"],
                    "car": car is not None, "target": target is not None,
                    "speed": float(st.get("speed", 0.0)),
                    "heading": st.get("heading"), "checks": checks,
                    "preview": None, "ts": time.time()}
                if cfg.get("preview"):
                    self.driver_state["preview"] = self._driver_preview(
                        shot, car, target, dec, st)

                if dec["done"]:
                    self.driver_on = False
                    ok = dec["mode"] == "done"
                    self.q_status("🤖 AI-водитель: %s" % dec["msg"],
                                  GREEN if ok else AMBER)
                    break
                spent = time.perf_counter() - t0
                if interval - spent > 0:
                    self._sleep_stop(interval - spent)
        finally:
            for act in list(held):
                key = keymap.get(act)
                if key is not None:
                    try:
                        self.kb_ctrl.release(key)
                    except Exception:
                        pass
            held.clear()
            self.driver_on = False
            self.q_status("■ AI-водитель остановлен", FG)

    def _driver_preview(self, shot, car, target, dec, st):
        """Кадр «что видит водитель»: цель жёлтым, машина зелёным,
        курс стрелкой, линия к цели, режим и ошибка руля текстом."""
        try:
            W = 480
            h, w = shot.shape[:2]
            ph = max(1, int(round(W * h / w)))
            small = cv2.resize(shot, (W, ph))
            kx, ky = W / float(w), ph / float(h)
            if target is not None:
                p = (int(target["cx"] * kx), int(target["cy"] * ky))
                r = max(8, int(max(target["w"], target["h"]) * kx / 2.0))
                cv2.circle(small, p, r, (0, 255, 255), 2)
                cv2.putText(small, "ЦЕЛЬ", (p[0] - 18, max(12, p[1] - r - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255),
                            1, cv2.LINE_AA)
            if car is not None:
                p = (int(car["cx"] * kx), int(car["cy"] * ky))
                r = max(6, int(max(car["w"], car["h"]) * kx / 2.0))
                cv2.circle(small, p, r, (0, 255, 0), 2)
                hd = math.radians(float(st.get("heading") or 0.0))
                p2 = (int(p[0] + math.cos(hd) * 34),
                      int(p[1] + math.sin(hd) * 34))
                cv2.arrowedLine(small, p, p2, (0, 255, 255), 2,
                                tipLength=0.3)
                if target is not None:
                    tp = (int(target["cx"] * kx), int(target["cy"] * ky))
                    cv2.line(small, p, tp, (255, 140, 0), 1, cv2.LINE_AA)
            mode = DRIVER_MODE_RUS.get(dec["mode"], dec["mode"])
            txt = "%s | дист %d%% | руль %+d град | %d px/s" % (
                mode, round(dec["dist_frac"] * 100),
                round(dec["err"]), round(float(st.get("speed", 0.0))))
            cv2.putText(small, txt, (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (255, 255, 255), 1, cv2.LINE_AA)
            if dec["msg"]:
                cv2.putText(small, dec["msg"][:60], (6, ph - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 200, 255),
                            1, cv2.LINE_AA)
            ok, buf = cv2.imencode(".png", small)
            return base64.b64encode(buf.tobytes()) if ok else None
        except Exception:
            return None

    def driver_calibrate(self):
        """Калибровка цветов: снимок экрана → клик по машине → клик по зоне."""
        if vision_missing():
            self.q_status("Сначала установите:  pip install %s"
                          % " ".join(vision_missing()), RED)
            return
        if self.recording or self.playing or self.driver_on:
            self.q_status("Дождитесь окончания текущей операции", AMBER)
            return
        cfg = dict(self.driver_cfg)
        cfg["area"] = None                       # снимаем весь монитор
        shot, _ox, _oy = self._grab_screen(cfg)
        if shot is None:
            return
        h0, w0 = shot.shape[:2]
        scale = min(1.0, 1000.0 / w0, 560.0 / h0)
        disp = cv2.resize(shot, (max(1, int(w0 * scale)), max(1, int(h0 * scale)))) \
            if scale < 1.0 else shot
        ok, buf = cv2.imencode(".png", disp)
        if not ok:
            self.q_status("Не удалось подготовить снимок", RED)
            return
        photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        top = tk.Toplevel(self.root)
        top.title("Калибровка AI-водителя")
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.transient(self.root)
        top._photo = photo
        info = tk.Label(top, text="Шаг 1: кликните по КУЗОВУ вашей машины\n"
                                  "Шаг 2: кликните по ЖЁЛТОЙ ЗОНЕ парковки\n"
                                  "Третий клик — начать заново",
                        bg=BG, fg=MUTED, justify="left")
        info.pack(anchor="w", padx=10, pady=(8, 4))
        cv = tk.Canvas(top, width=disp.shape[1], height=disp.shape[0],
                       highlightthickness=1, highlightbackground=BORDER,
                       cursor="crosshair", bg="#000000")
        cv.pack(padx=10, pady=(0, 6))
        cv.create_image(0, 0, image=photo, anchor="nw")
        sel = {"car": None, "target": None}
        marks = {"car": None, "target": None}

        def refresh_info():
            parts = []
            for key, title in (("car", "машина"), ("target", "зона")):
                v = sel[key]
                if v:
                    parts.append("%s: HSV %s" % (title, v[2]))
                else:
                    parts.append("%s: —" % title)
            info.config(text="Клик по КУЗОВУ машины, затем по ЖЁЛТОЙ ЗОНЕ парковки.\n"
                             "Третий клик — начать заново.\n"
                             + "   |   ".join(parts))

        def on_click(e):
            x = int(e.x / scale)
            y = int(e.y / scale)
            if x < 0 or y < 0 or x >= w0 or y >= h0:
                return
            if sel["car"] is not None and sel["target"] is not None:
                for mk in marks.values():
                    if mk:
                        cv.delete(mk)
                sel["car"] = None
                sel["target"] = None
                refresh_info()
                return
            hsv = sample_patch_hsv(shot, x, y)
            if hsv is None:
                return
            slot = "car" if sel["car"] is None else "target"
            color = "#ff5b5b" if slot == "car" else "#3dd68c"
            cvv_ = "#ff2020" if slot == "car" else "#20c060"
            if marks[slot]:
                cv.delete(marks[slot])
            mid = cv.create_oval(e.x - 7, e.y - 7, e.x + 7, e.y + 7,
                                 outline=color, width=2)
            cv.create_line(e.x - 11, e.y, e.x + 11, e.y, fill=cvv_, width=1)
            cv.create_line(e.x, e.y - 11, e.x, e.y + 11, fill=cvv_, width=1)
            marks[slot] = mid
            sel[slot] = (x, y, hsv)
            refresh_info()

        def save():
            if not sel["car"] or not sel["target"]:
                messagebox.showwarning(
                    APP_NAME, "Сначала кликните по машине и по зоне парковки",
                    parent=top)
                return
            c = self.driver_cfg
            c["car_hsv"] = sel["car"][2]
            c["target_hsv"] = sel["target"][2]
            self.save_driver_cfg()
            self._update_driver_lbl()
            top.destroy()
            self.q_status("Калибровка сохранена: машина HSV %s, зона HSV %s. "
                          "Если едет задом — галочка «Инвертировать курс»"
                          % (c["car_hsv"], c["target_hsv"]), GREEN)

        cv.bind("<ButtonPress-1>", on_click)
        row = tk.Frame(top, bg=BG)
        row.pack(pady=(0, 10))
        tk.Button(row, text="Сохранить", command=save, bg=PLAY_BG, fg="#dcffe9",
                  activebackground=PLAY_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0
                  ).pack(side="left", padx=4)
        tk.Button(row, text="Отмена", command=top.destroy, bg=BTN_BG, fg=FG,
                  activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=14, pady=4, cursor="hand2", bd=0
                  ).pack(side="left", padx=4)
        top.grab_set()

    def driver_pick_area(self):
        """Своё окно игры для водителя (по умолчанию берётся из «Зрения»)."""
        if vision_missing():
            self.q_status("Сначала установите:  pip install %s"
                          % " ".join(vision_missing()), RED)
            return
        cfg = dict(self.driver_cfg)
        cfg["area"] = None
        shot, ox, oy = self._grab_screen(cfg)
        if shot is None:
            return
        box = self._select_region_dialog(shot, "Область водителя — обведите окно игры")
        if not box:
            return
        x, y, w, h = box
        self.driver_cfg["area"] = {"left": ox + x, "top": oy + y,
                                   "width": w, "height": h}
        self.save_driver_cfg()
        self._update_driver_lbl()
        self.q_status("Область AI-водителя задана", GREEN)

    def driver_reset_area(self):
        self.driver_cfg["area"] = None
        self.save_driver_cfg()
        self._update_driver_lbl()

    def _update_driver_lbl(self):
        c = self.driver_cfg
        a = c.get("area")
        if a:
            self.d_area_lbl.config(text="Область: %d×%d от (%d, %d)"
                                   % (a.get("width", 0), a.get("height", 0),
                                      a.get("left", 0), a.get("top", 0)))
        else:
            self.d_area_lbl.config(text="Область: весь монитор")
        car = c.get("car_hsv")
        tgt = c.get("target_hsv")
        self.d_cal_lbl.config(
            text="Машина: %s   Зона: %s"
                 % (car if car else "не задана", tgt if tgt else "не задана"),
            fg=GREEN if (car and tgt) else AMBER)

    def driver_toggle_preview(self):
        """Окно «что видит водитель» — живой кадр с разметкой."""
        if self.drv_prev_win is not None and self.drv_prev_win.winfo_exists():
            self.drv_prev_win.destroy()
            self.drv_prev_win = None
            self.drv_prev_canvas = None
            self.driver_cfg["preview"] = False
            self.save_driver_cfg()
            return
        if not CV_OK:
            self.q_status("Превью требует opencv-python", AMBER)
            return
        self.driver_cfg["preview"] = True
        self.save_driver_cfg()
        w = tk.Toplevel(self.root)
        w.title("Что видит AI-водитель")
        w.configure(bg=BG)
        w.attributes("-topmost", True)
        self.drv_prev_canvas = tk.Canvas(w, width=484, height=300, bg="#000000",
                                         highlightthickness=1,
                                         highlightbackground=BORDER)
        self.drv_prev_canvas.pack(padx=8, pady=(8, 2))
        tk.Label(w, text="Жёлтый круг — зона парковки, зелёный — машина,\n"
                         "стрелка — курс, оранжевая линия — путь",
                 bg=BG, fg=MUTED, justify="left").pack(pady=(0, 8))
        self.drv_prev_win = w

    # ------------------------------------------------------------------- UI
    def q_status(self, text, color=FG, progress=None):
        self.status_q.put({"text": text, "color": color, "progress": progress})

    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=PANEL, foreground=FG, fieldbackground=PANEL2,
                     bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL)
        st.configure("Card.TLabelframe", background=PANEL, bordercolor=BORDER, relief="solid")
        st.configure("Card.TLabelframe.Label", background=PANEL, foreground=MUTED,
                     font=("Segoe UI", 9, "bold"))
        st.configure("TFrame", background=PANEL)
        st.configure("TLabel", background=PANEL, foreground=FG)
        st.configure("TCheckbutton", background=PANEL, foreground=FG, focuscolor=PANEL)
        st.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", FG)])
        st.configure("TSpinbox", background=PANEL2, foreground=FG, fieldbackground=PANEL2,
                     arrowcolor=FG, bordercolor=BORDER, buttonbackground=BTN_BG)
        st.configure("Horizontal.TScale", background=PANEL, troughcolor=PANEL2,
                     bordercolor=BORDER, lightcolor=BLUE, darkcolor=BLUE)
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                     foreground=FG, arrowcolor=FG, bordercolor=BORDER,
                     lightcolor=PANEL2, darkcolor=PANEL2)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
               foreground=[("readonly", FG)])
        st.configure("Treeview", background=PANEL2, foreground=FG, fieldbackground=PANEL2,
                     bordercolor=BORDER, rowheight=22)
        st.configure("Treeview.Heading", background=BTN_BG, foreground=MUTED, relief="flat")
        st.map("Treeview", background=[("selected", "#31506f")],
               foreground=[("selected", FG)])
        st.map("Treeview.Heading", background=[("active", BTN_ACTIVE)])

    # ------------------------------------------------------------ библиотеки
    def libs_save_cfg(self):
        try:
            os.makedirs(macro_dir(), exist_ok=True)
            with open(libs_cfg_path(), "w", encoding="utf-8") as f:
                json.dump(self.libs_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def libs_flags(self):
        self.libs_cfg["auto_install"] = bool(self.l_auto_inst_var.get())
        self.libs_cfg["auto_update"] = bool(self.l_auto_upd_var.get())
        self.libs_save_cfg()

    def _libs_log(self, line):
        try:
            self.libs_log.config(state="normal")
            self.libs_log.insert("end", str(line) + "\n")
            self.libs_log.see("end")
            self.libs_log.config(state="disabled")
        except Exception:
            pass

    def _libs_set_busy(self, busy):
        self._libs_busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_libs_check, self.btn_libs_install, self.btn_libs_update):
            try:
                b.config(state=state)
            except Exception:
                pass

    def _libs_refresh_ui(self):
        st = lib_status()
        miss = pick_missing(st)
        core_bad = any(s["core"] and not s["ok"] for s in st)
        self.libs_var.set(libs_report(st))
        self.libs_lbl.config(fg=GREEN if not miss else (RED if core_bad else AMBER))
        self.btn_libs_install.config(
            text="⬇ Установить недостающее" if miss else "✓ Всё установлено",
            state="disabled" if (self._libs_busy or not miss) else "normal")

    def libs_check(self):
        self._libs_refresh_ui()

    def libs_install(self):
        if self._libs_busy:
            return
        miss = pick_missing(lib_status())
        if not miss:
            self._libs_log("Все библиотеки уже установлены.")
            return
        self._libs_start(miss, upgrade=False)

    def libs_upgrade(self):
        if self._libs_busy:
            return
        self._libs_start([s["pip"] for s in lib_status()], upgrade=True)

    def _libs_start(self, pips, upgrade):
        """pip в фоновом потоке; вывод — через libs_log_q, итог — через cmd_q."""
        self._libs_set_busy(True)
        self._libs_log("— %s: %s —" % ("Обновление" if upgrade else "Установка",
                                       " ".join(pips)))

        def worker():
            ok = run_pip(build_pip_cmd(pips, upgrade=upgrade),
                         on_line=lambda s: self.libs_log_q.put(s))
            _import_libs()
            self.cmd_q.put(("libs_done", ok))

        threading.Thread(target=worker, daemon=True).start()

    def _libs_finish(self, ok):
        self._libs_log("Результат: %s" % ("успешно" if ok else
                       "не удалось — попробуйте вручную:  %s" % MANUAL_PIP_CMD))
        if PYNPUT_OK and not self._pynput_at_start:
            self._libs_log("pynput появился — ПЕРЕЗАПУСТИТЕ программу, чтобы "
                           "заработали запись и горячие клавиши.")
            self._pynput_at_start = True
        self._libs_refresh_ui()
        self._libs_set_busy(False)

    def _build_ui(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=10)

        # --- заголовок и статусная строка ---
        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, bg=BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        self.dot = tk.Label(head, text="●", bg=BG, fg=MUTED, font=("Segoe UI", 14))
        self.dot.pack(side="right")
        self.status_lbl = tk.Label(wrap, text="Готов", bg=BG, fg=MUTED,
                                   font=("Segoe UI", 10), anchor="w")
        self.status_lbl.pack(fill="x", pady=(2, 8))

        if not PYNPUT_OK:
            tk.Label(wrap, text="Библиотека pynput не найдена — запись и воспроизведение недоступны.\n"
                                "Нажмите «⬇ Установить недостающее» в карточке «БИБЛИОТЕКИ» "
                                "(ниже), затем перезапустите программу.",
                     bg="#5c2325", fg="#ffd7d9", justify="center", pady=8).pack(fill="x", pady=(0, 8))

        # --- карточка ЗАПИСЬ ---
        rec = ttk.Labelframe(wrap, text=" ЗАПИСЬ ", style="Card.TLabelframe")
        rec.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(rec, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=8)

        checks = tk.Frame(inner, bg=PANEL)
        checks.pack(fill="x")
        self.v_moves = tk.BooleanVar(value=True)
        self.v_clicks = tk.BooleanVar(value=True)
        self.v_keys = tk.BooleanVar(value=True)
        self.v_scroll = tk.BooleanVar(value=False)
        for text, var, attr in (("Движение мыши", self.v_moves, "rec_moves"),
                                ("Клики мыши", self.v_clicks, "rec_clicks"),
                                ("Клавиатура", self.v_keys, "rec_keys"),
                                ("Скролл", self.v_scroll, "rec_scroll")):
            ttk.Checkbutton(checks, text=text, variable=var,
                            command=lambda v=var, a=attr: setattr(self, a, v.get())
                            ).pack(side="left", padx=(0, 14))

        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(8, 2))
        self.btn_rec = tk.Button(row, text="●  Начать запись  (F9)", command=self.toggle_record,
                                 bg=REC_BG, fg="#ffe3e4", activebackground=REC_ACTIVE,
                                 activeforeground="white", relief="flat", padx=14, pady=6,
                                 font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0)
        self.btn_rec.pack(side="left")
        tk.Label(row, text="Хоткеи работают глобально — окно можно свернуть",
                 bg=PANEL, fg=MUTED).pack(side="left", padx=10)
        self.stats_lbl = tk.Label(inner, text=self._stats_text(0.0),
                                  bg=PANEL, fg=MUTED, anchor="w")
        self.stats_lbl.pack(fill="x", pady=(4, 0))

        # --- карточка ВОСПРОИЗВЕДЕНИЕ ---
        play = ttk.Labelframe(wrap, text=" ВОСПРОИЗВЕДЕНИЕ ", style="Card.TLabelframe")
        play.pack(fill="x", pady=(0, 8))
        pin = tk.Frame(play, bg=PANEL)
        pin.pack(fill="x", padx=10, pady=8)

        grid = tk.Frame(pin, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="Скорость:", bg=PANEL, fg=FG).grid(row=0, column=0, sticky="w", pady=3)
        self.speed_var = tk.DoubleVar(value=1.0)
        ttk.Scale(grid, from_=0.1, to=4.0, variable=self.speed_var,
                  command=self._on_speed, style="Horizontal.TScale"
                  ).grid(row=0, column=1, sticky="ew", padx=8)
        self.speed_val = tk.Label(grid, text="1.00x", bg=PANEL, fg=BLUE, width=7, anchor="e")
        self.speed_val.grid(row=0, column=2)

        tk.Label(grid, text="Повторы (0 = ∞):", bg=PANEL, fg=FG).grid(row=1, column=0, sticky="w", pady=3)
        p11 = tk.Frame(grid, bg=PANEL); p11.grid(row=1, column=1, sticky="w", padx=8)
        self.repeats_var = tk.StringVar(value="1")
        ttk.Spinbox(p11, from_=0, to=9999, textvariable=self.repeats_var, width=7).pack(side="left")
        tk.Label(p11, text="   Джиттер ±%:", bg=PANEL, fg=FG).pack(side="left")
        self.jitter_var = tk.StringVar(value="0")
        ttk.Spinbox(p11, from_=0, to=50, textvariable=self.jitter_var, width=5).pack(side="left")
        tk.Label(p11, text="   (0 = точно как записано)", bg=PANEL, fg=MUTED).pack(side="left")

        tk.Label(grid, text="Задержка старта, с:", bg=PANEL, fg=FG).grid(row=2, column=0, sticky="w", pady=3)
        p21 = tk.Frame(grid, bg=PANEL); p21.grid(row=2, column=1, sticky="w", padx=8)
        self.delay_var = tk.StringVar(value="3.0")
        ttk.Spinbox(p21, from_=0, to=30, increment=0.5, textvariable=self.delay_var,
                    width=7).pack(side="left")
        tk.Label(p21, text="   Пауза между повторами, с:", bg=PANEL, fg=FG).pack(side="left")
        self.pause_var = tk.StringVar(value="1.0")
        ttk.Spinbox(p21, from_=0, to=60, increment=0.5, textvariable=self.pause_var,
                    width=7).pack(side="left")

        brow = tk.Frame(pin, bg=PANEL)
        brow.pack(fill="x", pady=(8, 0))
        self.btn_play = tk.Button(brow, text="▶  Воспроизвести  (F10)", command=self.start_play,
                                  bg=PLAY_BG, fg="#dcffe9", activebackground=PLAY_ACTIVE,
                                  activeforeground="white", relief="flat", padx=14, pady=6,
                                  font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0)
        self.btn_play.pack(side="left")
        self.btn_stop = tk.Button(brow, text="■  Стоп  (F12)", command=self.request_stop,
                                  bg=STOP_BG, fg=FG, activebackground=STOP_ACTIVE,
                                  activeforeground="white", relief="flat", padx=14, pady=6,
                                  font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0)
        self.btn_stop.pack(side="left", padx=8)
        self.prog_var = tk.StringVar(value="—")
        tk.Label(brow, textvariable=self.prog_var, bg=PANEL, fg=MUTED).pack(side="left", padx=8)

        # --- карточка ПРОФИЛИ ---
        prof = ttk.Labelframe(wrap, text=" ПРОФИЛИ (macros/*.json) ", style="Card.TLabelframe")
        prof.pack(fill="x", pady=(0, 8))
        pfin = tk.Frame(prof, bg=PANEL)
        pfin.pack(fill="x", padx=10, pady=8)

        self.name_var = tk.StringVar(value=self.macro_name)
        tk.Label(pfin, text="Текущий:", bg=PANEL, fg=MUTED).pack(side="left")
        tk.Label(pfin, textvariable=self.name_var, bg=PANEL, fg=FG).pack(side="left", padx=(6, 0))

        prow = tk.Frame(prof, bg=PANEL)
        prow.pack(fill="x", pady=(6, 0))
        self.profile_box = ttk.Combobox(prow, state="readonly", width=28)
        self.profile_box.pack(side="left")
        for txt, cmd in (("Обновить", self.refresh_profiles),
                         ("Загрузить", self.load_profile),
                         ("Сохранить как…", self.save_profile),
                         ("Удалить", self.delete_profile)):
            tk.Button(prow, text=txt, command=cmd, bg=BTN_BG, fg=FG,
                      activebackground=BTN_ACTIVE, activeforeground="white",
                      relief="flat", padx=10, pady=4, cursor="hand2", bd=0).pack(side="left", padx=(6, 0))
        self.refresh_profiles()

        # --- карточка ПЛЕЙЛИСТ ---
        ql = ttk.Labelframe(wrap, text=" ПЛЕЙЛИСТ УРОВНЕЙ (каждый макрос играется N раз) ",
                            style="Card.TLabelframe")
        ql.pack(fill="x", pady=(0, 8))
        qin = tk.Frame(ql, bg=PANEL)
        qin.pack(fill="x", padx=10, pady=8)

        qrow = tk.Frame(qin, bg=PANEL)
        qrow.pack(fill="x")
        tk.Label(qrow, text="Повторов на макрос:", bg=PANEL, fg=FG).pack(side="left")
        self.q_repeats_var = tk.StringVar(value="2")
        ttk.Spinbox(qrow, from_=1, to=99, textvariable=self.q_repeats_var,
                    width=4).pack(side="left", padx=(6, 12))
        for txt, cmd in (("+ В очередь", self.add_to_queue),
                         ("- Убрать", self.remove_from_queue),
                         ("Очистить", self.clear_queue)):
            tk.Button(qrow, text=txt, command=cmd, bg=BTN_BG, fg=FG,
                      activebackground=BTN_ACTIVE, activeforeground="white",
                      relief="flat", padx=10, pady=4, cursor="hand2", bd=0
                      ).pack(side="left", padx=(0, 6))

        qbox = tk.Frame(qin, bg=PANEL)
        qbox.pack(fill="x", pady=(6, 0))
        self.queue_list = tk.Listbox(qbox, height=5, bg=PANEL2, fg=FG,
                                     selectbackground="#31506f", selectforeground=FG,
                                     relief="flat", highlightthickness=1,
                                     highlightbackground=BORDER, activestyle="none")
        qsbr = ttk.Scrollbar(qbox, orient="vertical", command=self.queue_list.yview)
        self.queue_list.configure(yscrollcommand=qsbr.set)
        self.queue_list.pack(side="left", fill="x", expand=True)
        qsbr.pack(side="right", fill="y")

        qopts = tk.Frame(qin, bg=PANEL)
        qopts.pack(fill="x", pady=(6, 0))
        self.q_loop_var = tk.BooleanVar(value=False)
        self.use_queue_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(qopts, text="По кругу (после последнего — снова первый)",
                        variable=self.q_loop_var,
                        command=self._save_queue).pack(side="left")
        ttk.Checkbutton(qopts, text="F10 запускает плейлист (если очередь не пуста)",
                        variable=self.use_queue_var,
                        command=self._save_queue).pack(side="left", padx=(14, 0))

        self.sess_var = tk.StringVar(value="Сессия: —")
        tk.Label(qin, textvariable=self.sess_var, bg=PANEL, fg=MUTED,
                 anchor="w").pack(fill="x", pady=(4, 0))

        # --- карточка ЗРЕНИЕ ---
        vis = ttk.Labelframe(wrap, text=" ЗРЕНИЕ — РОБОТ САМ ВИДИТ ЭКРАН (F11) ",
                             style="Card.TLabelframe")
        vis.pack(fill="x", pady=(0, 8))
        vin = tk.Frame(vis, bg=PANEL)
        vin.pack(fill="x", padx=10, pady=8)

        _vmiss = vision_missing()
        if _vmiss:
            tk.Label(vin, text="Нет библиотек: %s\nНажмите «⬇ Установить недостающее» "
                               "в карточке «БИБЛИОТЕКИ» (ниже) или выполните в cmd:\n"
                               "pip install %s"
                     % (", ".join(_vmiss), " ".join(_vmiss)),
                     bg="#5c2325", fg="#ffd7d9", justify="left", pady=6).pack(fill="x", pady=(0, 6))

        vrow0 = tk.Frame(vin, bg=PANEL)
        vrow0.pack(fill="x")
        self.btn_vision = tk.Button(vrow0, text="👁  Запустить зрение  (F11)",
                                    command=self.toggle_vision,
                                    bg=PLAY_BG, fg="#dcffe9", activebackground=PLAY_ACTIVE,
                                    activeforeground="white", relief="flat", padx=14, pady=6,
                                    font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0)
        self.btn_vision.pack(side="left")
        tk.Button(vrow0, text="👁 Превью", command=self.vision_toggle_preview,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=10, pady=6, cursor="hand2", bd=0).pack(side="left", padx=(8, 0))
        self.vision_status_lbl = tk.Label(vrow0, text="проверок: 0 • действий: 0",
                                          bg=PANEL, fg=MUTED)
        self.vision_status_lbl.pack(side="left", padx=10)

        vset = tk.Frame(vin, bg=PANEL)
        vset.pack(fill="x", pady=(8, 0))
        tk.Label(vset, text="Интервал проверки, с:", bg=PANEL, fg=FG).pack(side="left")
        self.vision_interval_var = tk.StringVar(value=str(self.vision_cfg["interval"]))
        ttk.Spinbox(vset, from_=0.1, to=5.0, increment=0.1,
                    textvariable=self.vision_interval_var, width=5,
                    command=self._vision_apply_ui).pack(side="left", padx=(4, 12))
        tk.Label(vset, text="Монитор:", bg=PANEL, fg=FG).pack(side="left")
        self.vision_mon_var = tk.StringVar(value=str(self.vision_cfg["monitor"]))
        self.vision_mon_box = ttk.Combobox(vset, textvariable=self.vision_mon_var,
                                           values=["1", "2", "3", "4"], width=3)
        self.vision_mon_box.pack(side="left", padx=(4, 12))
        self.v_multi_var = tk.BooleanVar(value=self.vision_cfg["multiscale"])
        ttk.Checkbutton(vset, text="Разные масштабы (медленнее, но надёжнее)",
                        variable=self.v_multi_var, command=self._vision_flags).pack(side="left")
        self.v_clicks_play_var = tk.BooleanVar(value=self.vision_cfg["clicks_during_play"])
        ttk.Checkbutton(vin, text="Клики правил во время макроса (нужно для «Заново» после аварии)",
                        variable=self.v_clicks_play_var,
                        command=self._vision_flags).pack(anchor="w", pady=(4, 0))

        vrow2 = tk.Frame(vin, bg=PANEL)
        vrow2.pack(fill="x", pady=(8, 0))
        for txt, cmd in (("＋ Снять шаблон", self.vision_new_template),
                         ("✎ Править", self.vision_edit_rule),
                         ("▲", lambda: self.vision_move_rule(-1)),
                         ("▼", lambda: self.vision_move_rule(1)),
                         ("✕ Удалить", self.vision_delete_rule),
                         ("⚡ Тест", self.vision_test)):
            tk.Button(vrow2, text=txt, command=cmd, bg=BTN_BG, fg=FG,
                      activebackground=BTN_ACTIVE, activeforeground="white",
                      relief="flat", padx=10, pady=4, cursor="hand2", bd=0).pack(side="left", padx=(0, 6))

        varea = tk.Frame(vin, bg=PANEL)
        varea.pack(fill="x", pady=(6, 0))
        self.vision_area_lbl = tk.Label(varea, text="Область поиска: весь монитор",
                                        bg=PANEL, fg=MUTED)
        self.vision_area_lbl.pack(side="left")
        tk.Button(varea, text="Выбрать окно игры", command=self.vision_pick_area,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=8, pady=2, cursor="hand2", bd=0).pack(side="left", padx=(8, 4))
        tk.Button(varea, text="Сброс", command=self.vision_reset_area,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=8, pady=2, cursor="hand2", bd=0).pack(side="left")

        vbox = tk.Frame(vin, bg=PANEL)
        vbox.pack(fill="x", pady=(6, 0))
        self.vision_list = tk.Listbox(vbox, height=4, bg=PANEL2, fg=FG,
                                      selectbackground="#31506f", selectforeground=FG,
                                      relief="flat", highlightthickness=1,
                                      highlightbackground=BORDER, activestyle="none")
        vsbr = ttk.Scrollbar(vbox, orient="vertical", command=self.vision_list.yview)
        self.vision_list.configure(yscrollcommand=vsbr.set)
        self.vision_list.pack(side="left", fill="x", expand=True)
        vsbr.pack(side="right", fill="y")

        # --- карточка AI-ВОДИТЕЛЬ ---
        drv = ttk.Labelframe(wrap, text=" 🤖 AI-ВОДИТЕЛЬ — РОБОТ САМ ВЕДЁТ МАШИНУ (F8) ",
                             style="Card.TLabelframe")
        drv.pack(fill="x", pady=(0, 8))
        din = tk.Frame(drv, bg=PANEL)
        din.pack(fill="x", padx=10, pady=8)

        tk.Label(din, text="Экспериментальный режим! Видит машину и зону парковки по цвету "
                           "и сам жмёт газ/руль. Лучше всего — камера «сверху». "
                           "Автоигрушки в онлайн-играх могут нарушать правила проекта.",
                 bg="#4d3a15", fg="#ffe9b8", justify="left",
                 wraplength=660).pack(fill="x", pady=(0, 6))

        drow0 = tk.Frame(din, bg=PANEL)
        drow0.pack(fill="x")
        self.btn_driver = tk.Button(drow0, text="🤖  Запустить AI-водителя  (F8)",
                                    command=self.toggle_driver,
                                    bg=PLAY_BG, fg="#dcffe9", activebackground=PLAY_ACTIVE,
                                    activeforeground="white", relief="flat", padx=14, pady=6,
                                    font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0)
        self.btn_driver.pack(side="left")
        tk.Button(drow0, text="👁 Превью", command=self.driver_toggle_preview,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=10, pady=6, cursor="hand2", bd=0).pack(side="left", padx=(8, 0))
        tk.Button(drow0, text="🎯 Калибровка цветов", command=self.driver_calibrate,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=10, pady=6, cursor="hand2", bd=0).pack(side="left", padx=(8, 0))
        self.d_cal_lbl = tk.Label(drow0, text="Машина: —   Зона: —", bg=PANEL, fg=AMBER)
        self.d_cal_lbl.pack(side="left", padx=10)

        self.driver_status_lbl = tk.Label(din, text="—", bg=PANEL, fg=MUTED, anchor="w")
        self.driver_status_lbl.pack(fill="x", pady=(4, 0))

        # клавиши управления
        dk = tk.Frame(din, bg=PANEL)
        dk.pack(fill="x", pady=(6, 0))
        self.d_gas_var = tk.StringVar(value=self.driver_cfg["keys"]["gas"])
        self.d_brake_var = tk.StringVar(value=self.driver_cfg["keys"]["brake"])
        self.d_left_var = tk.StringVar(value=self.driver_cfg["keys"]["left"])
        self.d_right_var = tk.StringVar(value=self.driver_cfg["keys"]["right"])
        for lbl, var in (("Газ:", self.d_gas_var), ("Тормоз:", self.d_brake_var),
                         ("Влево:", self.d_left_var), ("Вправо:", self.d_right_var)):
            tk.Label(dk, text=lbl, bg=PANEL, fg=FG).pack(side="left")
            ttk.Entry(dk, textvariable=var, width=4).pack(side="left", padx=(3, 10))
        tk.Label(dk, text="(как в игре: WASD или стрелки — up/down/left/right)",
                 bg=PANEL, fg=MUTED).pack(side="left")

        # параметры вождения
        dp = tk.Frame(din, bg=PANEL)
        dp.pack(fill="x", pady=(6, 0))
        tk.Label(dp, text="Порог парковки, % диагонали:", bg=PANEL, fg=FG).pack(side="left")
        self.d_stop_var = tk.StringVar(value="%.1f" % (self.driver_cfg["stop_dist_frac"] * 100))
        ttk.Spinbox(dp, from_=0.5, to=30, increment=0.5, textvariable=self.d_stop_var,
                    width=5).pack(side="left", padx=(3, 12))
        tk.Label(dp, text="Мёртвая зона руля, °:", bg=PANEL, fg=FG).pack(side="left")
        self.d_dead_var = tk.StringVar(value="%g" % self.driver_cfg["steer_deadzone"])
        ttk.Spinbox(dp, from_=1, to=60, increment=1, textvariable=self.d_dead_var,
                    width=4).pack(side="left", padx=(3, 12))
        tk.Label(dp, text="Макс. скорость, px/с:", bg=PANEL, fg=FG).pack(side="left")
        self.d_maxsp_var = tk.StringVar(value="%g" % self.driver_cfg["max_speed_px"])
        ttk.Spinbox(dp, from_=30, to=3000, increment=25, textvariable=self.d_maxsp_var,
                    width=6).pack(side="left", padx=(3, 0))

        # параметры цвета
        dc = tk.Frame(din, bg=PANEL)
        dc.pack(fill="x", pady=(6, 0))
        tk.Label(dc, text="Допуск цвета машины:", bg=PANEL, fg=FG).pack(side="left")
        self.d_car_tol_var = tk.StringVar(value=str(self.driver_cfg["car_tol"]))
        ttk.Spinbox(dc, from_=1, to=90, textvariable=self.d_car_tol_var,
                    width=4).pack(side="left", padx=(3, 12))
        tk.Label(dc, text="Допуск цвета зоны:", bg=PANEL, fg=FG).pack(side="left")
        self.d_tgt_tol_var = tk.StringVar(value=str(self.driver_cfg["target_tol"]))
        ttk.Spinbox(dc, from_=1, to=90, textvariable=self.d_tgt_tol_var,
                    width=4).pack(side="left", padx=(3, 12))
        tk.Label(dc, text="Мин. площадь, %:", bg=PANEL, fg=FG).pack(side="left")
        self.d_minf_var = tk.StringVar(value="%.2f" % (self.driver_cfg["min_frac"] * 100))
        ttk.Spinbox(dc, from_=0.01, to=50, increment=0.01, textvariable=self.d_minf_var,
                    width=5).pack(side="left", padx=(3, 12))
        tk.Label(dc, text="Монитор:", bg=PANEL, fg=FG).pack(side="left")
        self.d_mon_var = tk.StringVar(value=str(self.driver_cfg["monitor"]))
        ttk.Combobox(dc, textvariable=self.d_mon_var, values=["1", "2", "3", "4"],
                     width=3).pack(side="left", padx=(3, 0))

        dchk = tk.Frame(din, bg=PANEL)
        dchk.pack(fill="x", pady=(6, 0))
        self.d_inv_var = tk.BooleanVar(value=self.driver_cfg["invert_heading"])
        ttk.Checkbutton(dchk, text="Инвертировать курс (если робот едет задом наперёд)",
                        variable=self.d_inv_var).pack(side="left")

        darea = tk.Frame(din, bg=PANEL)
        darea.pack(fill="x", pady=(6, 0))
        self.d_area_lbl = tk.Label(darea, text="Область: весь монитор", bg=PANEL, fg=MUTED)
        self.d_area_lbl.pack(side="left")
        tk.Button(darea, text="Выбрать окно игры", command=self.driver_pick_area,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=8, pady=2, cursor="hand2", bd=0).pack(side="left", padx=(8, 4))
        tk.Button(darea, text="Сброс", command=self.driver_reset_area,
                  bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE, activeforeground="white",
                  relief="flat", padx=8, pady=2, cursor="hand2", bd=0).pack(side="left")

        tk.Label(din, text="Калибровка: снимок экрана → клик по кузову машины → клик по жёлтой зоне. "
                           "Зону ищет по цвету разметки (в CPM 2 она ярко-жёлтая). "
                           "После аварии пусть «Зрение» (F11) жмёт «Заново» по шаблону — "
                           "водитель продолжает ехать.",
                 bg=PANEL, fg=MUTED, justify="left",
                 wraplength=660).pack(fill="x", pady=(6, 0))

        # --- карточка БИБЛИОТЕКИ (v2.2) ---
        libf = ttk.Labelframe(wrap, text=" БИБЛИОТЕКИ — ПРОВЕРКА, АВТОУСТАНОВКА, ОБНОВЛЕНИЕ ",
                              style="Card.TLabelframe")
        libf.pack(fill="x", pady=(0, 8))
        libin = tk.Frame(libf, bg=PANEL)
        libin.pack(fill="x", padx=10, pady=8)

        self.libs_var = tk.StringVar(value=libs_report())
        self.libs_lbl = tk.Label(libin, textvariable=self.libs_var, bg=PANEL,
                                 fg=GREEN if not vision_missing() else RED,
                                 anchor="w", justify="left")
        self.libs_lbl.pack(fill="x")

        lrow = tk.Frame(libin, bg=PANEL)
        lrow.pack(fill="x", pady=(6, 0))
        self.btn_libs_check = tk.Button(lrow, text="🔎 Проверить", command=self.libs_check,
                                        bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE,
                                        activeforeground="white", relief="flat",
                                        padx=10, pady=4, cursor="hand2", bd=0)
        self.btn_libs_check.pack(side="left")
        self.btn_libs_install = tk.Button(lrow, text="⬇ Установить недостающее",
                                          command=self.libs_install, bg=BTN_BG, fg=FG,
                                          activebackground=BTN_ACTIVE,
                                          activeforeground="white", relief="flat",
                                          padx=10, pady=4, cursor="hand2", bd=0)
        self.btn_libs_install.pack(side="left", padx=(6, 0))
        self.btn_libs_update = tk.Button(lrow, text="🔄 Обновить всё", command=self.libs_upgrade,
                                         bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE,
                                         activeforeground="white", relief="flat",
                                         padx=10, pady=4, cursor="hand2", bd=0)
        self.btn_libs_update.pack(side="left", padx=(6, 0))

        lchk = tk.Frame(libin, bg=PANEL)
        lchk.pack(fill="x", pady=(6, 0))
        self.l_auto_inst_var = tk.BooleanVar(value=self.libs_cfg["auto_install"])
        ttk.Checkbutton(lchk, text="Авто-установка недостающего при запуске",
                        variable=self.l_auto_inst_var,
                        command=self.libs_flags).pack(side="left")
        self.l_auto_upd_var = tk.BooleanVar(value=self.libs_cfg["auto_update"])
        ttk.Checkbutton(lchk, text="Обновлять при запуске (медленнее, нужен интернет)",
                        variable=self.l_auto_upd_var,
                        command=self.libs_flags).pack(side="left", padx=(12, 0))

        self.libs_log = tk.Text(libin, height=4, bg=PANEL2, fg=MUTED, relief="flat",
                                highlightthickness=1, highlightbackground=BORDER,
                                font=("Consolas", 8), state="disabled")
        self.libs_log.pack(fill="x", pady=(6, 0))

        # --- карточка СОБЫТИЯ ---
        evf = ttk.Labelframe(wrap, text=" СОБЫТИЯ (первые %d) " % MAX_TREE_ROWS,
                             style="Card.TLabelframe")
        evf.pack(fill="both", expand=True, pady=(0, 8))
        ein = tk.Frame(evf, bg=PANEL)
        ein.pack(fill="both", expand=True, padx=10, pady=8)

        cols = ("num", "t", "type", "det")
        self.tree = ttk.Treeview(ein, columns=cols, show="headings", height=6)
        self.tree.heading("num", text="№")
        self.tree.heading("t", text="время, с")
        self.tree.heading("type", text="тип")
        self.tree.heading("det", text="детали")
        self.tree.column("num", width=52, anchor="e", stretch=False)
        self.tree.column("t", width=72, anchor="e", stretch=False)
        self.tree.column("type", width=84, anchor="w", stretch=False)
        self.tree.column("det", anchor="w")
        sb = ttk.Scrollbar(ein, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("move", foreground=MUTED)
        self.tree.tag_configure("click", foreground=AMBER)
        self.tree.tag_configure("key", foreground=GREEN)
        self.tree.tag_configure("scroll", foreground=BLUE)

        tk.Label(wrap, text="F8 — AI-водитель   •   F9 — запись   •   F10 — воспроизведение   •   "
                            "F11 — зрение   •   F12 — экстренный стоп\n"
                            "Профили: macros/*.json   •   Плейлист: macros/playlist.json   •   "
                            "Шаблоны: templates/*.png   •   Правила: macros/vision.json   •   "
                            "Водитель: macros/driver.json   •   Библиотеки: macros/libs.json",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left").pack(fill="x")

        self._load_queue()
        self._render_vision_rules()
        self._update_driver_lbl()
        self._libs_refresh_ui()
        try:
            with mss.mss() as _s:
                _cnt = len(_s.monitors)
            if _cnt > 2:
                self.vision_mon_box["values"] = [str(i) for i in range(1, _cnt)]
        except Exception:
            pass

    def _on_speed(self, val):
        try:
            self.speed_val.config(text="%.2fx" % float(val))
        except (ValueError, TypeError):
            pass

    def _stats_text(self, dur):
        s = self.stats
        return ("Событий: %d    Длительность: %.1f с    |    "
                "Движения: %d    Клики: %d    Клавиши: %d    Скролл: %d"
                % (sum(s.values()), dur, s.get("move", 0), s.get("click", 0),
                   s.get("key", 0), s.get("scroll", 0)))

    def _clear_tree(self):
        self.tree.delete(*self.tree.get_children())

    def _tree_insert(self, idx, ev):
        et = ev.get("type", "?")
        t = "%.2f" % float(ev.get("t", 0.0) or 0.0)
        if et == "move":
            det = "x=%d   y=%d" % (ev.get("x", 0), ev.get("y", 0))
        elif et == "click":
            det = "%s %s   (%d, %d)" % ("нажатие" if ev.get("pressed") else "отпускание",
                                        BUTTON_RUS.get(ev.get("button", "left"),
                                                       str(ev.get("button"))),
                                        ev.get("x", 0), ev.get("y", 0))
        elif et == "scroll":
            det = "dx=%+d   dy=%+d" % (ev.get("dx", 0), ev.get("dy", 0))
        elif et == "key":
            det = "%s %s" % ("нажата" if ev.get("action") == "press" else "отпущена",
                             key_display(ev.get("key") or {}))
        else:
            det = str(ev)
        self.tree.insert("", "end", values=(idx + 1, t, TYPE_RUS.get(et, et), det),
                         tags=(et,))

    def _refresh_buttons(self):
        self.btn_rec.config(text="■  Остановить запись  (F9)" if self.recording
                                else "●  Начать запись  (F9)",
                            bg=REC_ACTIVE if self.recording else REC_BG,
                            state="disabled" if self.playing else "normal")
        self.btn_play.config(state="disabled" if (self.playing or self.recording or not PYNPUT_OK)
                             else "normal")
        self.btn_stop.config(state="normal" if (self.playing or self.recording) else "disabled")
        self.dot.config(fg=RED if self.recording else (GREEN if self.playing else MUTED))
        _vok = not vision_missing()
        self.btn_vision.config(
            text="■  Остановить зрение  (F11)" if self.vision_on
                 else "👁  Запустить зрение  (F11)",
            bg=STOP_BG if self.vision_on else PLAY_BG,
            fg=FG if self.vision_on else "#dcffe9",
            activebackground=STOP_ACTIVE if self.vision_on else PLAY_ACTIVE,
            state="disabled" if (not _vok or self.recording) else "normal")
        self.btn_driver.config(
            text="■  Остановить AI-водителя  (F8)" if self.driver_on
                 else "🤖  Запустить AI-водителя  (F8)",
            bg=STOP_BG if self.driver_on else PLAY_BG,
            fg=FG if self.driver_on else "#dcffe9",
            activebackground=STOP_ACTIVE if self.driver_on else PLAY_ACTIVE,
            state="disabled" if (not _vok or self.recording or self.playing) else "normal")

    # ------------------------------------------------------------- poller
    def _poll(self):
        try:
            while True:
                cmd = self.cmd_q.get_nowait()
                if cmd == "toggle_record":
                    self.toggle_record()
                elif cmd == "start_play":
                    self.start_play()
                elif cmd == "toggle_vision":
                    self.toggle_vision()
                elif cmd == "toggle_driver":
                    self.toggle_driver()
                elif isinstance(cmd, tuple) and cmd and cmd[0] == "libs_done":
                    self._libs_finish(cmd[1])
        except queue.Empty:
            pass

        try:
            while True:
                self._libs_log(self.libs_log_q.get_nowait())
        except queue.Empty:
            pass

        try:
            while True:
                msg = self.status_q.get_nowait()
                self.status_lbl.config(text=msg.get("text", ""), fg=msg.get("color", FG))
                if msg.get("progress"):
                    self.prog_var.set(msg["progress"])
        except queue.Empty:
            pass

        if self.recording:
            self.stats_lbl.config(text=self._stats_text(time.perf_counter() - self.t0))
        else:
            self.stats_lbl.config(text=self._stats_text(self.duration))

        with self.ev_lock:
            total = len(self.events)
            pending = self.events[self._rows_shown:MAX_TREE_ROWS]
            start_idx = self._rows_shown
            self._rows_shown = min(total, MAX_TREE_ROWS)
        for off, ev in enumerate(pending):
            self._tree_insert(start_idx + off, ev)

        if self.playing and self.play_prog:
            pp = self.play_prog
            if pp["jobs"] > 1:
                self.prog_var.set("Плейлист %d/%d: %s   повтор %d/%d   действие %d/%d"
                                  % (pp["idx"], pp["jobs"], pp["name"],
                                     pp["rep"], pp["reps"], pp["done"], pp["total"]))
            else:
                rep_s = "%d/∞" % pp["rep"] if pp["reps"] <= 0 else "%d/%d" % (pp["rep"], pp["reps"])
                self.prog_var.set("Повтор %s   действие %d/%d" % (rep_s, pp["done"], pp["total"]))
            if self.sess_started:
                self.sess_var.set(self._session_text())

        # --- зрение: статус и живое превью ---
        vs = self.vision_state
        if self.vision_on:
            found_txt = ", ".join("%s %d%%" % (f["name"], round(f["score"] * 100))
                                  for f in vs.get("found", [])[:3]) or "—"
            self.vision_status_lbl.config(
                text="проверок: %d • действий: %d • вижу: %s"
                     % (vs.get("checks", 0), vs.get("actions", 0), found_txt), fg=BLUE)
        if (self.preview_win is not None and self.preview_win.winfo_exists()
                and vs.get("preview") and time.time() - self._preview_ts > 0.25):
            self._preview_ts = time.time()
            try:
                self._preview_img = tk.PhotoImage(data=vs["preview"],
                                                  master=self.preview_win)
                self.preview_canvas.config(width=self._preview_img.width(),
                                           height=self._preview_img.height())
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(0, 0, image=self._preview_img,
                                                 anchor="nw")
            except Exception:
                pass

        # --- AI-водитель: статус и живое превью ---
        ds = self.driver_state
        if self.driver_on:
            mode_rus = DRIVER_MODE_RUS.get(ds.get("mode"), "—")
            self.driver_status_lbl.config(
                text="режим: %s • машина: %s • цель: %s • дистанция %d%% • "
                     "руль %+d° • скорость %d px/с • кадров: %d%s"
                     % (mode_rus,
                        "да" if ds.get("car") else "НЕТ",
                        "да" if ds.get("target") else "НЕТ",
                        round(float(ds.get("dist", 1.0)) * 100),
                        round(float(ds.get("err", 0.0))),
                        round(float(ds.get("speed", 0.0))),
                        ds.get("checks", 0),
                        (" • " + ds["msg"]) if ds.get("msg") else ""),
                fg=BLUE)
        if (self.drv_prev_win is not None and self.drv_prev_win.winfo_exists()
                and ds.get("preview") and time.time() - self._drv_prev_ts > 0.25):
            self._drv_prev_ts = time.time()
            try:
                self._drv_prev_img = tk.PhotoImage(data=ds["preview"],
                                                   master=self.drv_prev_win)
                self.drv_prev_canvas.config(width=self._drv_prev_img.width(),
                                            height=self._drv_prev_img.height())
                self.drv_prev_canvas.delete("all")
                self.drv_prev_canvas.create_image(0, 0, image=self._drv_prev_img,
                                                  anchor="nw")
            except Exception:
                pass

        self._refresh_buttons()
        self.root.after(80, self._poll)

    # ------------------------------------------------------------- выход
    def on_close(self):
        try:
            self.vision_on = False
            self.driver_on = False
            self._driver_release_now()
            self.stop_flag.set()
            self.recording = False
            self.playing = False
            if PYNPUT_OK:
                self._mouse_listener.stop()
                self._kb_listener.stop()
        finally:
            self.root.destroy()


# ------------------------------------------------- окно проверки при запуске
def libs_splash(miss, cfg):
    """Окно «Проверка библиотек» перед главным окном: показывает статус,
    при auto_install сама ставит недостающее, при auto_update обновляет всё.
    Возвращает True, если pip реально запускался."""
    ran = {"pip": False}
    root = tk.Tk()
    root.title("%s — проверка библиотек" % APP_NAME)
    root.configure(bg=BG)
    root.geometry("640x470")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    tk.Label(root, text="Проверка библиотек", bg=BG, fg=FG,
             font=("Segoe UI", 14, "bold")).pack(pady=(14, 2))
    tk.Label(root, text="pynput — запись и клавиши;   numpy, opencv-python, mss — "
                        "зрение и AI-водитель.",
             bg=BG, fg=MUTED, justify="left").pack(fill="x", padx=18)

    rows = tk.Frame(root, bg=BG)
    rows.pack(fill="x", padx=18, pady=8)

    def refresh_rows():
        for w in rows.winfo_children():
            w.destroy()
        for s in lib_status():
            if s["ok"]:
                txt = "✓  установлен" + (("   " + s["version"]) if s["version"] else "")
                col = GREEN
            else:
                txt, col = "✗  не установлен", RED
            line = tk.Frame(rows, bg=BG)
            line.pack(fill="x")
            tk.Label(line, text=s["pip"], bg=BG, fg=FG, width=16, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(line, text=txt, bg=BG, fg=col, anchor="w").pack(side="left")

    log = tk.Text(root, height=11, bg=PANEL2, fg=MUTED, relief="flat",
                  highlightthickness=1, highlightbackground=BORDER,
                  font=("Consolas", 8), state="disabled")
    log.pack(fill="both", expand=True, padx=18, pady=(0, 8))

    def add_log(line):
        try:
            log.config(state="normal")
            log.insert("end", str(line) + "\n")
            log.see("end")
            log.config(state="disabled")
            root.update_idletasks()
            root.update()
        except Exception:
            pass

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=18, pady=(0, 14))

    def act_text():
        return "⬇ Установить недостающее" if pick_missing(lib_status()) else "🔄 Обновить всё"

    btn_go = tk.Button(btns, text="Продолжить →", command=root.destroy,
                       bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE,
                       activeforeground="white", relief="flat",
                       padx=14, pady=6, cursor="hand2", bd=0)
    btn_go.pack(side="right")
    btn_act = tk.Button(btns, text=act_text(), command=lambda: None,
                        bg=BTN_BG, fg=FG, activebackground=BTN_ACTIVE,
                        activeforeground="white", relief="flat",
                        padx=14, pady=6, cursor="hand2", bd=0)
    btn_act.pack(side="left")

    def do_work(upgrade):
        """Ставит недостающее (или обновляет всё). → True, если всё на месте."""
        btn_act.config(state="disabled")
        btn_go.config(state="disabled")
        pips = pick_missing(lib_status())
        if not pips and upgrade:
            pips = [s["pip"] for s in lib_status()]
        if pips:
            ran["pip"] = True
            add_log("$ python -m pip install %s%s"
                    % ("--upgrade " if upgrade else "", " ".join(pips)))
            ok = run_pip(build_pip_cmd(pips, upgrade=upgrade), on_line=add_log)
            add_log("Результат: %s" % ("успешно" if ok else
                   "НЕ УДАЛОСЬ — попробуйте вручную:  %s" % MANUAL_PIP_CMD))
        _import_libs()
        refresh_rows()
        left = pick_missing(lib_status())
        if left:
            add_log("Всё ещё не хватает: %s — можно продолжить без этих режимов."
                    % ", ".join(left))
            btn_go.config(text="Продолжить всё равно →", state="normal")
            btn_act.config(text=act_text(), state="normal")
            return False
        add_log("Все библиотеки на месте — программа готова к работе.")
        btn_act.config(text=act_text(), state="normal")
        return True

    def on_act():
        # есть недостающее → установка; всё на месте → обновление
        do_work(not bool(pick_missing(lib_status())))

    btn_act.config(command=on_act)

    def auto_run():
        try:
            all_ok = True
            if miss and cfg["auto_install"]:
                add_log("Авто-установка включена — ставлю недостающее…")
                all_ok = do_work(False)
            if cfg["auto_update"]:
                add_log("Авто-обновление включено — обновляю библиотеки…")
                all_ok = do_work(True) and all_ok
            if all_ok and not pick_missing(lib_status()):
                root.after(800, root.destroy)   # всё хорошо — окно закроется само
        except Exception as _e:
            add_log("[ошибка] %s" % _e)
            btn_go.config(text="Продолжить всё равно →", state="normal")

    busy_now = bool(miss and cfg["auto_install"]) or bool(cfg["auto_update"])
    if busy_now:
        btn_go.config(state="disabled")
    refresh_rows()
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    if miss or cfg["auto_update"]:
        root.after(250, auto_run)
    root.mainloop()
    return ran["pip"]


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    # --- v2.2: проверка библиотек, авто-установка и авто-обновление ---
    _libs_cfg = normalize_libs_cfg(read_json_safe(libs_cfg_path()))
    _missing = pick_missing(lib_status())
    if _missing or _libs_cfg["auto_update"]:
        libs_splash(_missing, _libs_cfg)
        _import_libs()      # подхватить то, что только что установилось
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
