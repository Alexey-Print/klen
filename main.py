# -*- coding: utf-8 -*-
# =====================================================================
#  ФОТО-ОТПРАВЩИК  —  шаблон-основа (Kivy/Python)
# =====================================================================
#  Сценарий:
#    запуск -> штатная камера -> проверка (Отправить/Переснять)
#    -> способ (MMS / MAX) -> архив (с геолокацией и удалением)
#
#  Хранение данных: photo_sender_data.json (рядом со скриптом)
#  Фото: папка photo_archive/ (рядом со скриптом)
#
#  ВАЖНО (см. заметки внизу файла):
#   - для камеры нужен модуль plyer (в Pydroid: pip install plyer)
#   - штатная камера/поделиться/MMS полноценно работают на устройстве,
#     а не в десктоп-эмуляции
#   - эмодзи НЕ используем (рендерятся квадратами), рубль = \u20bd
# =====================================================================

import os
import json
import time
import shutil
import threading
from datetime import datetime

from kivy.app import App
from kivy.core.window import Window
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.utils import get_color_from_hex as H

from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scatterlayout import ScatterLayout
from kivy.uix.stencilview import StencilView


def _meter_upright(p):
    try:
        import os as _os
        from PIL import Image as _PImg, ImageOps as _POps
        if not p or not _os.path.exists(p):
            return p
        up = p + ".up.jpg"
        if _os.path.exists(up) and _os.path.getmtime(up) >= _os.path.getmtime(p):
            return up
        _img = _PImg.open(p)
        _img = _POps.exif_transpose(_img)
        _img.convert("RGB").save(up, "JPEG", quality=90)
        return up
    except Exception:
        return p

class ZoomFrame(StencilView):
    """Рамка для фото: всё, что вылезает при зуме и перетаскивании,
    обрезается по её краям и не налезает на кнопки.
    В углу — значок с диагональной стрелкой: подсказка, что фото
    можно увеличивать пальцами и двигать."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.zoom = ScatterLayout(do_rotation=False, do_translation=True,
                                  scale_min=1.0, scale_max=8.0,
                                  size_hint=(None, None))
        self.img = Image(allow_stretch=True, keep_ratio=True)
        self.zoom.add_widget(self.img)
        self.add_widget(self.zoom)

        # Значок рисуем линиями: эмодзи в Pydroid не рендерятся.
        with self.canvas.after:
            self._bgc = Color(0, 0, 0, 0.45)
            self._bg = RoundedRectangle(radius=[8])
            self._lc = Color(1, 1, 1, 0.85)
            self._l1 = Line(width=1.8)   # диагональ
            self._l2 = Line(width=1.8)   # наконечник сверху справа
            self._l3 = Line(width=1.8)   # наконечник снизу слева

        self.bind(size=self._fit, pos=self._fit)

    def _fit(self, *a):
        self.zoom.size = self.size
        self.zoom.pos = self.pos

        # значок в правом нижнем углу рамки
        s = dp(34)
        pad = dp(8)
        bx = self.right - s - pad
        by = self.y + pad
        self._bg.pos = (bx, by)
        self._bg.size = (s, s)

        m = dp(9)
        x0, y0 = bx + m, by + m
        x1, y1 = bx + s - m, by + s - m
        a_ = dp(7)
        self._l1.points = [x0, y0, x1, y1]
        self._l2.points = [x1 - a_, y1, x1, y1, x1, y1 - a_]
        self._l3.points = [x0 + a_, y0, x0, y0, x0, y0 + a_]
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line

# ---------------------------------------------------------------------
#  ПУТИ И ФАЙЛЫ
# ---------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Внутри APK папка с программой только для чтения, поэтому данные
# храним в собственной папке приложения на карте памяти.
# В Pydroid всё работает по-старому (переменной ANDROID_ARGUMENT там нет).
_IS_APK = bool(os.environ.get("ANDROID_ARGUMENT"))


def _apk_data_dir():
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        d = act.getExternalFilesDir(None)
        if d is not None:
            return d.getAbsolutePath()
        return act.getFilesDir().getAbsolutePath()
    except Exception:
        return None


if _IS_APK:
    BASE_DIR = _apk_data_dir() or os.path.join(APP_DIR, "данные")
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
    except Exception:
        pass
    # При первом запуске переносим вшитые ресурсы рядом с данными.
    for _n in ("logo.png", "logo_mark.png", "fon.jpg"):
        try:
            _src = os.path.join(APP_DIR, _n)
            _dst = os.path.join(BASE_DIR, _n)
            if os.path.isfile(_src) and not os.path.isfile(_dst):
                shutil.copy2(_src, _dst)
        except Exception:
            pass
else:
    BASE_DIR = APP_DIR
    # Служебные файлы лежат в подпапке «файлы» (если она есть).
    _SUB = os.path.join(BASE_DIR, "файлы")
    if os.path.isdir(_SUB):
        BASE_DIR = _SUB
DATA_FILE = os.path.join(BASE_DIR, "photo_sender_data.json")
LOGO_FILE = os.path.join(BASE_DIR, "logo.png")  # логотип ЖСК (если положен рядом)
LOGO_MARK = os.path.join(BASE_DIR, "logo_mark.png")  # эмблема для плашки
FON_FILE = os.path.join(BASE_DIR, "fon.jpg")  # картинка-фон главной (если есть)

# =====================================================================
#  ЭМБЛЕМА ЖСК "КЛЕН" — вшита прямо в код, отдельный файл не нужен.
#  (если рядом положить logo_mark.png, будет использован он)
# =====================================================================
LOGO_B64 = (
    "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"
    "9vXqVPXfxNAJp30gYuEjeMUaxzyAL3cPtrYmZeZrTdtexEBukMkS5Bu/BMomZpKldSxAOFQJCOvTIGiMpGeAD4k8+QKCP4xxDwOa"
    "kFd5VV5UY988525Mqj3v2wCARoAWxOFjUZnRV/jKv28/sv7zP2v6kaeFkkkrKXLesB5bPV7cf83DmF19wf8lSn49Kkfe+dQKyk5m"
    "ntBf6PyTp1e/gEQqWUQk6lzl91m2bU1KOc6kKyfdeDmAb2MevD0/2Pp7nepIJWMkF0NrhtUvcU3pLUNa68cNTP4dBZl9WEqTRUS7"
    "mfmqu66+/xsV6fIvvrzuJdHW1+KVZIrtI8f2eYuX//eslnNbXgkQwXGwY/AxZjfMFt4ihRuvqf9mZW3x955b+ZTdm+1XlpQSTOHi"
    "l4O1qxGW1Nps4s0UUsdEweOq/yGNl+PVBceCSkAKC1opXZqsoBsuu7dww4V33poiav4w6IRfWYCMQAY3NoqKorq/yvPA7tJ02X8t"
    "3fR0UUtvKwvLEkF/oXmkinhAxOHYFjFQEg/FEjTB7MPDYAoFjgOnVkjk81n3nHGz7Otm3d56wejLvkhkPxvnb5wyqSo62XvoH5at"
    "e+bzK3a/WnCSwvY8olx+yLtoxsXWvJm37ZleffHniGiVyQzvMj5sCC9HPl8Yho2kJ334Ptk+b17B09mCB2mTC19NUyZSDvW0dXma"
    "jIoY++WJVsyOtElb3DWie/0F8BTz8AwA+DIz/6QoXfbdVTuazt14YJOXSqasrq4OtXTd06P7sz2rOwudf1ZpV37L9GfhgbEg4pd8"
    "n9ntqq2o+f4TbyyuONR6QCWSCRmURuyzLcMR40jbg7hENo8oocLF7ymErMCpWAhCvpDT48oniI9d/0lcNOHih4moOUY30B/Vc/yR"
    "BUg83a9fv95OUHEjs9tZVlT+2jMrH8OhjkNaSBIcwk4wAmMTbkxCQbGoIQ9WhwJxiUoKv8IHqDGzYlw/5xb7quk37axNTfmkvwMY"
    "IaZAjY2NwWb8hoPt27/12rYXp20/sVnbCdtxXY+JWd837+PWhWMvWVpXNPlBIuqLgRTf5cY0MPzyrTuX87ThGzNJEJstKrGvraag"
    "Qs1Ylz1JBItI+INODgyywZoVSSmK4KsivueDymhxrWbm66vKqr5dUVJ1/+ublyvpOMIt5PUbG5cWDRX6/+26C26+g5l/m4iOxsGO"
    "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"
    "2cjcydd8DSj9MyLqcigV/7TM0i1btggXNd2Y45F7R0YG2Mt40rCGIAWAqLZiMhorZvQBwMaNG3/qEiYerLWghYhoJ0A7Ix79+IKG"
    "xf/71dP76l4+uAuDY4ORr1LC85TgmIMjBEAm0XuAqYDhDAipzFg4Js4PnJsB5M3o/mOB/Ds+Qs52H1s6PD5gswgpv1PG/l2WYiGc"
    "wTIQhIEJc6GpKatW1y+5Xi6dvmKsrnrWNzKo+DMiOlvYFP8sr6q1tZU3bdrEe469/LvtvcdZepKJiKyvl9ElZSXSF/5OAGfc5Pxn"
    "6s/iPi+2clJU/I/M/N0FDYv+cOXc6+/fe2J35b6jr6D3UpdOpTPkp3zHShOJ3lY4/pqd7htIIan/Ug96hy9+gJm/3NLSYt7Od9Db"
    "dvW7foCZueGRF795+PljjxdRigBJsUd4QSohQUfMURAaQ4JmVM8UKxpXYFbFrLCufMZjxam6P4gXxs+bf+dMBBjAin999bFdj734"
    "z4okEUgTWap7NK2mXq1saH7gnhXv/ZPt27erdevWRW/MZ7JdEa2Lodep4+byf207c/iuzksnr9135BV09nciJG38VBpCQlg/M7uJ"
    "6Hiiopk5At510wew8Yb3NTk/MPFms2z/4wT5+Vc+A+COS2f/tme4vTgwoZHsCenktTFjNgpC1ibiyuIqMW/OItnUsATVmbqT0ydN"
    "exgo2UpEhwux/J9XqLMDO8Q6WhedvXTut071HPWDIBd56ZSKIyGiyIjiVBkaZy44BAB9zX1vGLxJtC56gB9wuZjUBeCPmPkvV8y9"
    "ccOSGas+fKqzbX1bx6HMmf4zGLg8xEJJ9oVvg1fBYCNgWFNkwqhr4JzqGOr6HQC/5eYa/7FA/p2dHoaZ5+w48uQ7T3UfZ5Aio7VT"
    "FhLYRPCEwtzJ82he/SJqqJp9oa5i+vNlqSkPAthVEC0sYN0xrhhS/hyvK2Lmpm2Hn779yMn9RipPMkeWvczEgrUoEpmBedULXwGu"
    "iCV4Qx6bqSBJ12bZDwDYIoXcEumoflXj9XeeuXjivx/taFtwrOskne85B40IgpQLs2FIEnSm8wRaTxy6wSlF37axEW/bE4SZqXPg"
    "7N8c6zooR7OjRvrSqq2YkPLTmFnbwCvnrkHD5MZjNSX1/yDhPUxEgwU/r2Cz7N7InVEAMMPh4LrzA2emjmaHo+KSYqXZOOat4bTn"
    "08zqWZcyqaIu4BcX5hMn6dqTcYckWhcRUSeAf2Lmr117zQ2/3tF1emNb55GbX259Gd2DFyjSEYzV3Mu+gS5zuvfooktja9YBeKZg"
    "rvO2evw/uoRiK+yuJB4AAAAASUVORK5CYII="
)


def _logo_image():
    """Вернуть эмблему (PIL Image) из файла рядом или из вшитой копии."""
    from PIL import Image
    import base64, io
    try:
        if os.path.exists(LOGO_MARK):
            return Image.open(LOGO_MARK).convert("RGBA")
    except Exception as e:
        print("Логотип из файла не открылся:", e)
    try:
        return Image.open(io.BytesIO(base64.b64decode(LOGO_B64))).convert("RGBA")
    except Exception as e:
        print("Вшитый логотип не открылся:", e)
        return None
PHOTO_DIR = os.path.join(BASE_DIR, "photo_archive")
STAMP_DIR = os.path.join(BASE_DIR, "photo_stamped")
THUMB_DIR = os.path.join(BASE_DIR, "photo_thumbs")

try:
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(STAMP_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)
    # .nomedia прячет папки приложения от галереи телефона,
    # чтобы фото приложения не показывались в галерее и их нельзя было
    # случайно удалить оттуда.
    for _d in (PHOTO_DIR, STAMP_DIR, THUMB_DIR):
        _nm = os.path.join(_d, ".nomedia")
        if not os.path.exists(_nm):
            open(_nm, "w").close()
except Exception as _e:
    print("Не удалось создать папку фото:", _e)

# ---------------------------------------------------------------------
#  ПАЛИТРА (тёмная, неоновые акценты)
# ---------------------------------------------------------------------
BG      = H("#0d0d12")   # фон
CARD    = H("#1a1a24")   # карточка
CARD2   = H("#22222e")   # карточка светлее
BTN2    = H("#30313f")   # вторичная кнопка (заметно светлее фона)
BORDER  = H("#5c5e7e")   # рамка вторичных кнопок
ACCENT  = H("#00e5b0")   # неоновый бирюзовый (главное действие)
ACCENT2 = H("#3aa0ff")   # синий (второе действие)
DANGER  = H("#ff4d6d")   # красный (удалить/переснять)
TEXT    = H("#f0f0f5")   # основной текст
MUTED   = H("#8a8a9a")   # приглушённый текст
DARKTX  = H("#0d0d12")   # тёмный текст на светлых кнопках
INPUTBG = H("#1c1c26")   # фон полей ввода (НЕ прозрачный!)
BACKC   = H("#8f7fe8")   # «назад» — свой цвет, чтобы не искать её глазами

# =====================================================================
#  БЛОК ANDROID: камера / поделиться / MMS
#  Всё обёрнуто в try/except — если API недоступно, приложение
#  продолжает работать, просто действие не выполняется.
# =====================================================================

# Съёмка через ШТАТНУЮ камеру напрямую (jnius + MediaStore), без plyer.
# Почему так: plyer в Pydroid часто падает на file:// (FileUriExposedException).
# MediaStore отдаёт content:// URI, в который камера пишет без FileProvider.
# Готовое фото копируем в наш файл, а временную запись в галерее удаляем.

def launch_native_camera(app, dest_path, on_done, status_cb):
    """Запустить штатную камеру. Результат придёт в on_done(path|None)
    через on_resume/опрос (см. методы приложения)."""
    def report(m):
        print("CAM:", m)
        try:
            status_cb(m)
        except Exception:
            pass

    try:
        from jnius import autoclass, cast
    except Exception as e:
        report("Модуль jnius недоступен: %s" % e)
        on_done(None)
        return

    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity is None:
            report("Активность недоступна (mActivity=None)")
            on_done(None)
            return
    except Exception as e:
        report("Не найден PythonActivity: %s" % e)
        on_done(None)
        return

    try:
        Intent = autoclass("android.content.Intent")
        MediaStore = autoclass("android.provider.MediaStore")
        ContentValues = autoclass("android.content.ContentValues")
        ImagesMedia = autoclass("android.provider.MediaStore$Images$Media")

        resolver = activity.getContentResolver()
        values = ContentValues()
        values.put("_display_name", "photo_%d.jpg" % int(time.time()))
        values.put("mime_type", "image/jpeg")
        uri = resolver.insert(ImagesMedia.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            report("Не удалось создать файл (uri=None). Нужны разрешения на фото.")
            on_done(None)
            return

        intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
        intent.putExtra(MediaStore.EXTRA_OUTPUT, cast("android.os.Parcelable", uri))
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        app._cam = {"uri": uri, "dest": dest_path, "cb": on_done,
                    "activity": activity, "tries": 0}
        report("Открываю камеру...")
        activity.startActivity(intent)
    except Exception as e:
        report("Ошибка запуска камеры: %s" % e)
        on_done(None)


def finish_native_camera(activity, uri, dest_path):
    """Скопировать снятое фото из MediaStore в наш файл. True при успехе.
    После копирования удаляем временную запись из галереи."""
    from jnius import autoclass

    def _cleanup():
        try:
            activity.getContentResolver().delete(uri, None, None)
        except Exception as e:
            print("CAM cleanup:", e)

    # Способ 1: путь из столбца _data (характерно для старых Android)
    try:
        resolver = activity.getContentResolver()
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is not None:
            got = False
            if cursor.moveToFirst():
                idx = cursor.getColumnIndex("_data")
                if idx >= 0:
                    path = cursor.getString(idx)
                    if path and os.path.exists(path) and os.path.getsize(path) > 0:
                        shutil.copyfile(path, dest_path)
                        got = True
            cursor.close()
            if got:
                _cleanup()
                return True
    except Exception as e:
        print("CAM _data:", e)

    # Способ 2: чтение потока content:// (новые Android)
    try:
        resolver = activity.getContentResolver()
        istream = resolver.openInputStream(uri)
        if istream is None:
            return False
        FileOutputStream = autoclass("java.io.FileOutputStream")
        out = FileOutputStream(dest_path)
        buf = bytearray(8192)
        total = 0
        while True:
            n = istream.read(buf)
            if n <= 0:
                break
            out.write(buf, 0, n)
            total += n
        out.flush()
        out.close()
        istream.close()
        if total > 0:
            _cleanup()
            return True
        return False
    except Exception as e:
        print("CAM stream:", e)
        return False


def make_shareable_uri(activity, path):
    """Скопировать фото в MediaStore и вернуть content:// URI, пригодный для
    передачи в другие приложения (без FileProvider). None при ошибке.
    Нужно потому, что на Android 7+ file:// нельзя отдавать другим приложениям."""
    try:
        from jnius import autoclass
        ContentValues = autoclass("android.content.ContentValues")
        ImagesMedia = autoclass("android.provider.MediaStore$Images$Media")
        FileInputStream = autoclass("java.io.FileInputStream")
        resolver = activity.getContentResolver()
        values = ContentValues()
        values.put("_display_name", "send_%d.jpg" % int(time.time()))
        values.put("mime_type", "image/jpeg")
        uri = resolver.insert(ImagesMedia.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            return None
        ostream = resolver.openOutputStream(uri)
        istream = FileInputStream(path)
        buf = bytearray(8192)
        while True:
            n = istream.read(buf)
            if n <= 0:
                break
            ostream.write(buf, 0, n)
        ostream.flush()
        ostream.close()
        istream.close()
        return uri
    except Exception as e:
        print("make_shareable_uri:", e)
        return None


def share_photo(path):
    """Открыть системное 'Поделиться' с прикреплённым фото (для MAX и др.).
    True, если окно отправки открылось."""
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")

        uri = make_shareable_uri(activity, path)
        if uri is None:
            print("share: uri None")
            return False

        intent = Intent()
        intent.setAction(Intent.ACTION_SEND)
        intent.setType("image/*")
        intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        title = cast("java.lang.CharSequence", String("Отправить через"))
        chooser = Intent.createChooser(intent, title)
        chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(chooser)
        return True
    except Exception as e:
        print("Поделиться недоступно:", e)
        return False


@mainthread
def _toast_main(msg):
    toast(msg)


def share_photos_multiple(paths):
    """Отправить несколько фото. Тяжёлое копирование — в вызывающем потоке,
    запуск окна отправки — на главном потоке."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        uris = []
        for p in paths:
            u = make_shareable_uri(activity, p)
            if u is not None:
                uris.append(u)
        if not uris:
            _toast_main("Не удалось подготовить фото.")
            return False
        _start_share_multiple(activity, uris)
        return True
    except Exception as e:
        print("share multiple:", e)
        _toast_main("Не удалось открыть отправку.")
        return False


@mainthread
def _start_share_multiple(activity, uris):
    try:
        from jnius import autoclass, cast
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        ArrayList = autoclass("java.util.ArrayList")

        arr = ArrayList()
        for u in uris:
            arr.add(cast("android.os.Parcelable", u))

        intent = Intent()
        intent.setAction(Intent.ACTION_SEND_MULTIPLE)
        intent.setType("image/*")
        intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM, arr)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        title = cast("java.lang.CharSequence", String("Отправить"))
        chooser = Intent.createChooser(intent, title)
        chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(chooser)
    except Exception as e:
        print("start share multiple:", e)
        _toast_main("Не удалось открыть отправку.")


def send_mms_multiple(paths, number):
    """Отправить несколько фото по MMS на номер (копирование в фоне)."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        uris = []
        for p in paths:
            u = make_shareable_uri(activity, p)
            if u is not None:
                uris.append(u)
        if not uris:
            _toast_main("Не удалось подготовить фото.")
            return False
        _start_mms_multiple(activity, uris, number)
        return True
    except Exception as e:
        print("mms multiple:", e)
        _toast_main("Не удалось открыть отправку.")
        return False


@mainthread
def _start_mms_multiple(activity, uris, number):
    try:
        from jnius import autoclass, cast
        Intent = autoclass("android.content.Intent")
        ArrayList = autoclass("java.util.ArrayList")

        arr = ArrayList()
        for u in uris:
            arr.add(cast("android.os.Parcelable", u))

        intent = Intent(Intent.ACTION_SEND_MULTIPLE)
        intent.setType("image/*")
        intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM, arr)
        intent.putExtra("address", number)
        intent.putExtra("sms_body", "")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try:
            Telephony = autoclass("android.provider.Telephony$Sms")
            pkg = Telephony.getDefaultSmsPackage(activity)
            if pkg:
                intent.setPackage(pkg)
        except Exception as e:
            print("MMS pkg:", e)
        activity.startActivity(intent)
    except Exception as e:
        print("start mms multiple:", e)
        _toast_main("Не удалось открыть отправку.")


def send_mms(path, number):
    """Открыть отправку фото через приложение сообщений (MMS) на номер.
    На части устройств номер уже подставлен, на части — выбирается
    в приложении сообщений (1 лишний тап). True, если отправка открылась."""
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        Intent = autoclass("android.content.Intent")

        uri = make_shareable_uri(activity, path)
        if uri is None:
            print("mms: uri None")
            return False

        intent = Intent(Intent.ACTION_SEND)
        intent.setType("image/*")
        intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
        intent.putExtra("address", number)
        intent.putExtra("sms_body", "")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        # Направить сразу в приложение сообщений по умолчанию
        try:
            Telephony = autoclass("android.provider.Telephony$Sms")
            pkg = Telephony.getDefaultSmsPackage(activity)
            if pkg:
                intent.setPackage(pkg)
        except Exception as e:
            print("MMS default pkg:", e)

        activity.startActivity(intent)
        return True
    except Exception as e:
        print("MMS недоступно:", e)
        return False

# =====================================================================
#  БЛОК ГЕОЛОКАЦИИ: чтение GPS из EXIF + адрес по координатам
#  Полностью необязательный. Нет геометки/интернета — просто ничего
#  не показываем, приложение работает как обычно.
# =====================================================================

def read_gps(path):
    """Прочитать (lat, lon) из EXIF снимка. Вернуть None, если нет."""
    try:
        from PIL import Image as PILImage
        from PIL.ExifTags import TAGS, GPSTAGS
        img = PILImage.open(path)
        exif = img._getexif()
        if not exif:
            return None
        gps_raw = None
        for tag, val in exif.items():
            if TAGS.get(tag) == "GPSInfo":
                gps_raw = val
                break
        if not gps_raw:
            return None
        gps = {}
        for k, v in gps_raw.items():
            gps[GPSTAGS.get(k, k)] = v
        if "GPSLatitude" not in gps or "GPSLongitude" not in gps:
            return None

        def to_deg(v):
            d = float(v[0]); m = float(v[1]); s = float(v[2])
            return d + m / 60.0 + s / 3600.0

        lat = to_deg(gps["GPSLatitude"])
        lon = to_deg(gps["GPSLongitude"])
        if str(gps.get("GPSLatitudeRef", "N")).upper() == "S":
            lat = -lat
        if str(gps.get("GPSLongitudeRef", "E")).upper() == "W":
            lon = -lon
        return (lat, lon)
    except Exception as e:
        print("EXIF/GPS ошибка:", e)
        return None


def reverse_geocode(lat, lon):
    """Координаты -> адрес (нужен интернет). Вернуть строку или None."""
    try:
        import urllib.request
        import json as _json
        url = ("https://nominatim.openstreetmap.org/reverse?"
               "format=json&lat=%s&lon=%s&zoom=18&addressdetails=1" % (lat, lon))
        req = urllib.request.Request(url, headers={"User-Agent": "PhotoSender/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return data.get("display_name")
    except Exception as e:
        print("Геокодер ошибка:", e)
        return None


# =====================================================================
#  ПОДПИСЬ НА ФОТО: впечатываем текст в нижнюю часть снимка, чтобы
#  получатель видел подпись прямо на картинке.
# =====================================================================

def _find_font(bold=False):
    candidates = []
    name = "Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf"
    try:
        import kivy
        candidates.append(os.path.join(os.path.dirname(kivy.__file__),
                                       "data", "fonts", name))
        candidates.append(os.path.join(os.path.dirname(kivy.__file__),
                                       "data", "fonts", "Roboto-Regular.ttf"))
    except Exception:
        pass
    if bold:
        candidates += ["/system/fonts/Roboto-Bold.ttf",
                       "/system/fonts/DroidSans-Bold.ttf",
                       "/system/fonts/NotoSans-Bold.ttf"]
    candidates += [
        "/system/fonts/Roboto-Regular.ttf",
        "/system/fonts/DroidSans.ttf",
        "/system/fonts/NotoSans-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# Одновременно готовим только одно фото — иначе на больших снимках
# телефон упирается в память и всё виснет.
STAMP_LOCK = threading.Lock()


def stamped_cache_path(src_path, caption, comment="", meter=""):
    """Имя файла-кэша для конкретного фото с конкретными надписями."""
    try:
        lg = "el2"
        key = "%s|%s|%s|%s|%s" % (os.path.basename(src_path or ""), caption or "",
                                  comment or "", meter or "", lg)
        h = 0
        for ch in key:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        return os.path.join(STAMP_DIR, "st_%08x.jpg" % h)
    except Exception:
        return None


def stamped_ready(src_path, caption, comment="", meter=""):
    """Готовое фото с надписями, если оно уже есть в кэше. Иначе None."""
    if not caption and not comment and not meter:
        return src_path if (src_path and os.path.exists(src_path)) else None
    p = stamped_cache_path(src_path, caption, comment, meter)
    return p if (p and os.path.exists(p)) else None


def stamped_image_path(src_path, caption, comment="", meter=""):
    """Фото с фирменной плашкой ЖСК: сверху поле с логотипом и адресом,
    снизу поле с комментарием. Сам кадр ничем не перекрывается.
    Результат кэшируется — повторные открытия мгновенные."""
    if ((not caption and not comment and not meter) or not src_path
            or not os.path.exists(src_path)):
        return src_path

    out = stamped_cache_path(src_path, caption, comment, meter)
    if out and os.path.exists(out):
        return out

    with STAMP_LOCK:
        # ещё раз проверяем: пока ждали очереди, файл мог уже появиться
        if out and os.path.exists(out):
            return out
        return _render_stamped(src_path, caption, comment, out, meter)


def _render_stamped(src_path, caption, comment, out, meter=""):
    try:
        from PIL import (Image, ImageDraw, ImageFont, ImageOps,
                         ImageFilter, ImageChops)

        GOLD = (255, 214, 102)
        BG = (18, 24, 38)
        FIELD = (10, 14, 22)

        base = Image.open(src_path)
        try:
            # draft — быстрое и лёгкое декодирование JPEG сразу в меньший размер
            base.draft("RGB", (1200, 1200))
        except Exception:
            pass
        try:
            base = ImageOps.exif_transpose(base)
        except Exception:
            pass
        base = base.convert("RGB")
        # Ужимаем: на снимках 2000+px отрисовка плашки очень тяжёлая
        base.thumbnail((1200, 1200), Image.LANCZOS)
        W0, H0 = base.size

        # поля сверху и снизу — кадр не перекрываем
        top_f = int(W0 * 0.215)
        bot_f = int(W0 * 0.28)
        img = Image.new("RGB", (W0, H0 + top_f + bot_f), FIELD)
        img.paste(base, (0, top_f))
        W, H = img.size
        draw = ImageDraw.Draw(img)

        fpath = _find_font(bold=True)

        def fit(text, maxw, start_size):
            fs = start_size
            while fs > 8:
                f = (ImageFont.truetype(fpath, fs) if fpath
                     else ImageFont.load_default())
                b = draw.textbbox((0, 0), text, font=f)
                if (b[2] - b[0]) <= maxw or not fpath:
                    return f, b
                fs -= 1
            f = (ImageFont.truetype(fpath, 8) if fpath
                 else ImageFont.load_default())
            return f, draw.textbbox((0, 0), text, font=f)

        sx = 2
        m = int(W * 0.012)
        bw = max(2, int(W * 0.005))

        def plate(boxes):
            """Нарисовать фигуру из скруглённых блоков: фон + жёлтый контур."""
            big = Image.new("L", (W * sx, H * sx), 0)
            bd = ImageDraw.Draw(big)
            for (bx, r) in boxes:
                bd.rounded_rectangle([bx[0]*sx, bx[1]*sx, bx[2]*sx, bx[3]*sx],
                                     radius=int(r)*sx, fill=255)
            mk = big.resize((W, H), Image.LANCZOS).point(
                lambda v: 255 if v > 128 else 0)
            ol = ImageChops.subtract(mk, mk.filter(ImageFilter.MinFilter(bw*2+1)))
            img.paste(Image.new("RGB", (W, H), BG), (0, 0), mk)
            img.paste(Image.new("RGB", (W, H), GOLD), (0, 0), ol)

        # ---- верхняя плашка: одна рамка, слева эмблема,
        #      справа ЖСК КЛЕН, улица и дом/кв ----
        if caption:
            ph = int(W * 0.20)
            x0, y0 = m, m
            x1 = W - m
            y1 = y0 + ph
            plate([([x0, y0, x1, y1], ph * 0.24)])

            pad = int(ph * 0.09)
            mh = ph - pad * 2
            mx = x0 + int(pad * 1.4)
            text_x = x0 + int(pad * 1.4)
            try:
                mark = _logo_image()
                if mark is not None:
                    mw = max(1, int(mark.width * mh / mark.height))
                    mark = mark.resize((mw, mh))
                    img.paste(mark, (mx, y0 + pad), mark)
                    text_x = mx + mw + pad
            except Exception as le:
                print("Эмблема не наложена:", le)

            avail = x1 - text_x - int(pad * 1.4)

            # Адрес двумя строками — так шрифт остаётся крупным
            # даже на длинных улицах.
            _st, _ho, _fl = parse_address(caption)
            line1 = _st or caption
            line2 = build_address("", _ho, _fl)

            f_sm, b = fit("ЖСК КЛЕН", avail, int(ph * 0.15))
            sw = b[2] - b[0]
            draw.text((text_x + max(0, (avail - sw) // 2), y0 + int(ph * 0.07)),
                      "ЖСК КЛЕН", fill=(255, 255, 255), font=f_sm)

            if line2:
                f1, b1 = fit(line1, avail, int(ph * 0.30))
                w1 = b1[2] - b1[0]
                draw.text((text_x + max(0, (avail - w1) // 2),
                           y0 + int(ph * 0.29)), line1, fill=GOLD, font=f1)
                f2, b2 = fit(line2, avail, int(ph * 0.30))
                w2 = b2[2] - b2[0]
                draw.text((text_x + max(0, (avail - w2) // 2),
                           y0 + int(ph * 0.61)), line2, fill=GOLD, font=f2)
            else:
                f1, b1 = fit(line1, avail, int(ph * 0.34))
                w1 = b1[2] - b1[0]
                draw.text((text_x + max(0, (avail - w1) // 2),
                           y0 + int(ph * 0.42)), line1, fill=GOLD, font=f1)

        # ---- нижняя плашка: показания счётчика + комментарий ----
        if True:
            import re as _re2
            _mt = meter or ""
            _ct = comment or ""
            _words = ("ХОЛОДНАЯ", "ГОРЯЧАЯ", "ЭЛЕКТРО")
            _typ = ""
            for _w in _words:
                if _mt.startswith(_w):
                    _typ = _w; break
            if _typ == "ХОЛОДНАЯ":
                _col = (77, 163, 255)
            elif _typ == "ГОРЯЧАЯ":
                _col = (255, 92, 92)
            elif _typ == "ЭЛЕКТРО":
                _col = (255, 214, 102)
            else:
                _col = (255, 255, 255)
            _mm = _re2.search(r"(\d[\d ]*)\s*,\s*(\d+)", _mt)
            _whole = ""; _frac = ""
            if _mm:
                _whole = _mm.group(1).replace(" ", ""); _frac = _mm.group(2)
            else:
                _mm2 = _re2.search(r"(\d+)", _mt)
                if _mm2:
                    _whole = _mm2.group(1)
            _unit = "кВт·ч" if ("кВт" in _mt) else ("куб.м" if _whole else "")
            _drawn = False
            if _whole:
                try:
                    try:
                        import datetime as _dt5, os as _os5
                        _mns5 = ["", "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]
                        if src_path and _os5.path.exists(src_path):
                            _dd5 = _dt5.datetime.fromtimestamp(_os5.path.getmtime(src_path))
                        else:
                            _dd5 = _dt5.datetime.now()
                        _mon = _mns5[_dd5.month]
                    except Exception:
                        _mon = ""
                    ch = int(W * 0.078); cw = int(W * 0.050); gap = int(W * 0.008)
                    r2h = int(W * 0.062); pad = int(W * 0.022); midgap = int(W * 0.012)
                    bw3 = max(2, int(W * 0.003))
                    bh = pad + ch + midgap + r2h + pad
                    by1 = H - m; by0 = by1 - bh
                    plate([([m, by0, W - m, by1], int(bh * 0.14))])
                    lx = m + int(W * 0.03)
                    r1y = by0 + pad
                    r2y = r1y + ch + midgap
                    f_ty, _bty = fit(_typ or " ", int(W * 0.42), int(ch * 0.60))
                    f_mn, _bmn = fit(_mon or " ", int(W * 0.42), int(r2h * 0.95))
                    f_dig, _ = fit("8", int(cw * 0.8), int(ch * 0.58))
                    f_un, _bu = fit(_unit or " ", int(W * 0.18), int(ch * 0.40))
                    f_cm, _ = fit(_ct or " ", int(W * 0.60), int(r2h * 0.85))
                    _tw = (draw.textbbox((0, 0), _typ, font=f_ty)[2]) if _typ else 0
                    _mw = (draw.textbbox((0, 0), _mon, font=f_mn)[2]) if _mon else 0
                    _lw = max(_tw, _mw)
                    _rx0 = lx + _lw + int(W * 0.035)
                    _rx1 = W - m - int(W * 0.015)
                    if _typ:
                        _bt = draw.textbbox((0, 0), _typ, font=f_ty)
                        draw.text((lx, r1y + (ch - (_bt[3] - _bt[1])) // 2 - _bt[1]), _typ, fill=_col, font=f_ty)
                    if _mon:
                        _bm = draw.textbbox((0, 0), _mon, font=f_mn)
                        draw.text((lx, r2y + (r2h - (_bm[3] - _bm[1])) // 2 - _bm[1]), _mon, fill=(255, 214, 102), font=f_mn)
                    _uw = (_bu[2] - _bu[0]) if _unit else 0
                    _bc = draw.textbbox((0, 0), ",", font=f_dig)
                    _cmw = (_bc[2] - _bc[0]) + gap
                    _n = len(_whole) + len(_frac)
                    _rw = _n * cw + max(0, _n - 1) * gap + (_cmw if _frac else 0) + (_uw + gap if _unit else 0)
                    x = _rx0 + max(0, (_rx1 - _rx0 - _rw) // 2)
                    for _d in _whole:
                        draw.rounded_rectangle([x, r1y, x + cw, r1y + ch], radius=int(cw * 0.16), fill=(28, 32, 42), outline=(150, 150, 170), width=bw3)
                        _bd = draw.textbbox((0, 0), _d, font=f_dig)
                        draw.text((x + (cw - (_bd[2] - _bd[0])) // 2 - _bd[0], r1y + (ch - (_bd[3] - _bd[1])) // 2 - _bd[1]), _d, fill=(255, 255, 255), font=f_dig)
                        x += cw + gap
                    if _frac:
                        _bd = draw.textbbox((0, 0), ",", font=f_dig)
                        draw.text((x, r1y + ch - (_bd[3] - _bd[1]) - int(ch * 0.10) - _bd[1]), ",", fill=(255, 255, 255), font=f_dig)
                        x += _cmw
                        for _d in _frac:
                            draw.rounded_rectangle([x, r1y, x + cw, r1y + ch], radius=int(cw * 0.16), fill=(48, 24, 24), outline=(255, 92, 92), width=bw3)
                            _bd = draw.textbbox((0, 0), _d, font=f_dig)
                            draw.text((x + (cw - (_bd[2] - _bd[0])) // 2 - _bd[0], r1y + (ch - (_bd[3] - _bd[1])) // 2 - _bd[1]), _d, fill=(255, 92, 92), font=f_dig)
                            x += cw + gap
                    if _unit:
                        _bd = draw.textbbox((0, 0), _unit, font=f_un)
                        draw.text((x + gap, r1y + (ch - (_bd[3] - _bd[1])) // 2 - _bd[1]), _unit, fill=(210, 210, 220), font=f_un)
                    if _ct:
                        _bcm = draw.textbbox((0, 0), _ct, font=f_cm)
                        _cx = _rx0 + max(0, (_rx1 - _rx0 - (_bcm[2] - _bcm[0])) // 2)
                        draw.text((_cx, r2y + (r2h - (_bcm[3] - _bcm[1])) // 2 - _bcm[1]), _ct, fill=(200, 200, 210), font=f_cm)
                    _drawn = True
                except Exception:
                    _drawn = False
            if not _drawn:
                try:
                    import datetime as _dt6, os as _os6
                    _mns6 = ["", "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]
                    if src_path and _os6.path.exists(src_path):
                        _dd6 = _dt6.datetime.fromtimestamp(_os6.path.getmtime(src_path))
                    else:
                        _dd6 = _dt6.datetime.now()
                    _mon6 = _mns6[_dd6.month]
                except Exception:
                    _mon6 = ""
                _parts6 = []
                if _mon6:
                    _parts6.append(_mon6)
                if _mt:
                    _parts6.append(_mt)
                if _ct:
                    _parts6.append(_ct)
                _txt = "   |   ".join(_parts6) if _parts6 else "-"
                f_bt, b = fit(_txt, W - 2 * m - int(W * 0.06), int(W * 0.062))
                lwid, lhei = b[2] - b[0], b[3] - b[1]
                bh = lhei + int(W * 0.05)
                by1 = H - m; by0 = by1 - bh
                plate([([m, by0, W - m, by1], bh * 0.38)])
                _y6 = by0 + (bh - lhei) // 2 - int(W * 0.007)

                def _wid6(_s6):
                    try:
                        return int(draw.textlength(_s6, font=f_bt))
                    except Exception:
                        _bb6 = draw.textbbox((0, 0), _s6, font=f_bt)
                        return _bb6[2] - _bb6[0]

                _cols6 = []
                if _mon6:
                    _cols6.append((_mon6, (255, 214, 102)))
                if _mt:
                    _cols6.append((_mt, _col))
                if _ct:
                    _cols6.append((_ct, (200, 200, 210)))
                if _cols6:
                    _x6 = (W - _wid6(_txt)) // 2
                    for _i6, _pc6 in enumerate(_cols6):
                        if _i6:
                            draw.text((_x6, _y6), "   |   ",
                                      fill=(150, 150, 165), font=f_bt)
                            _x6 += _wid6("   |   ")
                        draw.text((_x6, _y6), _pc6[0], fill=_pc6[1], font=f_bt)
                        _x6 += _wid6(_pc6[0])
                else:
                    draw.text(((W - lwid) // 2, _y6), _txt,
                              fill=(255, 255, 255), font=f_bt)

        # Вписываем всё в квадрат. Мессенджер показывает квадратное
        # превью целиком, а вытянутое режет сверху и снизу — вместе
        # с адресом и комментарием. Сам кадр не обрезается,
        # получатель откроет фото и увеличит пальцами.
        side = max(W, H)
        square = Image.new("RGB", (side, side), FIELD)
        square.paste(img, ((side - W) // 2, (side - H) // 2))
        img = square

        if not out:
            out = os.path.join(STAMP_DIR, "stamp_%d.jpg" % int(time.time() * 1000))
        img.save(out, "JPEG", quality=90)
        return out
    except Exception as e:
        print("Не удалось наложить плашку:", e)
        return src_path


# --- Миниатюры для быстрого архива ---

def cached_thumb_path(src):
    """Путь к готовой миниатюре, если она уже создана. Иначе None."""
    if not src:
        return None
    tp = os.path.join(THUMB_DIR, os.path.basename(src))
    return tp if os.path.exists(tp) else None


def make_thumb(src):
    """Создать маленькую миниатюру (кэш). Вернуть путь или None."""
    try:
        if not src or not os.path.exists(src):
            return None
        tp = os.path.join(THUMB_DIR, os.path.basename(src))
        if os.path.exists(tp):
            return tp
        from PIL import Image, ImageOps
        with STAMP_LOCK:
            if os.path.exists(tp):
                return tp
            img = Image.open(src)
            try:
                img.draft("RGB", (480, 480))
            except Exception:
                pass
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img = img.convert("RGB")
            img.thumbnail((240, 240))
            img.save(tp, "JPEG", quality=80)
        return tp
    except Exception as e:
        print("Не удалось создать миниатюру:", e)
        return None

# =====================================================================
#  ДАННЫЕ
# =====================================================================

def default_data():
    return {
        "recipients": [],          # [{"name": "Олег", "number": "+7..."}]
        "last_recipient": 0,       # индекс последнего адресата MMS
        "settings": {"mms_mode": "list"},  # "list" | "last"
        "default_address": "",     # адрес по умолчанию (подставляется в новые фото)
        "archive": [],             # список записей архива
    }


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            base = default_data()
            base.update(d)
            if "settings" not in d:
                base["settings"] = {"mms_mode": "list"}
            return base
        except Exception as e:
            print("Ошибка чтения данных:", e)
    return default_data()


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка записи данных:", e)

# =====================================================================
#  UI-ХЕЛПЕРЫ
# =====================================================================

class RoundedButton(Button):
    """Кнопка со скруглённым цветным фоном (без картинок).
    border — цвет рамки (для тёмных кнопок, чтобы читались как кнопки)."""
    def __init__(self, bg=ACCENT, fg=DARKTX, radius=20, border=None, **kw):
        super().__init__(**kw)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = fg
        self.halign = "center"
        self.valign = "middle"
        self.bold = True
        self._radius = radius
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(radius=[radius])
            if border is not None:
                self._bcol = Color(*border)
                self._line = Line(width=2.4)
            else:
                self._line = None
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size
        if self._line is not None:
            self._line.rounded_rectangle = (
                self.x, self.y, self.width, self.height, self._radius)
        self.text_size = (self.width - dp(16), None)

    def set_bg(self, color):
        self._col.rgba = color


class ImageButton(ButtonBehavior, Image):
    """Картинка, на которую можно нажимать (для миниатюр архива)."""
    pass


class Card(BoxLayout):
    """Скруглённый контейнер-карточка (border — цвет рамки, если нужен)."""
    def __init__(self, bg=CARD, radius=18, border=None, **kw):
        super().__init__(**kw)
        self._radius = radius
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(radius=[radius])
            if border is not None:
                self._bc = Color(*border)
                self._ln = Line(width=1.6)
            else:
                self._ln = None
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size
        if self._ln is not None:
            self._ln.rounded_rectangle = (
                self.x, self.y, self.width, self.height, self._radius)


def title_label(text, color=TEXT, size="20sp"):
    lb = Label(text=text, color=color, font_size=size, bold=True,
               size_hint_y=None, height=dp(48), halign="center", valign="middle")
    lb.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
    return lb


def body_label(text, color=MUTED, size="14sp", h=dp(26), halign="left"):
    lb = Label(text=text, color=color, font_size=size,
               size_hint_y=None, height=h, halign=halign, valign="middle")
    lb.bind(size=lambda w, *a: setattr(w, "text_size", (w.width, None)))
    return lb


def make_input(hint=""):
    """Поле ввода с ТЁМНЫМ НЕ прозрачным фоном (прозрачный ломает ввод
    в Pydroid). Enter убирает клавиатуру, чтобы она не закрывала кнопки."""
    ti = TextInput(
        hint_text=hint, multiline=False,
        background_color=INPUTBG, foreground_color=TEXT,
        cursor_color=ACCENT, hint_text_color=(0.72, 0.76, 0.84, 1),
        padding=[dp(12), dp(12)], font_size="17sp",
        size_hint_y=None, height=dp(52),
    )

    from kivy.graphics import Color as _IC8, Line as _IL8

    def _bord8(*_a):
        ti.canvas.after.clear()
        with ti.canvas.after:
            _IC8(ACCENT[0], ACCENT[1], ACCENT[2], 0.85)
            _IL8(rounded_rectangle=(ti.x + 1, ti.y + 1,
                                    ti.width - 2, ti.height - 2, dp(9)),
                 width=1.6)

    ti.bind(pos=_bord8, size=_bord8)
    ti.bind(on_text_validate=lambda w: setattr(w, "focus", False))
    return ti


def parse_address(text):
    """Разобрать адрес на (улица, дом, кв)."""
    street, house, flat = (text or "").strip(), "", ""
    low = street.lower()
    for key in (" дом", " д.", " д "):
        i = low.find(key)
        if i > 0:
            rest = street[i + len(key):].strip()
            street = street[:i].strip()
            low2 = rest.lower()
            j = -1
            for k2 in ("кв.", "кв ", "кв"):
                j = low2.find(k2)
                if j >= 0:
                    flat = rest[j + len(k2):].strip()
                    rest = rest[:j].strip()
                    break
            house = rest.strip()
            break
    return street, house, flat


def build_address(street, house, flat):
    """Собрать адрес из частей."""
    street = (street or "").strip()
    house = (house or "").strip()
    flat = (flat or "").strip()
    out = street
    if house:
        out += (" " if out else "") + "дом " + house
    if flat:
        out += (" " if out else "") + "кв " + flat
    return out.strip()


def make_digit_cell(bg=INPUTBG, fg=TEXT):
    """Ячейка под одну цифру счётчика."""
    ti = TextInput(
        text="", multiline=False, halign="center",
        background_color=bg, foreground_color=fg,
        cursor_color=ACCENT, padding=[0, dp(10)],
        font_size="17sp", input_type="number",
        size_hint_x=None, width=dp(33),
    )
    return ti

def _ster_btn(inp):
    """Кнопка СТЕР — очищает поле inp."""
    b = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT,
                      border=BORDER, size_hint_x=None,
                      width=dp(64), font_size="10sp")
    b.bind(on_release=lambda *a: setattr(inp, "text", ""))
    return b


def make_num_input(hint=""):
    """Поле для цифр (клавиатура с числами)."""
    ti = make_input(hint)
    ti.input_type = "number"
    return ti

def meter_unit(mtype):
    """Единицы измерения: у света киловатт-часы, у воды кубы."""
    return "кВт\u00b7ч" if (mtype or "").strip() == "ЭЛЕКТРО" else "м3"


def meter_slots(mtype):
    """Сколько ячеек под цифры.
    Вода: 5 целых и 3 красных (дробных).
    Свет (ЭНЕРГОМЕРА CE101 и подобные): 5 целых и 1 красная."""
    return (5, 1) if (mtype or "").strip() == "ЭЛЕКТРО" else (5, 3)


def meter_line(mtype, mval):
    """Строка про счётчик. Тип и цифры — каждое по желанию:
    можно только «ХОЛОДНАЯ», можно с показаниями, можно ничего."""
    t = (mtype or "").strip()
    if t in ("ХВС", "ХОЛОДНАЯ"):
        t = "ХОЛОДНАЯ"
    elif t in ("ГВС", "ГОРЯЧАЯ"):
        t = "ГОРЯЧАЯ"
    elif t:
        t = "ЭЛЕКТРО"
    m = (mval or "").strip()
    u = meter_unit(t)
    if t and m:
        return "%s  %s %s" % (t, m, u)
    if t:
        return t
    if m:
        return "%s %s" % (m, u)
    return ""


def meter_text(entry):
    """Строка показаний счётчика для фото и карточек."""
    return meter_line(entry.get("meter_type", ""), entry.get("meter", ""))

def warm_entry(entry):
    """Заранее перерисовать фото с плашкой после правки текста."""
    f = entry.get("file", "")
    if not f or not os.path.exists(f):
        return
    c1 = entry.get("caption", "")
    c2 = entry.get("comment", "")
    c3 = meter_text(entry)

    def work():
        try:
            stamped_image_path(f, c1, c2, c3)
        except Exception as ex:
            print("warm_entry:", ex)
    threading.Thread(target=work, daemon=True).start()

def split_address(text):
    """Разбить адрес на две строки: улица сверху, дом/кв снизу."""
    if not text:
        return ""
    low = text.lower()
    for key in (" дом", " д.", " д ", " корп", " стр"):
        i = low.find(key)
        if i > 0:
            return text[:i].strip() + "\n" + text[i:].strip()
    return text

def toast(msg):
    """Короткое всплывающее сообщение (само закроется)."""
    lbl = Label(text=msg, color=TEXT, halign="center", valign="middle",
                font_size="15sp")
    lbl.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
    p = Popup(title="", content=lbl, size_hint=(0.85, None), height=dp(180),
              separator_height=0, background_color=(0.05, 0.05, 0.07, 1))
    p.open()
    Clock.schedule_once(lambda dt: p.dismiss(), 2.6)


def confirm_delete(msg, on_yes):
    """Окно подтверждения удаления. on_yes() вызывается при согласии."""
    content = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(16))
    lbl = Label(text=msg, color=TEXT, font_size="16sp",
                halign="center", valign="middle")
    lbl.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
    content.add_widget(lbl)

    p = Popup(title="", content=content, size_hint=(0.86, None), height=dp(230),
              separator_height=0, background_color=(0.05, 0.05, 0.07, 1))
    row = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(12))
    no = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER, font_size="15sp")
    no.bind(on_release=lambda *a: p.dismiss())
    yes = RoundedButton(text="УДАЛИТЬ", bg=DANGER, fg=TEXT, font_size="15sp")

    def do(*a):
        p.dismiss()
        on_yes()
    yes.bind(on_release=do)
    row.add_widget(no)
    row.add_widget(yes)
    content.add_widget(row)
    p.open()

def edit_meter_dialog(entry, on_done=None):
    """Показания счётчика: сверху фото, снизу цифры — одновременно.
    Фото увеличивается пальцами (до 8 раз) и двигается, поэтому можно
    разглядеть цифру, тут же набрать её и сдвинуть фото дальше."""
    content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))

    # --- фото сверху: берём оригинал, он чётче обработанного ---
    src = entry.get("file", "")
    frame = ZoomFrame()
    im = frame.img
    if src and os.path.exists(src):
        im.source = _meter_upright(src)
    else:
        tp = cached_thumb_path(src)
        if tp:
            im.source = _meter_upright(tp)
    content.add_widget(frame)

    st = {"type": entry.get("meter_type", ""),
          "digits": list((entry.get("meter", "") or "").replace(",", ""))}

    # --- вода ---
    trow = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
    b_cold = RoundedButton(text="ХОЛОДНАЯ", bg=BTN2, fg=TEXT, border=BORDER,
                           font_size="11sp")
    b_hot = RoundedButton(text="ГОРЯЧАЯ", bg=BTN2, fg=TEXT, border=BORDER,
                          font_size="11sp")
    b_el = RoundedButton(text="ЭЛЕКТРО", bg=BTN2, fg=TEXT, border=BORDER,
                         font_size="11sp")

    def paint_water():
        b_cold.set_bg(H("#4da3ff") if st["type"] == "ХОЛОДНАЯ" else BTN2)
        b_hot.set_bg(H("#ff5c5c") if st["type"] == "ГОРЯЧАЯ" else BTN2)
        el = (st["type"] == "ЭЛЕКТРО")
        b_el.set_bg(H("#ffd166") if el else BTN2)
        b_el.color = DARKTX if el else TEXT
        build_cells()

    def set_type(t):
        st["type"] = "" if st["type"] == t else t
        paint_water()

    b_cold.bind(on_press=lambda *a: set_type("ХОЛОДНАЯ"))
    b_hot.bind(on_press=lambda *a: set_type("ГОРЯЧАЯ"))
    b_el.bind(on_press=lambda *a: set_type("ЭЛЕКТРО"))
    trow.add_widget(b_cold)
    trow.add_widget(b_hot)
    trow.add_widget(b_el)
    content.add_widget(trow)

    # --- ячейки под цифры ---
    crow = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(2))
    content.add_widget(crow)
    st["cells"] = []

    def build_cells():
        """Ячейки под тип счётчика: у воды 5+3, у света 5+1.
        Перестраиваются, когда переключаешь воду/свет."""
        w_cnt, f_cnt = meter_slots(st["type"])
        total = w_cnt + f_cnt
        st["w_cnt"] = w_cnt
        st["total"] = total
        st["digits"] = st["digits"][:total]
        crow.clear_widgets()
        st["cells"] = []
        crow.add_widget(Label(size_hint_x=1))
        for i in range(total):
            red = i >= w_cnt
            cell = Card(bg=CARD2, border=(H("#ff6b6b") if red else BORDER),
                        radius=5, orientation="vertical",
                        size_hint_x=None, width=dp(30))
            lb = Label(text="", color=(H("#ff6b6b") if red else TEXT),
                       font_size="17sp", bold=True)
            cell.add_widget(lb)
            st["cells"].append(lb)
            crow.add_widget(cell)
            if i == w_cnt - 1:
                crow.add_widget(Label(text=",", color=TEXT, font_size="17sp",
                                      bold=True, size_hint_x=None,
                                      width=dp(9)))
        st["um"] = Label(text=meter_unit(st["type"]), color=MUTED,
                         font_size="11sp", size_hint_x=None, width=dp(40))
        crow.add_widget(st["um"])
        crow.add_widget(Label(size_hint_x=1))
        redraw()

    def redraw():
        for i, lb in enumerate(st["cells"]):
            lb.text = st["digits"][i] if i < len(st["digits"]) else ""

    def tap(d):
        if len(st["digits"]) < st.get("total", 8):
            st["digits"].append(d)
            redraw()

    def back(*a):
        if st["digits"]:
            st["digits"].pop()
            redraw()

    # --- клавиатура ---
    keys = GridLayout(cols=3, size_hint_y=None, height=dp(170), spacing=dp(5))
    for d in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        k = RoundedButton(text=d, bg=CARD2, fg=TEXT, border=BORDER,
                          font_size="19sp")
        k.bind(on_press=lambda *a, dd=d: tap(dd))
        keys.add_widget(k)
    kc = RoundedButton(text="← СТЕРЕТЬ", bg=BTN2, fg=TEXT, border=BORDER,
                       font_size="10sp")
    kc.bind(on_press=back)
    k0 = RoundedButton(text="0", bg=CARD2, fg=TEXT, border=BORDER,
                       font_size="19sp")
    k0.bind(on_press=lambda *a: tap("0"))
    kd = RoundedButton(text="ОЧИСТИТЬ ВСЁ", bg=BTN2, fg=TEXT, border=BORDER,
                       font_size="10sp")

    def clear_digits(*a):
        st["digits"] = []
        redraw()
    kd.bind(on_press=clear_digits)
    keys.add_widget(kc)
    keys.add_widget(k0)
    keys.add_widget(kd)
    content.add_widget(keys)

    pp = Popup(title="Показания счётчика", content=content,
               size_hint=(0.98, 0.96),
               title_color=TEXT, separator_color=ACCENT,
               background_color=(0.05, 0.05, 0.07, 1))

    def save(*a):
        ds = st["digits"]
        whole = "".join(ds[:st.get("w_cnt", 5)])
        frac = "".join(ds[st.get("w_cnt", 5):])
        val = ""
        if whole or frac:
            val = (whole or "0") + ("," + frac if frac else "")
        if val:
            entry["meter"] = val
        else:
            entry.pop("meter", None)
        if st["type"]:
            entry["meter_type"] = st["type"]
        else:
            entry.pop("meter_type", None)
        App.get_running_app().save()
        warm_entry(entry)
        pp.dismiss()
        if on_done:
            on_done()

    def wipe(*a):
        entry.pop("meter", None)
        entry.pop("meter_type", None)
        App.get_running_app().save()
        warm_entry(entry)
        pp.dismiss()
        if on_done:
            on_done()

    row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
    cl = RoundedButton(text="УБРАТЬ", bg=BTN2, fg=TEXT, border=BORDER,
                       font_size="12sp")
    cl.bind(on_press=wipe)
    cn = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                       font_size="12sp")
    cn.bind(on_press=lambda *a: pp.dismiss())
    ok = RoundedButton(text="ГОТОВО", bg=ACCENT, fg=DARKTX, font_size="13sp")
    ok.bind(on_press=save)
    row.add_widget(cl)
    row.add_widget(cn)
    row.add_widget(ok)
    content.add_widget(row)

    build_cells()
    paint_water()
    pp.open()


def logo_texture():
    """Вшитый логотип как картинка для экрана.
    Отдельный файл не нужен: берём из LOGO_B64 (или logo_mark.png,
    если он положен рядом)."""
    try:
        from kivy.core.image import Image as CoreImage
        import base64
        import io
        if os.path.exists(LOGO_MARK):
            return CoreImage(LOGO_MARK).texture
        data = io.BytesIO(base64.b64decode(LOGO_B64))
        return CoreImage(data, ext="png").texture
    except Exception as e:
        print("Логотип на экран не встал:", e)
        return None


def logo_image(**kw):
    """Готовый виджет с логотипом."""
    im = Image(allow_stretch=True, keep_ratio=True, **kw)
    tx = logo_texture()
    if tx is not None:
        im.texture = tx
    return im


# =====================================================================
#  ЭКРАН 1: КАМЕРА (авто-запуск штатной камеры)
# =====================================================================

class CameraScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)

        # Фон-картинка. Лежит рядом со скриптом — рисуем её,
        # нет файла — остаётся обычный тёмный фон.
        self._bg = None
        if os.path.exists(FON_FILE):
            with self.canvas.before:
                Color(1, 1, 1, 1)
                self._bg = Rectangle(source=FON_FILE, pos=self.pos,
                                     size=self.size)
            self.bind(pos=self._upd_bg, size=self._upd_bg)

        root = BoxLayout(orientation="vertical", spacing=dp(10),
                         padding=[dp(16), dp(12)])

        # шапка-полоса: логотип и название
        head = Card(bg=(0.05, 0.12, 0.16, 0.85), radius=12,
                    orientation="horizontal", size_hint_y=None,
                    height=dp(50), padding=[dp(10), dp(6)], spacing=dp(10))
        head.add_widget(logo_image(size_hint_x=None, width=dp(30)))
        cap = Label(text="ФОТО-ОТПРАВЩИК", color=TEXT, font_size="15sp",
                    bold=True, halign="left", valign="middle")
        cap.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
        head.add_widget(cap)
        root.add_widget(head)

        # Название кооператива — прямо на картинке, без подложки.
        # Чтобы читалось на пёстром фоне, у букв чёрная обводка.
        name = Label(text="ЖСК КЛЕН", color=H("#ffd166"), font_size="30sp",
                     bold=True, size_hint_y=None, height=dp(48),
                     halign="center", valign="middle",
                     outline_width=2, outline_color=(0, 0, 0, 1))
        name.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
        root.add_widget(name)

        self.status = Label(
            text="Нажмите «СНЯТЬ ФОТО», чтобы сделать снимок.",
            color=(0.92, 0.92, 0.92, 1), font_size="13sp",
            size_hint_y=None, height=dp(36),
            halign="center", valign="middle",
            outline_width=2, outline_color=(0, 0, 0, 1))
        self.status.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
        root.add_widget(self.status)

        # пусто: тут видно картинку
        root.add_widget(Label(size_hint_y=1))

        self.btn = RoundedButton(text="СНЯТЬ ФОТО", bg=ACCENT, fg=DARKTX,
                                 size_hint_y=None, height=dp(64),
                                 font_size="18sp")
        self.btn.bind(on_release=lambda *a: self.launch())
        root.add_widget(self.btn)

        arch = RoundedButton(text="АРХИВ", bg=H("#3d4a63"), fg=TEXT,
                             border=BORDER, size_hint_y=None, height=dp(56),
                             font_size="16sp")
        arch.bind(on_release=lambda *a: self.go_archive())
        root.add_widget(arch)

        ex = RoundedButton(text="ВЫХОД", bg=H("#e06a6a"), fg=TEXT,
                           size_hint_y=None, height=dp(52), font_size="15sp")
        ex.bind(on_release=lambda *a: self.exit_app())
        root.add_widget(ex)

        root.add_widget(body_label("ЖСК КЛЕН", color=(0.7, 0.7, 0.7, 1),
                                   size="11sp", h=dp(20), halign="center"))

        self.add_widget(root)

    def _upd_bg(self, *a):
        if self._bg is not None:
            self._bg.pos = self.pos
            self._bg.size = self.size

    def exit_app(self):
        app = App.get_running_app()
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            activity.finishAndRemoveTask()
        except Exception as e:
            print("Выход:", e)
        app.stop()

    def on_enter(self, *a):
        # Стартовая страница. Камера открывается по кнопке «СНЯТЬ ФОТО».
        if not App.get_running_app()._cam:
            self.status.text = "Нажмите «СНЯТЬ ФОТО», чтобы сделать снимок."

    def launch(self):
        app = App.get_running_app()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(PHOTO_DIR, "photo_%s.jpg" % ts)
        self.status.text = "Открываю камеру..."
        app.launch_camera(path, self._done, self._set_status)

    def _set_status(self, msg):
        self.status.text = msg

    def _done(self, path):
        app = App.get_running_app()
        if path and os.path.exists(path):
            app.current_photo = path
            self.status.text = ""
            self.manager.transition.direction = "left"
            self.manager.current = "review"
        else:
            self.status.text = ("Съёмка отменена или камера недоступна.\n"
                                "Нажмите «СНЯТЬ ФОТО», чтобы попробовать снова.")

    def go_archive(self):
        self.manager.transition.direction = "left"
        self.manager.current = "archive"


# =====================================================================
#  ЭКРАН 2: ПРОВЕРКА (Отправить / Переснять)
# =====================================================================

class ReviewScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        root.add_widget(title_label("ПРОВЕРКА СНИМКА", color=TEXT))

        # Фото в рамке с зумом (два пальца) и значком-стрелками.
        self._frame = ZoomFrame()
        self.img = self._frame.img

        # Хранилище значений (полей ввода на экране больше нет)
        self.street_val = ""
        self.house_val = ""
        self.flat_val = ""
        self.comment_val = ""
        self.meter_type = ""
        self.meter_data = ""

        # --- Редкое: адрес и комментарий, каждый в своей рамке, мелко ---
        # Читать тут не нужно: нажал ИЗМЕНИТЬ — в отдельном окне крупно.
        abox = Card(bg=(1, 1, 1, 0.03), border=BORDER, radius=8,
                    orientation="horizontal", size_hint_y=None, height=dp(32),
                    padding=[dp(8), dp(2)], spacing=dp(6))
        self.addr_lbl = Label(text="", color=H("#ffd166"), font_size="11sp",
                              bold=True, halign="left", valign="middle")
        self.addr_lbl.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
        ea = RoundedButton(text="ИЗМЕНИТЬ", bg=ACCENT2, fg=TEXT,
                           size_hint_x=None, width=dp(88), font_size="9sp")
        ea.bind(on_release=lambda *a: self.edit_address())
        abox.add_widget(self.addr_lbl)
        abox.add_widget(ea)
        root.add_widget(abox)

        cbox = Card(bg=(1, 1, 1, 0.03), border=BORDER, radius=8,
                    orientation="horizontal", size_hint_y=None, height=dp(32),
                    padding=[dp(8), dp(2)], spacing=dp(6))
        self.com_lbl = Label(text="", color=MUTED, font_size="10sp",
                             halign="left", valign="middle")
        self.com_lbl.bind(size=lambda w, *a: setattr(w, "text_size", w.size))
        ec = RoundedButton(text="ИЗМЕНИТЬ", bg=BTN2, fg=TEXT, border=BORDER,
                           size_hint_x=None, width=dp(88), font_size="9sp")
        ec.bind(on_release=lambda *a: self.edit_comment())
        cbox.add_widget(self.com_lbl)
        cbox.add_widget(ec)
        root.add_widget(cbox)

        # Фото — под адресом и комментарием,
        # чтобы кнопки внизу оставались на виду.
        root.add_widget(self._frame)
        root.add_widget(body_label("Фото увеличивается двумя пальцами",
                                   color=MUTED, size="11sp", h=dp(18),
                                   halign="center"))

        # --- Частое: тип счётчика ---
        mrow = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.b_cold = RoundedButton(text="ХОЛОДНАЯ", bg=BTN2, fg=TEXT,
                                    border=BORDER, font_size="11sp")
        self.b_cold.bind(on_press=lambda *a: self.pick_water("ХОЛОДНАЯ"))
        self.b_hot = RoundedButton(text="ГОРЯЧАЯ", bg=BTN2, fg=TEXT,
                                   border=BORDER, font_size="11sp")
        self.b_hot.bind(on_press=lambda *a: self.pick_water("ГОРЯЧАЯ"))
        self.b_el = RoundedButton(text="ЭЛЕКТРО", bg=BTN2, fg=TEXT,
                                  border=BORDER, font_size="11sp")
        self.b_el.bind(on_press=lambda *a: self.pick_water("ЭЛЕКТРО"))
        mrow.add_widget(self.b_cold)
        mrow.add_widget(self.b_hot)
        mrow.add_widget(self.b_el)
        root.add_widget(mrow)

        keep = RoundedButton(text="СОХРАНИТЬ В АРХИВ", bg=ACCENT, fg=DARKTX,
                             size_hint_y=None, height=dp(46), font_size="12sp")
        keep.bind(on_release=lambda *a: self.save_only())
        root.add_widget(keep)

        # --- Частое: снизу. Главная — СОХРАНИТЬ (зелёная) ---
        row1 = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        retake = RoundedButton(text="ПЕРЕСНЯТЬ", bg=BTN2, fg=TEXT,
                               border=BORDER, font_size="14sp")
        retake.bind(on_release=lambda *a: self.retake())
        self.meter_btn = RoundedButton(text="ПОКАЗАНИЯ", bg=BTN2, fg=TEXT,
                                       border=BORDER, font_size="13sp")
        self.meter_btn.bind(on_press=lambda *a: self.open_meter())
        row1.add_widget(retake)
        row1.add_widget(self.meter_btn)
        root.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             font_size="14sp")
        back.bind(on_release=lambda *a: self.go_back())
        send = RoundedButton(text="ОТПРАВИТЬ", bg=ACCENT2, fg=TEXT,
                             font_size="14sp")
        send.bind(on_release=lambda *a: self.go_send())
        row2.add_widget(back)
        row2.add_widget(send)
        root.add_widget(row2)

        self.add_widget(root)

    # ---------- счётчик ----------
    def pick_water(self, t):
        self.meter_type = "" if self.meter_type == t else t
        self._upd_meter()

    def _upd_meter(self):
        self.b_cold.set_bg(H("#4da3ff") if self.meter_type == "ХОЛОДНАЯ"
                           else BTN2)
        self.b_cold.color = TEXT
        self.b_hot.set_bg(H("#ff5c5c") if self.meter_type == "ГОРЯЧАЯ"
                          else BTN2)
        self.b_hot.color = TEXT
        el = (self.meter_type == "ЭЛЕКТРО")
        self.b_el.set_bg(H("#ffd166") if el else BTN2)
        self.b_el.color = DARKTX if el else TEXT
        if self.meter_data:
            self.meter_btn.text = "%s %s" % (self.meter_data,
                                             meter_unit(self.meter_type))
            self.meter_btn.set_bg(ACCENT2)
            self.meter_btn.color = TEXT
        else:
            self.meter_btn.text = "ПОКАЗАНИЯ"
            self.meter_btn.set_bg(BTN2)
            self.meter_btn.color = TEXT

    def open_meter(self):
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            padding=dp(10))
        w_cnt, f_cnt = meter_slots(self.meter_type)
        total = w_cnt + f_cnt
        st = {"digits": list((self.meter_data or "").replace(",", ""))[:total]}

        crow = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(2))
        crow.add_widget(Label(size_hint_x=1))
        cells = []
        for i in range(total):
            red = i >= w_cnt
            cell = Card(bg=CARD2, border=(H("#ff6b6b") if red else BORDER),
                        radius=5, orientation="vertical",
                        size_hint_x=None, width=dp(30))
            lb = Label(text="", color=(H("#ff6b6b") if red else TEXT),
                       font_size="17sp", bold=True)
            cell.add_widget(lb)
            cells.append(lb)
            crow.add_widget(cell)
            if i == w_cnt - 1:
                crow.add_widget(Label(text=",", color=TEXT, font_size="17sp",
                                      bold=True, size_hint_x=None,
                                      width=dp(9)))
        crow.add_widget(Label(text=meter_unit(self.meter_type), color=MUTED,
                              font_size="11sp", size_hint_x=None, width=dp(40)))
        crow.add_widget(Label(size_hint_x=1))
        content.add_widget(crow)

        def redraw():
            for i, lb in enumerate(cells):
                lb.text = st["digits"][i] if i < len(st["digits"]) else ""

        def tap(d):
            if len(st["digits"]) < total:
                st["digits"].append(d)
                redraw()

        def back(*a):
            if st["digits"]:
                st["digits"].pop()
                redraw()

        keys = GridLayout(cols=3, size_hint_y=None, height=dp(190),
                          spacing=dp(6))
        for d in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            k = RoundedButton(text=d, bg=CARD2, fg=TEXT, border=BORDER,
                              font_size="20sp")
            k.bind(on_press=lambda *a, dd=d: tap(dd))
            keys.add_widget(k)
        kc = RoundedButton(text="СТЕРЕТЬ", bg=BTN2, fg=TEXT, border=BORDER,
                           font_size="11sp")
        kc.bind(on_press=back)
        k0 = RoundedButton(text="0", bg=CARD2, fg=TEXT, border=BORDER,
                           font_size="20sp")
        k0.bind(on_press=lambda *a: tap("0"))
        kd = RoundedButton(text="ОЧИСТИТЬ ВСЁ", bg=BTN2, fg=TEXT,
                           border=BORDER, font_size="10sp")

        def clear_digits(*a):
            st["digits"] = []
            redraw()
        kd.bind(on_press=clear_digits)
        keys.add_widget(kc)
        keys.add_widget(k0)
        keys.add_widget(kd)
        content.add_widget(keys)

        pp = Popup(title="Показания счётчика", content=content,
                   size_hint=(0.96, None), height=dp(370),
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            ds = st["digits"]
            whole = "".join(ds[:w_cnt])
            frac = "".join(ds[w_cnt:])
            val = ""
            if whole or frac:
                val = (whole or "0") + ("," + frac if frac else "")
            self.meter_data = val
            self._upd_meter()
            pp.dismiss()

        def cancel_meter(*a):
            self.meter_data = ""
            self._upd_meter()
            pp.dismiss()

        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        cl = RoundedButton(text="УБРАТЬ", bg=BTN2, fg=TEXT, border=BORDER,
                           font_size="13sp")
        cl.bind(on_press=cancel_meter)
        ok = RoundedButton(text="ГОТОВО", bg=ACCENT, fg=DARKTX, font_size="14sp")
        ok.bind(on_press=save)
        row.add_widget(cl)
        row.add_widget(ok)
        content.add_widget(row)

        redraw()
        pp.open()

    # ---------- адрес в отдельном окне ----------
    def edit_address(self):
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            padding=dp(14))

        row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="14sp")
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX,
                           font_size="14sp")
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row)

        content.add_widget(body_label("Улица:", color=MUTED, size="13sp",
                                      h=dp(20)))
        s_in = make_input("Улица")
        s_in.text = self.street_val
        srow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        srow.add_widget(s_in)
        s_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER,
                              size_hint_x=None, width=dp(72), font_size="11sp")
        s_clr.bind(on_release=lambda *a: setattr(s_in, "text", ""))
        srow.add_widget(s_clr)
        content.add_widget(srow)

        content.add_widget(body_label("Дом и квартира:", color=MUTED,
                                      size="13sp", h=dp(20)))
        hk = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        h_in = make_num_input("Дом")
        h_in.text = self.house_val
        h_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER,
                              size_hint_x=None, width=dp(64), font_size="10sp")
        h_clr.bind(on_release=lambda *a: setattr(h_in, "text", ""))
        f_in = make_num_input("Кв")
        f_in.text = self.flat_val
        f_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER,
                              size_hint_x=None, width=dp(64), font_size="10sp")
        f_clr.bind(on_release=lambda *a: setattr(f_in, "text", ""))
        hk.add_widget(h_in)
        hk.add_widget(h_clr)
        hk.add_widget(f_in)
        hk.add_widget(f_clr)
        content.add_widget(hk)
        content.add_widget(Label(size_hint_y=1))

        pp = Popup(title="Изменить адрес", content=content,
                   size_hint=(0.94, None), height=dp(340),
                   pos_hint={"top": 0.98}, title_color=TEXT,
                   separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            self.street_val = s_in.text.strip()
            self.house_val = h_in.text.strip()
            self.flat_val = f_in.text.strip()
            self._upd_addr()
            pp.dismiss()

        cancel.bind(on_release=lambda *a: pp.dismiss())
        ok.bind(on_release=save)
        pp.open()

    def edit_comment(self):
        content = BoxLayout(orientation="vertical", spacing=dp(10),
                            padding=dp(14))

        row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="14sp")
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX,
                           font_size="14sp")
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row)

        ti = make_input("Комментарий")
        ti.text = self.comment_val
        content.add_widget(ti)
        content.add_widget(Label(size_hint_y=1))

        pp = Popup(title="Изменить комментарий", content=content,
                   size_hint=(0.94, None), height=dp(220),
                   pos_hint={"top": 0.98}, title_color=TEXT,
                   separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        _skip7 = [False]

        def _apply7(*a):
            self.comment_val = ti.text.strip()
            self._upd_addr()

        def save(*a):
            _apply7()
            _skip7[0] = True
            pp.dismiss()

        def _cancel7(*a):
            _skip7[0] = True
            pp.dismiss()

        def _dism7(*a):
            if not _skip7[0]:
                _apply7()
            return False

        pp.bind(on_dismiss=_dism7)
        ti.bind(on_text_validate=lambda *a: save())
        cancel.bind(on_release=_cancel7)
        ok.bind(on_release=save)
        pp.open()

    def _upd_addr(self):
        self.addr_lbl.text = build_address(self.street_val, self.house_val,
                                           self.flat_val) or "Адрес не указан"
        self.com_lbl.text = self.comment_val or "Комментарий не указан"

    # ---------- вход/выход ----------
    def on_enter(self, *a):
        app = App.get_running_app()
        st, ho, fl = parse_address(app.data.get("default_address", ""))
        self.street_val = st
        self.house_val = ho
        self.flat_val = fl
        self.comment_val = ""
        self.meter_type = ""
        self.meter_data = ""
        self._upd_addr()
        self._upd_meter()
        if app.current_photo:
            self.img.source = app.current_photo
            self.img.reload()

    def retake(self):
        app = App.get_running_app()
        try:
            if app.current_photo and os.path.exists(app.current_photo):
                os.remove(app.current_photo)
        except Exception as e:
            print("Не удалось удалить снимок:", e)
        app.current_photo = None
        self.manager.transition.direction = "right"
        self.manager.current = "camera"
        cam = self.manager.get_screen("camera")
        Clock.schedule_once(lambda dt: cam.launch(), 0.15)

    def _collect(self):
        app = App.get_running_app()
        app.current_caption = build_address(self.street_val, self.house_val,
                                            self.flat_val)
        app.current_comment = self.comment_val
        app.current_meter = self.meter_data
        app.current_meter_type = self.meter_type

    def go_send(self):
        self._collect()
        self.manager.transition.direction = "left"
        self.manager.current = "method"

    def go_back(self):
        app = App.get_running_app()
        try:
            if app.current_photo and os.path.exists(app.current_photo):
                os.remove(app.current_photo)
        except Exception as e:
            print("Не удалось удалить снимок:", e)
        app.current_photo = None
        app.current_caption = ""
        app.current_comment = ""
        self.manager.transition.direction = "right"
        self.manager.current = "camera"

    def save_only(self):
        self._collect()
        app = App.get_running_app()
        app.add_to_archive(method="Сохранено", recipient="")
        app.current_photo = None
        self.manager.transition.direction = "left"
        self.manager.current = "archive"


# =====================================================================
#  ЭКРАН 3: СПОСОБ ОТПРАВКИ (MMS / MAX)
# =====================================================================

class SendMethodScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(18))
        root.add_widget(title_label("КАК ОТПРАВИТЬ?", color=TEXT))

        mms = RoundedButton(text="MMS  (на номер из списка)", bg=ACCENT2, fg=TEXT,
                            size_hint_y=None, height=dp(96), font_size="17sp")
        mms.bind(on_release=lambda *a: self.pick_mms())
        root.add_widget(mms)

        mx = RoundedButton(text="MAX / ПОДЕЛИТЬСЯ\n(адресата выбираете в MAX)",
                           bg=ACCENT, fg=DARKTX,
                           size_hint_y=None, height=dp(96), font_size="15sp")
        mx.bind(on_release=lambda *a: self.pick_max())
        root.add_widget(mx)

        root.add_widget(Label(size_hint_y=1))  # растяжка

        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             size_hint_y=None, height=dp(64), font_size="16sp")
        back.bind(on_release=lambda *a: self.go_back())
        root.add_widget(back)

        self.add_widget(root)

    def pick_mms(self):
        self.manager.transition.direction = "left"
        self.manager.current = "mms"

    def pick_max(self):
        app = App.get_running_app()
        _mt = meter_line(app.current_meter_type, app.current_meter)
        to_send = stamped_image_path(app.current_photo, app.current_caption,
                                    app.current_comment, _mt)
        ok = share_photo(to_send)
        if not ok:
            toast("Не удалось открыть «Поделиться».\n"
                  "Проверьте разрешения на фото/хранилище.")
            return
        app.add_to_archive(method="MAX", recipient="")
        app.current_photo = None
        self.manager.transition.direction = "left"
        self.manager.current = "archive"

    def go_back(self):
        self.manager.transition.direction = "right"
        self.manager.current = "review"

# =====================================================================
#  ЭКРАН 4: ВЫБОР АДРЕСАТА ДЛЯ MMS
#  Два режима отображения (переключаются в настройках):
#    "list" — все имена списком
#    "last" — последний адресат крупно + плюс для остальных
# =====================================================================

class MMSScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._show_all = False  # для режима "last": раскрыт ли полный список
        self.root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        self.add_widget(self.root)

    def on_enter(self, *a):
        self._show_all = False
        self.rebuild()

    def rebuild(self):
        app = App.get_running_app()
        self.root.clear_widgets()
        self.root.add_widget(title_label("КОМУ ОТПРАВИТЬ (MMS)", color=TEXT))

        recips = app.data.get("recipients", [])
        mode = app.data.get("settings", {}).get("mms_mode", "list")

        scroll = ScrollView()
        col = GridLayout(cols=1, spacing=dp(12), size_hint_y=None, padding=[0, dp(4)])
        col.bind(minimum_height=col.setter("height"))

        if not recips:
            col.add_widget(body_label("Пока нет ни одного адресата.",
                                      color=MUTED, size="15sp", h=dp(40),
                                      halign="center"))
        elif mode == "last" and not self._show_all:
            # Показываем только последнего адресата крупно
            idx = app.data.get("last_recipient", 0)
            if idx >= len(recips):
                idx = 0
            r = recips[idx]
            big = RoundedButton(text=r["name"], bg=ACCENT, fg=DARKTX,
                                size_hint_y=None, height=dp(96), font_size="20sp")
            big.bind(on_release=lambda *a, i=idx: self.do_send(i))
            col.add_widget(big)
            if len(recips) > 1:
                other = RoundedButton(text="ДРУГОЙ  +", bg=BTN2, fg=TEXT, border=BORDER,
                                      size_hint_y=None, height=dp(72), font_size="16sp")
                other.bind(on_release=lambda *a: self._expand())
                col.add_widget(other)
        else:
            # Полный список имён
            for i, r in enumerate(recips):
                b = RoundedButton(text=r["name"], bg=CARD2, fg=TEXT, border=BORDER,
                                  size_hint_y=None, height=dp(78), font_size="18sp")
                b.bind(on_release=lambda *a, idx=i: self.do_send(idx))
                col.add_widget(b)

        # Кнопка добавить нового адресата
        add = RoundedButton(text="+  ДОБАВИТЬ НОМЕР", bg=ACCENT2, fg=TEXT,
                            size_hint_y=None, height=dp(72), font_size="16sp")
        add.bind(on_release=lambda *a: self.add_popup())
        col.add_widget(add)

        scroll.add_widget(col)
        self.root.add_widget(scroll)

        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             size_hint_y=None, height=dp(64), font_size="16sp")
        back.bind(on_release=lambda *a: self.go_back())
        self.root.add_widget(back)

    def _expand(self):
        self._show_all = True
        self.rebuild()

    def do_send(self, index):
        app = App.get_running_app()
        recips = app.data.get("recipients", [])
        if index >= len(recips):
            return
        r = recips[index]
        _mt = meter_line(app.current_meter_type, app.current_meter)
        to_send = stamped_image_path(app.current_photo, app.current_caption,
                                    app.current_comment, _mt)
        ok = send_mms(to_send, r["number"])
        if not ok:
            toast("Не удалось открыть отправку MMS.\n"
                  "Проверьте разрешения и приложение сообщений.")
            return
        app.data["last_recipient"] = index
        app.save()
        app.add_to_archive(method="MMS", recipient=r["name"])
        app.current_photo = None
        self.manager.transition.direction = "left"
        self.manager.current = "archive"

    def add_popup(self, then_send=True):
        app = App.get_running_app()
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14))
        name_in = make_input("Имя (например, Олег)")
        num_in = make_input("Номер (+7...)")
        content.add_widget(name_in)
        content.add_widget(num_in)

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12))
        popup = Popup(title="Новый адресат", content=content,
                      size_hint=(0.9, None), height=dp(300),
                      pos_hint={"top": 0.98},
                      title_color=TEXT, separator_color=ACCENT,
                      background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            name = name_in.text.strip()
            num = num_in.text.strip()
            if not name or not num:
                return
            app.data["recipients"].append({"name": name, "number": num})
            app.data["last_recipient"] = len(app.data["recipients"]) - 1
            app.save()
            popup.dismiss()
            if then_send:
                self.do_send(len(app.data["recipients"]) - 1)
            else:
                self.rebuild()

        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER, font_size="15sp")
        cancel.bind(on_release=lambda *a: popup.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        popup.open()

    def go_back(self):
        self.manager.transition.direction = "right"
        self.manager.current = "method"

# =====================================================================
#  ЭКРАН 5: АРХИВ (миниатюры, дата, адресат, способ, адрес, удаление)
# =====================================================================

class ArchiveScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.selected = set()
        self.root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        self.add_widget(self.root)

    def on_enter(self, *a):
        self.selected = set()
        self.rebuild()

    def rebuild(self):
        app = App.get_running_app()
        self.root.clear_widgets()
        self._card_updaters = {}
        archive = app.data.get("archive", [])

        # Главная кнопка — крупная и отдельно
        _srow = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(8))
        shot = RoundedButton(text="СНЯТЬ ФОТО", bg=ACCENT, fg=DARKTX,
                             border=H("#bff4dc"), font_size="19sp")
        shot.bind(on_release=lambda *a: self.go_camera())
        _srow.add_widget(shot)
        _srow.add_widget(Label(size_hint_x=None, width=dp(56)))
        self.root.add_widget(_srow)

        top1 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        # Слева всегда «уйти отсюда»: без выделения — на главную,
        # с выделением — назад. Кнопку назад привычнее искать слева.
        home = RoundedButton(text="ГЛАВНАЯ", bg=ACCENT2, fg=TEXT,
                             border=H("#cfe4ff"), font_size="12sp")

        def _home_press(*a):
            if self.selected:
                self.clear_selection()
            else:
                self.go_home()
        home.bind(on_release=_home_press)
        self._home_btn = home
        gal = RoundedButton(text="ГАЛЕРЕЯ", bg=BTN2, fg=TEXT, border=BORDER,
                            font_size="12sp")
        gal.bind(on_release=lambda *a: self.go_gallery())
        sett = RoundedButton(text="      НАСТРОЙКИ", bg=BTN2, fg=H("#ffd166"), border=BORDER,
                             font_size="10sp")
        sett.bind(on_release=lambda *a: self.go_settings())
        import math as _gm
        def _draw_gear(*_a):
            from kivy.graphics import Color as _GC, Line as _GL
            sett.canvas.after.clear()
            cx = sett.x + dp(10); cy = sett.center_y; r = dp(5)
            with sett.canvas.after:
                _GC(1.0, 0.82, 0.40, 1)
                _GL(circle=(cx, cy, r), width=2.4)
                _GL(circle=(cx, cy, r * 0.45), width=1.9)
                for _k in range(8):
                    _an = _gm.pi * 2 * _k / 8.0
                    _GL(points=[cx + _gm.cos(_an) * r, cy + _gm.sin(_an) * r, cx + _gm.cos(_an) * (r + dp(3.2)), cy + _gm.sin(_an) * (r + dp(3.2))], width=2.4)
        sett.bind(pos=_draw_gear, size=_draw_gear)
        top1.add_widget(home)
        top1.add_widget(gal)
        top1.add_widget(sett)
        self.root.add_widget(top1)

        # Кнопки выделения тут не висят: они появляются сами,
        # когда тронешь галочку на фото (см. _refresh_actions).

        # Панель действий (обновляется без перестройки списка)
        self.act_container = BoxLayout(orientation="vertical", size_hint_y=None,
                                       height=0, spacing=dp(10))
        self.root.add_widget(self.act_container)

        self.root.add_widget(title_label("АРХИВ — СЕГОДНЯ", color=ACCENT,
                                         size="18sp"))

        if not archive:
            self.root.add_widget(body_label("Архив пуст.", color=MUTED,
                                            size="15sp", h=dp(40), halign="center"))
            self.root.add_widget(Label(size_hint_y=1))
            return

        scroll = ScrollView()
        colw = GridLayout(cols=1, spacing=dp(12), size_hint_y=None, padding=[0, dp(4)])
        colw.bind(minimum_height=colw.setter("height"))

        # В архиве — только сегодняшние фото. Прошлые дни — в «ГАЛЕРЕЕ».
        today = datetime.now().strftime("%d.%m.%Y")
        shown = 0
        for real_index in range(len(archive) - 1, -1, -1):
            entry = archive[real_index]
            if (entry.get("date", "")[:10]) != today:
                continue
            colw.add_widget(self._make_card(entry, real_index))
            shown += 1

        if shown == 0:
            colw.add_widget(body_label("Сегодня фото ещё нет.\n"
                                       "Прошлые дни — в «ГАЛЕРЕЕ».",
                                       color=MUTED, size="15sp", h=dp(70),
                                       halign="center"))
        else:
            colw.add_widget(body_label("Прошлые дни — в «ГАЛЕРЕЕ»",
                                       color=MUTED, size="13sp", h=dp(40),
                                       halign="center"))

        scroll.add_widget(colw)
        self.root.add_widget(scroll)
        self._refresh_actions()

    def _preheat_today(self):
        """Заранее готовим сегодняшние фото с плашкой — просмотр без ожидания."""
        app = App.get_running_app()
        today = datetime.now().strftime("%d.%m.%Y")
        items = [e for e in app.data.get("archive", [])
                 if (e.get("date", "")[:10]) == today]

        def work():
            for e in items:
                try:
                    f = e.get("file", "")
                    if not f or not os.path.exists(f):
                        continue
                    c1, c2 = e.get("caption", ""), e.get("comment", "")
                    if not c1 and not c2:
                        continue
                    if stamped_ready(f, c1, c2):
                        continue
                    stamped_image_path(f, c1, c2)
                except Exception as ex:
                    print("preheat archive:", ex)
        threading.Thread(target=work, daemon=True).start()

    def _refresh_actions(self):
        """Ряд действий виден только когда что-то выбрано.
        Кнопка выделения одна и меняется по состоянию — так меньше
        кнопок и не надо искать нужную."""
        c = getattr(self, "act_container", None)
        if c is None:
            return
        c.clear_widgets()
        n = len(self.selected)

        # Левая кнопка подрабатывает кнопкой «назад»
        hb = getattr(self, "_home_btn", None)
        if hb is not None:
            hb.text = "НАЗАД" if n else "ГЛАВНАЯ"
            hb.set_bg(BACKC if n else ACCENT2)

        if not n:
            c.height = 0
            return

        shown = set(self._card_updaters.keys())
        all_on = bool(shown) and shown.issubset(self.selected)

        c.height = dp(94)
        box = BoxLayout(orientation="vertical", size_hint_y=None,
                        height=dp(94), spacing=dp(6))

        row1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        if all_on:
            # Выделено всё: теперь осмысленно отправить (зелёная ниже),
            # поэтому эта кнопка нарочно тусклая.
            b = RoundedButton(text="СНЯТЬ ВЫДЕЛЕНИЕ", bg=BTN2, fg=TEXT,
                              border=BORDER, font_size="13sp")
            b.bind(on_release=lambda *a: self.clear_selection())
        else:
            # Жёлтая — единственная такая на экране, находится сразу.
            b = RoundedButton(text="ВЫДЕЛИТЬ ВСЕ ФОТО", bg=H("#ffd166"),
                              fg=DARKTX, border=None, font_size="13sp")
            b.bind(on_release=lambda *a: self.select_all())
        row1.add_widget(b)
        box.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        send = RoundedButton(text="ОТПРАВИТЬ (%d)" % n, bg=ACCENT, fg=DARKTX,
                             font_size="14sp")
        send.bind(on_release=lambda *a: self.send_selected())
        dely = RoundedButton(text="УДАЛИТЬ (%d)" % n, bg=DANGER, fg=TEXT,
                             font_size="14sp")
        dely.bind(on_release=lambda *a: self.delete_selected())
        row2.add_widget(send)
        row2.add_widget(dely)
        box.add_widget(row2)

        c.add_widget(box)

    def _group_header(self, text):
        lb = Label(text=text, color=H("#8ab4ff"), font_size="15sp", bold=True,
                   size_hint_y=None, height=dp(40), halign="left", valign="middle")
        lb.bind(size=lambda w, *a: setattr(w, "text_size", (w.width, None)))
        return lb

    def _make_card(self, entry, index):
        selected = index in self.selected
        bg = CARD2 if selected else CARD
        top_h = dp(190)          # фото + кнопки ПРОСМОТР/УДАЛИТЬ
        cap_h = dp(35)
        com_h = dp(39)
        card_h = dp(18) + top_h + dp(6) + cap_h + dp(4) + com_h
        card = Card(bg=bg, orientation="vertical", size_hint_y=None,
                    height=card_h, padding=dp(10), spacing=dp(8))

        # Рамка выделения (всегда есть, прозрачная когда не выбрано)
        with card.canvas.after:
            bcol = Color(*ACCENT)
            bcol.a = 1 if selected else 0
            bln = Line(width=2.0)

        def _upd_ln(*a, ln=bln, c=card):
            ln.rounded_rectangle = (c.x, c.y, c.width, c.height, 18)
        card.bind(pos=_upd_ln, size=_upd_ln)

        # Верхняя строка: большое фото + информация справа
        top = BoxLayout(orientation="horizontal", size_hint_y=None,
                        height=top_h, spacing=dp(12))

        thumb = ImageButton(allow_stretch=True, keep_ratio=True)
        tp = cached_thumb_path(entry.get("file"))
        src_exists = bool(entry.get("file") and os.path.exists(entry["file"]))
        if tp:
            thumb.source = tp
        elif src_exists:
            self._load_thumb_async(entry["file"], thumb)
        else:
            # Фото недоступно (например, удалено) — тёмная заглушка вместо белого
            with thumb.canvas.before:
                Color(0.16, 0.16, 0.22, 1)
                _mr = RoundedRectangle(radius=[8])

            def _upd_mr(*a, r=_mr, t=thumb):
                r.pos = t.pos
                r.size = t.size
            thumb.bind(pos=_upd_mr, size=_upd_mr)
        thumb.bind(on_release=lambda *a, i=index: self.toggle_select(i))

        # Галочка-квадратик в левом верхнем углу фото (обновляемая)
        chk_state = {"sel": selected}
        with thumb.canvas.after:
            sqcol = Color(*(ACCENT if selected else (0, 0, 0, 0.45)))
            csq = RoundedRectangle(size=(dp(30), dp(30)), pos=(-100, -100),
                                   radius=[6])
            chkcol = Color(*(DARKTX if selected else (1, 1, 1, 0.9)))
            cln = Line(width=2.2 if selected else 1.6)

        def _draw_chk(*a, th=thumb, sq=csq, ln=cln, st=chk_state):
            s = dp(30)
            x = th.x + dp(5)
            y = th.top - s - dp(5)
            sq.pos = (x, y)
            sq.size = (s, s)
            if st["sel"]:
                ln.width = 2.2
                ln.points = [x + s * 0.22, y + s * 0.5,
                             x + s * 0.42, y + s * 0.28,
                             x + s * 0.78, y + s * 0.74]
            else:
                ln.width = 1.6
                ln.rounded_rectangle = (x, y, s, s, 6)
        thumb.bind(pos=_draw_chk, size=_draw_chk)

        left = BoxLayout(orientation="vertical", size_hint_x=None,
                         width=dp(180), spacing=dp(5))
        left.add_widget(thumb)
        view = RoundedButton(text="ПРОСМОТР", bg=ACCENT2, fg=TEXT,
                             border=H("#cfe4ff"),
                             size_hint_y=None, height=dp(40), font_size="14sp")
        view.bind(on_release=lambda *a, e=entry: self.open_preview(e))
        left.add_widget(view)
        top.add_widget(left)

        # Функция мгновенного обновления вида выбора (без перестройки)
        def set_sel(sel, cd=card, bc=bcol, sc=sqcol, cc=chkcol,
                    st=chk_state, draw=_draw_chk):
            cd._col.rgba = CARD2 if sel else CARD
            bc.a = 1 if sel else 0
            sc.rgba = ACCENT if sel else (0, 0, 0, 0.45)
            cc.rgba = DARKTX if sel else (1, 1, 1, 0.9)
            st["sel"] = sel
            draw()
        self._card_updaters[index] = set_sel

        # Информация справа от фото (нормальной ширины)
        info = BoxLayout(orientation="vertical", spacing=dp(3))
        who = entry.get("recipient") or "—"
        method = entry.get("method", "")
        _d = entry.get("date", "")
        _time = _d.split()[-1] if _d else ""
        info.add_widget(body_label(_time, color=TEXT, size="15sp", h=dp(28)))
        info.add_widget(body_label("%s  \u2022  %s" % (method, who),
                                   color=ACCENT, size="14sp", h=dp(26)))
        geo_lb = body_label(self._geo_text(entry), color=MUTED,
                            size="13sp", h=dp(26))
        info.add_widget(geo_lb)
        info.add_widget(Label(size_hint_y=1))
        dele = RoundedButton(text="УДАЛИТЬ", bg=DANGER, fg=TEXT,
                             border=H("#ffd2d2"),
                             size_hint_y=None, height=dp(40), font_size="13sp")
        def _confirm_delete(i):
            from kivy.uix.popup import Popup as _P
            from kivy.uix.boxlayout import BoxLayout as _B
            from kivy.uix.label import Label as _L
            _c = _B(orientation="vertical", spacing=dp(12), padding=dp(16))
            _c.add_widget(_L(text="Удалить это фото?"))
            _r = _B(size_hint_y=None, height=dp(48), spacing=dp(12))
            _no = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER, font_size="14sp")
            _ok = RoundedButton(text="УДАЛИТЬ", bg=DANGER, fg=TEXT, font_size="14sp")
            _r.add_widget(_no); _r.add_widget(_ok); _c.add_widget(_r)
            _pp = _P(title="Удаление", content=_c, size_hint=(0.82, None), height=dp(180))
            _no.bind(on_release=lambda *a: _pp.dismiss())
            def _go(*a):
                _pp.dismiss(); self.delete_entry(i)
            _ok.bind(on_release=_go)
            _pp.open()
        dele.bind(on_release=lambda *a, i=index: _confirm_delete(i))
        info.add_widget(dele)
        top.add_widget(info)
        card.add_widget(top)

        if (entry.get("lat") is not None and entry.get("lon") is not None
                and not entry.get("address") and not entry.get("geo_checked")):
            self._fetch_address(entry, geo_lb)

        # Строка адреса: жёлтая рамка + кнопка правки справа
        caprow = BoxLayout(orientation="horizontal", size_hint_y=None,
                           height=cap_h, spacing=dp(8))
        capf = Card(bg=CARD2, border=H("#ffd166"), orientation="vertical",
                    padding=dp(2))
        capf.add_widget(body_label(split_address(entry.get("caption"))
                                   or "Адрес не указан",
                                   color=H("#ffd166"),
                                   size="12sp", h=dp(31), halign="center"))
        # Кнопки правки тут нет: адрес правится в ПРОСМОТР ->
        # РЕДАКТИРОВАТЬ. Строка занимает всю ширину и лучше читается.
        caprow.add_widget(capf)
        card.add_widget(caprow)

        # Строка комментария: рамка + кнопка правки справа
        comrow = BoxLayout(orientation="horizontal", size_hint_y=None,
                           height=com_h, spacing=dp(8))
        comf = Card(bg=CARD2, border=BORDER, orientation="vertical", padding=dp(2))
        _mt = meter_text(entry)
        _ct = entry.get("comment") or ""
        _line = (("%s   |   %s" % (_mt, _ct)) if (_mt and _ct)
                 else (_mt or _ct or "Комментарий не указан"))
        if _mt:
            if _mt.startswith("ХОЛОДНАЯ"):
                _col = H("#4da3ff")
            elif _mt.startswith("ГОРЯЧАЯ"):
                _col = H("#ff5c5c")
            else:
                _col = H("#ffd166")
        else:
            _col = TEXT if _ct else MUTED
        import re as _re
        _typ = (_mt.split()[0] if _mt else "")
        _m = _re.search(r"(\d[\d ]*)\s*,\s*(\d+)", _mt or "")
        _whole = ""; _frac = ""
        if _m:
            _whole = _m.group(1).replace(" ", ""); _frac = _m.group(2)
        else:
            _m2 = _re.search(r"(\d+)", _mt or "")
            if _m2:
                _whole = _m2.group(1)
        _unit = "кВт·ч" if ("кВт" in (_mt or "")) else ("м3" if _whole else "")
        from kivy.graphics import Color as _GC2, Line as _GL2
        import os as _os4, datetime as _dt4
        try:
            _fp4 = entry.get("file", "")
            if _fp4 and _os4.path.exists(_fp4):
                _dm4 = _dt4.datetime.fromtimestamp(_os4.path.getmtime(_fp4))
            else:
                _dm4 = _dt4.datetime.now()
            _mon_c = ["", "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"][_dm4.month]
        except Exception:
            _mon_c = ""
        def _mkcell(_dch, _fg):
            _lb = Label(text=_dch, color=_fg, font_size="11sp", bold=True, size_hint=(None, None), size=(dp(17), dp(16)), pos_hint={"center_y": 0.5})
            with _lb.canvas.before:
                _GC2(0.45, 0.45, 0.52, 1)
                _ln2 = _GL2(width=1.2)
            def _upd(_w, *_a):
                _ln2.rounded_rectangle = (_w.x + dp(1), _w.y + dp(1), _w.width - dp(2), _w.height - dp(2), dp(3))
            _lb.bind(pos=_upd, size=_upd)
            return _lb
        if _whole:
            _bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(17), spacing=dp(3))
            if _typ:
                _tl = Label(text=_typ, color=_col, font_size="12sp", bold=True, size_hint_x=None, width=dp(2))
                _tl.bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(4)))
                _bar.add_widget(_tl)
            _bar.add_widget(Label(size_hint_x=1))
            for _d in _whole:
                _bar.add_widget(_mkcell(_d, (0.95, 0.95, 0.98, 1)))
            if _frac:
                _bar.add_widget(Label(text=",", color=(0.95, 0.95, 0.98, 1), font_size="14sp", bold=True, size_hint_x=None, width=dp(6)))
                for _d in _frac:
                    _bar.add_widget(_mkcell(_d, (1.0, 0.36, 0.36, 1)))
            if _unit:
                _ul = Label(text=_unit, color=MUTED, font_size="9sp", size_hint_x=None, width=dp(2))
                _ul.bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(6)))
                _bar.add_widget(_ul)
            _bar.add_widget(Label(size_hint_x=1))
            comf.add_widget(_bar)
            _bar2 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(14), spacing=dp(3))
            if _mon_c:
                _ml = Label(text=_mon_c, color=(1.0, 0.82, 0.4, 1), font_size="11sp", bold=True, size_hint=(None, None), height=dp(14), pos_hint={"center_y": 0.5}, width=dp(2))
                _ml.bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(4)))
                _bar2.add_widget(_ml)
            else:
                _bar2.add_widget(Label(size_hint_x=None, width=dp(1)))
            _bar2.add_widget(Label(size_hint_x=1))
            if _ct:
                _bar2.add_widget(Label(text=_ct, color=MUTED, font_size="12sp", size_hint=(None, None), height=dp(14), pos_hint={"center_y": 0.5}, width=dp(2)))
                _bar2.children[0].bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(4)))
            _bar2.add_widget(Label(size_hint_x=1))
            comf.add_widget(_bar2)
        else:
            _bar3 = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(15), spacing=dp(3))
            _bar3.add_widget(Label(size_hint_x=1))
            if _mon_c:
                _ml3 = Label(text=_mon_c, color=(1.0, 0.82, 0.4, 1),
                             font_size="11sp", bold=True,
                             size_hint=(None, None), height=dp(15),
                             pos_hint={"center_y": 0.5}, width=dp(2))
                _ml3.bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(10)))
                _bar3.add_widget(_ml3)
            _cl3 = Label(text=(_ct or "Комментарий не указан"),
                         color=MUTED, font_size="11sp",
                         size_hint=(None, None), height=dp(15),
                         pos_hint={"center_y": 0.5}, width=dp(2))
            _cl3.bind(texture_size=lambda w, s: setattr(w, "width", s[0] + dp(4)))
            _bar3.add_widget(_cl3)
            _bar3.add_widget(Label(size_hint_x=1))
            comf.add_widget(_bar3)
        # Комментарий и показания правятся там же — в просмотре.
        comrow.add_widget(comf)
        card.add_widget(comrow)

        return card

    def _load_thumb_async(self, src, thumb):
        def work():
            tp = make_thumb(src)
            if tp:
                self._set_thumb(thumb, tp)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _set_thumb(self, thumb, tp):
        try:
            thumb.source = tp
            thumb.reload()
        except Exception:
            pass

    def _caption_text(self, entry):
        c = entry.get("caption")
        return ("Подпись: %s" % c) if c else "Без подписи"

    def open_preview(self, entry):
        """Просмотр фото: увеличивается двумя пальцами.
        Правка спрятана под кнопкой РЕДАКТИРОВАТЬ — обычно она не нужна."""
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(6))
        wait = body_label("", color=MUTED, size="14sp", h=0, halign="center")
        box.add_widget(wait)

        frame = ZoomFrame()
        img = frame.img
        box.add_widget(frame)

        def refresh():
            cap = entry.get("caption", "")
            com = entry.get("comment", "")
            mtx = meter_text(entry)
            src = entry.get("file", "")
            ready = stamped_ready(src, cap, com, mtx)
            if ready:
                wait.text = ""
                wait.height = 0
                img.source = ready
                img.reload()
            else:
                quick = cached_thumb_path(src) or (src if os.path.exists(src)
                                                   else "")
                if quick:
                    img.source = quick
                wait.text = "Готовлю фото..."
                wait.height = dp(30)
                self._prepare_stamped(src, cap, com, img, mtx)

        refresh()

        hint = body_label("Фото увеличивается двумя пальцами",
                          color=MUTED, size="11sp", h=dp(18), halign="center")
        box.add_widget(hint)

        erow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))

        def show_edit(on):
            erow.clear_widgets()
            if not on:
                eb = RoundedButton(text="РЕДАКТИРОВАТЬ", bg=BTN2, fg=TEXT,
                                   border=BORDER, font_size="13sp")
                eb.bind(on_release=lambda *a: show_edit(True))
                erow.add_widget(eb)
                return
            ea = RoundedButton(text="АДРЕС", bg=H("#ffd166"), fg=DARKTX,
                               font_size="12sp")
            ea.bind(on_release=lambda *a: self.edit_address_dialog(entry,
                                                                   refresh))
            ec = RoundedButton(text="КОММЕНТ.", bg=BTN2, fg=TEXT,
                               border=BORDER, font_size="12sp")
            ec.bind(on_release=lambda *a: self._edit_field(
                entry, "comment", "Изменить комментарий", "Комментарий",
                refresh))
            em = RoundedButton(text="ПОКАЗАНИЯ СЧЁТЧИКА", bg=BTN2,
                               fg=TEXT, border=BORDER,
                               font_size="10sp")
            em.bind(on_release=lambda *a: edit_meter_dialog(entry, refresh))
            erow.add_widget(ea)
            erow.add_widget(ec)
            erow.add_widget(em)

        show_edit(False)
        box.add_widget(erow)

        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             size_hint_y=None, height=dp(46), font_size="15sp")
        box.add_widget(back)

        p = Popup(title="", content=box, size_hint=(0.98, 0.94),
                  separator_height=0, background_color=(0.0, 0.0, 0.0, 1))
        back.bind(on_release=lambda *a: p.dismiss())
        p.open()

    def _prepare_stamped(self, src, cap, com, img, mtx=""):
        def work():
            path = stamped_image_path(src, cap, com, mtx)
            if path:
                self._set_thumb(img, path)
        threading.Thread(target=work, daemon=True).start()

    def edit_caption(self, entry):
        self._edit_field(entry, "caption", "Изменить адрес", "Адрес")

    def edit_comment(self, entry):
        self._edit_field(entry, "comment", "Изменить комментарий", "Комментарий")

    def edit_address_dialog(self, entry, on_done=None):
        st, ho, fl = parse_address(entry.get("caption", ""))
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        s_in = make_input("Улица"); s_in.text = st
        srow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        srow.add_widget(s_in)
        s_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER, size_hint_x=None, width=dp(72), font_size="11sp")
        s_clr.bind(on_release=lambda *a: setattr(s_in, "text", ""))
        srow.add_widget(s_clr)
        content.add_widget(srow)
        hk = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        h_in = make_num_input("Дом"); h_in.text = ho
        h_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER, size_hint_x=None, width=dp(64), font_size="10sp")
        h_clr.bind(on_release=lambda *a: setattr(h_in, "text", ""))
        f_in = make_num_input("Кв"); f_in.text = fl
        f_clr = RoundedButton(text="СТЕР", bg=BTN2, fg=TEXT, border=BORDER, size_hint_x=None, width=dp(64), font_size="10sp")
        f_clr.bind(on_release=lambda *a: setattr(f_in, "text", ""))
        hk.add_widget(h_in)
        hk.add_widget(h_clr)
        hk.add_widget(f_in)
        hk.add_widget(f_clr)
        content.add_widget(hk)

        pp = Popup(title="Изменить адрес", content=content,
                   size_hint=(0.94, None), height=dp(340),
                   pos_hint={"top": 0.98},
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            val = build_address(s_in.text, h_in.text, f_in.text)
            if val:
                entry["caption"] = val
            else:
                entry.pop("caption", None)
            app = App.get_running_app()
            app.remember_address(val)
            app.save()
            warm_entry(entry)
            pp.dismiss()
            if on_done:
                on_done()
            self.rebuild()

        row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="15sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel); row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        pp.open()

    def _edit_field(self, entry, key, title, hint, on_done=None):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14))
        ti = make_input(hint)
        ti.text = entry.get(key, "")
        content.add_widget(ti)

        pp = Popup(title=title, content=content,
                   size_hint=(0.92, None), height=dp(220),
                   pos_hint={"top": 0.98},
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        _skip7 = [False]

        def _apply7(*a):
            val = ti.text.strip()
            if val:
                entry[key] = val
            else:
                entry.pop(key, None)
            App.get_running_app().save()

        def save(*a):
            _apply7()
            _skip7[0] = True
            pp.dismiss()
            self.rebuild()

        def _cancel7(*a):
            _skip7[0] = True
            pp.dismiss()

        def _dism7(*a):
            if not _skip7[0]:
                _apply7()
                self.rebuild()
            return False

        pp.bind(on_dismiss=_dism7)
        ti.bind(on_text_validate=lambda *a: save())

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="15sp")
        cancel.bind(on_release=_cancel7)
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        pp.open()

    def toggle_select(self, index):
        if index in self.selected:
            self.selected.discard(index)
        else:
            self.selected.add(index)
        f = self._card_updaters.get(index)
        if f:
            f(index in self.selected)
        self._refresh_actions()

    def select_all(self):
        """Выделить только то, что показано на экране — то есть
        сегодняшние фото. Прошлые дни не трогаем: их тут не видно,
        а выделять вслепую опасно."""
        self.selected = set(self._card_updaters.keys())
        for f in self._card_updaters.values():
            f(True)
        self._refresh_actions()

    def clear_selection(self):
        self.selected = set()
        for f in self._card_updaters.values():
            f(False)
        self._refresh_actions()

    def send_selected(self):
        app = App.get_running_app()
        archive = app.data.get("archive", [])
        entries = []
        for i in sorted(self.selected):
            if 0 <= i < len(archive):
                e = archive[i]
                if e.get("file") and os.path.exists(e["file"]):
                    entries.append(e)
        if not entries:
            toast("Не выбрано ни одного фото.")
            return

        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(body_label("Как отправить выбранные (%d)?" % len(entries),
                                      color=TEXT, size="16sp", h=dp(44),
                                      halign="center"))
        pp = Popup(title="", content=content, size_hint=(0.9, None), height=dp(330),
                   separator_height=0, background_color=(0.05, 0.05, 0.07, 1))

        mms = RoundedButton(text="MMS  (на номер из списка)", bg=ACCENT2, fg=TEXT,
                            size_hint_y=None, height=dp(74), font_size="15sp")
        mms.bind(on_release=lambda *a: (pp.dismiss(), self._send_multi_mms(entries)))
        mx = RoundedButton(text="MAX / ПОДЕЛИТЬСЯ\n(адресата выбираете в MAX)",
                           bg=ACCENT, fg=DARKTX,
                           size_hint_y=None, height=dp(74), font_size="13sp")
        mx.bind(on_release=lambda *a: (pp.dismiss(), self._send_multi_max(entries)))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               size_hint_y=None, height=dp(58), font_size="14sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        content.add_widget(mms)
        content.add_widget(mx)
        content.add_widget(cancel)
        pp.open()

    def _send_multi_max(self, entries):
        toast("Готовлю отправку...")
        self.clear_selection()

        def work():
            paths = [stamped_image_path(e["file"], e.get("caption", ""),
                                        e.get("comment", ""), meter_text(e))
                     for e in entries]
            share_photos_multiple(paths)
        threading.Thread(target=work, daemon=True).start()

    def _send_multi_mms(self, entries):
        app = App.get_running_app()
        recips = app.data.get("recipients", [])
        if not recips:
            toast("Сначала добавьте адресата в Настройках.")
            return

        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        content.add_widget(body_label("Кому отправить (MMS)?", color=TEXT,
                                      size="16sp", h=dp(36), halign="center"))
        pp = Popup(title="", content=content, size_hint=(0.88, 0.8),
                   separator_height=0, background_color=(0.05, 0.05, 0.07, 1))

        scroll = ScrollView()
        col = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        for r in recips:
            b = RoundedButton(text=r["name"], bg=CARD2, fg=TEXT, border=BORDER,
                              size_hint_y=None, height=dp(66), font_size="17sp")
            b.bind(on_release=lambda *a, num=r["number"]:
                   self._do_multi_mms(pp, entries, num))
            col.add_widget(b)
        scroll.add_widget(col)
        content.add_widget(scroll)

        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               size_hint_y=None, height=dp(58), font_size="14sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        content.add_widget(cancel)
        pp.open()

    def _do_multi_mms(self, pp, entries, number):
        pp.dismiss()
        toast("Готовлю отправку...")
        self.clear_selection()

        def work():
            paths = [stamped_image_path(e["file"], e.get("caption", ""),
                                        e.get("comment", ""), meter_text(e))
                     for e in entries]
            send_mms_multiple(paths, number)
        threading.Thread(target=work, daemon=True).start()

    def delete_selected(self):
        n = len(self.selected)
        if n == 0:
            toast("Ничего не выбрано.")
            return
        confirm_delete("Удалить выбранные (%d)?" % n,
                       self._do_delete_selected)

    def _do_delete_selected(self):
        app = App.get_running_app()
        archive = app.data.get("archive", [])
        for i in sorted(self.selected, reverse=True):
            if 0 <= i < len(archive):
                entry = archive[i]
                try:
                    if entry.get("file") and os.path.exists(entry["file"]):
                        os.remove(entry["file"])
                except Exception as e:
                    print("Не удалось удалить файл:", e)
                del archive[i]
        app.save()
        self.selected = set()
        self.rebuild()

    def _geo_text(self, entry):
        if entry.get("address"):
            return entry["address"]
        if entry.get("lat") is not None and entry.get("lon") is not None:
            if entry.get("geo_checked"):
                return "%.5f, %.5f" % (entry["lat"], entry["lon"])
            return "Определяю адрес..."
        return "Без геометки"

    def _fetch_address(self, entry, label):
        lat = entry["lat"]; lon = entry["lon"]

        def worker():
            addr = reverse_geocode(lat, lon)
            self._apply_address(entry, label, addr)

        threading.Thread(target=worker, daemon=True).start()

    @mainthread
    def _apply_address(self, entry, label, addr):
        app = App.get_running_app()
        entry["geo_checked"] = True
        if addr:
            entry["address"] = addr
        app.save()
        try:
            label.text = self._geo_text(entry)
        except Exception:
            pass

    def delete_entry(self, index):
        confirm_delete("Удалить это фото?",
                       lambda: self._do_delete_entry(index))

    def _do_delete_entry(self, index):
        app = App.get_running_app()
        archive = app.data.get("archive", [])
        if index < 0 or index >= len(archive):
            return
        entry = archive[index]
        try:
            if entry.get("file") and os.path.exists(entry["file"]):
                os.remove(entry["file"])
        except Exception as e:
            print("Не удалось удалить файл:", e)
        del archive[index]
        app.save()
        self.selected = set()
        self.rebuild()

    def go_camera(self):
        self.manager.transition.direction = "right"
        self.manager.current = "camera"
        cam = self.manager.get_screen("camera")
        Clock.schedule_once(lambda dt: cam.launch(), 0.15)

    def go_home(self):
        self.manager.transition.direction = "right"
        self.manager.current = "camera"

    def go_gallery(self):
        self.manager.transition.direction = "left"
        self.manager.current = "gallery"

    def go_settings(self):
        self.manager.transition.direction = "left"
        self.manager.current = "settings"

# =====================================================================
# =====================================================================
#  ЭКРАН: ГАЛЕРЕЯ (даты -> сетка фото за день, как в галерее телефона)
# =====================================================================

class GalleryScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.day = None  # None = список дат, иначе выбранная дата
        self.selected = []   # выбранные записи для отправки
        self.root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        self.add_widget(self.root)

    def on_enter(self, *a):
        self.day = None
        self.selected = []
        self.rebuild()

    def rebuild(self):
        app = App.get_running_app()
        self.root.clear_widgets()
        archive = app.data.get("archive", [])

        if not archive:
            self.root.add_widget(self._head("ГАЛЕРЕЯ"))
            self.root.add_widget(body_label("Архив пуст.", color=MUTED,
                                            size="15sp", h=dp(40),
                                            halign="center"))
            self.root.add_widget(Label(size_hint_y=1))
            return

        if self.day is None:
            self._build_days(archive)
        else:
            self._build_photos(archive)

    def _head(self, title):
        """Одна ровная шапка: НАЗАД — заголовок — АРХИВ.
        НАЗАД сам понимает, куда идти: из дня — к датам, с дат — в архив."""
        head = BoxLayout(orientation="vertical", size_hint_y=None,
                         height=dp(46) * 2 + dp(6), spacing=dp(6))

        _r1 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        arch = RoundedButton(text="АРХИВ", bg=ACCENT2, fg=TEXT,
                             border=H("#ffd166"), font_size="14sp")
        arch.bind(on_release=lambda *a: self.go_archive())
        _r1.add_widget(arch)
        _r1.add_widget(Label(size_hint_x=None, width=dp(56)))
        head.add_widget(_r1)

        _r2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT,
                             border=H("#e6e0ff"), font_size="13sp")
        back.bind(on_release=lambda *a: self.go_back())
        _tbox = Card(bg=CARD2, border=ACCENT, orientation="vertical",
                     padding=dp(2))
        _tbox.add_widget(title_label(title, color=ACCENT, size="16sp"))
        _r2.add_widget(back)
        _r2.add_widget(_tbox)
        _r2.add_widget(Label(size_hint_x=None, width=dp(56)))
        head.add_widget(_r2)
        return head

    def _build_days(self, archive):
        self.root.add_widget(self._head("ГАЛЕРЕЯ"))

        # Собираем даты (новые сверху) и считаем фото
        days = []
        counts = {}
        for e in archive:
            d = (e.get("date", "")[:10]) or "—"
            if d not in counts:
                counts[d] = 0
                days.append(d)
            counts[d] += 1
        days.sort(reverse=True)

        today = datetime.now().strftime("%d.%m.%Y")
        scroll = ScrollView()
        col = GridLayout(cols=1, spacing=dp(10), size_hint_y=None,
                         padding=[0, dp(4)])
        col.bind(minimum_height=col.setter("height"))
        for d in days:
            label = ("СЕГОДНЯ  (%d)" % counts[d]) if d == today \
                else ("%s  (%d)" % (d, counts[d]))
            b = RoundedButton(text=label, bg=CARD2, fg=TEXT, border=BORDER,
                              size_hint_y=None, height=dp(58), font_size="16sp")
            b.bind(on_release=lambda *a, dd=d: self.open_day(dd))
            col.add_widget(b)
        scroll.add_widget(col)
        self.root.add_widget(scroll)

    def _build_photos(self, archive):
        today = datetime.now().strftime("%d.%m.%Y")
        title = "СЕГОДНЯ" if self.day == today else self.day
        self.root.add_widget(self._head(title))

        items = [e for e in archive if (e.get("date", "")[:10]) == self.day]
        items.reverse()

        # Один ряд действий вместо трёх рядов кнопок.
        # Ничего не выбрано -> одна кнопка «ВЫБРАТЬ ВСЁ».
        # Что-то выбрано -> СНЯТЬ / ОТПРАВИТЬ / УДАЛИТЬ.
        act = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        if self.selected:
            n = len(self.selected)
            clr = RoundedButton(text="СНЯТЬ (%d)" % n, bg=BTN2, fg=TEXT,
                                border=BORDER, font_size="12sp")
            clr.bind(on_release=lambda *a: self.clear_sel_gal())
            snd = RoundedButton(text="ОТПРАВИТЬ (%d)" % n, bg=ACCENT, fg=DARKTX,
                                font_size="13sp")
            snd.bind(on_release=lambda *a: self.send_sel_gal())
            dl = RoundedButton(text="УДАЛИТЬ (%d)" % n, bg=DANGER, fg=TEXT,
                               font_size="13sp")
            dl.bind(on_release=lambda *a: self.delete_sel_gal())
            act.add_widget(clr)
            act.add_widget(snd)
            act.add_widget(dl)
        else:
            sa = RoundedButton(text="ВЫБРАТЬ ВСЁ", bg=BTN2, fg=TEXT,
                               border=BORDER, font_size="14sp")
            sa.bind(on_release=lambda *a, it=items: self.select_all_gal(it))
            act.add_widget(sa)
        self.root.add_widget(act)

        scroll = ScrollView()
        grid = GridLayout(cols=3, spacing=dp(6), size_hint_y=None,
                          padding=[0, dp(4)])
        grid.bind(minimum_height=grid.setter("height"))
        for e in items:
            cell = BoxLayout(orientation="vertical", size_hint_y=None,
                             height=dp(180), spacing=dp(2))
            cell.add_widget(body_label(e.get("caption") or "",
                                       color=H("#ffd166"),
                                       size="10sp", h=dp(24), halign="center"))

            wrap = FloatLayout()
            im = ImageButton(allow_stretch=True, keep_ratio=True,
                             size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            tp = cached_thumb_path(e.get("file"))
            if tp:
                im.source = tp
            elif e.get("file") and os.path.exists(e["file"]):
                self._load_thumb_async(e["file"], im)
            im.bind(on_release=lambda *a, ee=e: self.open_photo(ee))
            wrap.add_widget(im)

            sel = e in self.selected
            chk = RoundedButton(
                text=("\u2713" if sel else ""),
                bg=(ACCENT if sel else (0, 0, 0, 0.55)),
                fg=DARKTX,
                border=(None if sel else (1, 1, 1, 0.9)),
                radius=6, size_hint=(None, None), size=(dp(30), dp(30)),
                pos_hint={"x": 0.03, "top": 0.97}, font_size="16sp")
            chk.bind(on_release=lambda *a, ee=e: self.toggle_sel_gal(ee))
            wrap.add_widget(chk)
            cell.add_widget(wrap)

            cell.add_widget(body_label(e.get("comment") or "", color=TEXT,
                                       size="10sp", h=dp(22), halign="center"))
            grid.add_widget(cell)
        scroll.add_widget(grid)
        self.root.add_widget(scroll)
        if not getattr(self, "_warmed", None) == self.day:
            self._warmed = self.day
            self._preheat(items)

    def _preheat(self, items):
        """Заранее готовим фото с плашкой — просмотр открывается сразу."""
        def work():
            n = 0
            for e in items:
                try:
                    src = e.get("file", "")
                    if not src or not os.path.exists(src):
                        continue
                    cap = e.get("caption", "")
                    com = e.get("comment", "")
                    if not cap and not com:
                        continue
                    mtx = meter_text(e)
                    if stamped_ready(src, cap, com, mtx):
                        continue
                    stamped_image_path(src, cap, com, mtx)
                    n += 1
                    # Готовим понемногу и с паузой, иначе телефон
                    # не успевает и Android ругается «не отвечает».
                    time.sleep(0.4)
                    if n >= 4:
                        break
                except Exception as ex:
                    print("preheat:", ex)
        threading.Thread(target=work, daemon=True).start()

    # --- выделение и отправка из галереи ---
    def toggle_sel_gal(self, entry):
        if entry in self.selected:
            self.selected.remove(entry)
        else:
            self.selected.append(entry)
        self.rebuild()

    def select_all_gal(self, items):
        self.selected = list(items)
        self.rebuild()

    def clear_sel_gal(self):
        self.selected = []
        self.rebuild()

    def send_sel_gal(self):
        if not self.selected:
            toast("Ничего не выбрано.")
            return
        entries = list(self.selected)
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        content.add_widget(body_label("Как отправить (%d)?" % len(entries),
                                      color=TEXT, size="16sp", h=dp(40),
                                      halign="center"))
        pp = Popup(title="", content=content, size_hint=(0.9, None), height=dp(330),
                   separator_height=0, background_color=(0.05, 0.05, 0.07, 1))
        mms = RoundedButton(text="MMS  (на номер из списка)", bg=ACCENT2, fg=TEXT,
                            size_hint_y=None, height=dp(70), font_size="14sp")
        mms.bind(on_release=lambda *a: (pp.dismiss(), self._gal_mms(entries)))
        mx = RoundedButton(text="MAX / ПОДЕЛИТЬСЯ", bg=ACCENT, fg=DARKTX,
                           size_hint_y=None, height=dp(70), font_size="14sp")
        mx.bind(on_release=lambda *a: (pp.dismiss(), self._gal_max(entries)))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               size_hint_y=None, height=dp(52), font_size="13sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        content.add_widget(mms)
        content.add_widget(mx)
        content.add_widget(cancel)
        pp.open()

    def delete_sel_gal(self):
        n = len(self.selected)
        if not n:
            toast("Ничего не выбрано.")
            return
        confirm_delete("Удалить выбранные (%d)?" % n, self._do_delete_sel_gal)

    def _do_delete_sel_gal(self):
        app = App.get_running_app()
        archive = app.data.get("archive", [])
        for e in list(self.selected):
            try:
                f = e.get("file")
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception as ex:
                print("del:", ex)
            if e in archive:
                archive.remove(e)
        app.save()
        self.selected = []
        self.rebuild()

    def _gal_max(self, entries):
        toast("Готовлю отправку...")
        self.clear_sel_gal()

        def work():
            paths = [stamped_image_path(e.get("file", ""), e.get("caption", ""),
                                        e.get("comment", ""), meter_text(e))
                     for e in entries]
            share_photos_multiple(paths)
        threading.Thread(target=work, daemon=True).start()

    def _gal_mms(self, entries):
        app = App.get_running_app()
        recips = app.data.get("recipients", [])
        if not recips:
            toast("Сначала добавьте адресата в Настройках.")
            return
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        content.add_widget(body_label("Кому отправить (MMS)?", color=TEXT,
                                      size="16sp", h=dp(36), halign="center"))
        pp = Popup(title="", content=content, size_hint=(0.88, 0.8),
                   separator_height=0, background_color=(0.05, 0.05, 0.07, 1))
        scroll = ScrollView()
        col = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        for r in recips:
            b = RoundedButton(text=r["name"], bg=CARD2, fg=TEXT, border=BORDER,
                              size_hint_y=None, height=dp(60), font_size="16sp")
            b.bind(on_release=lambda *a, num=r["number"]:
                   self._gal_do_mms(pp, entries, num))
            col.add_widget(b)
        scroll.add_widget(col)
        content.add_widget(scroll)
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               size_hint_y=None, height=dp(52), font_size="13sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        content.add_widget(cancel)
        pp.open()

    def _gal_do_mms(self, pp, entries, number):
        pp.dismiss()
        toast("Готовлю отправку...")
        self.clear_sel_gal()

        def work():
            paths = [stamped_image_path(e.get("file", ""), e.get("caption", ""),
                                        e.get("comment", ""), meter_text(e))
                     for e in entries]
            send_mms_multiple(paths, number)
        threading.Thread(target=work, daemon=True).start()

    def _load_thumb_async(self, src, thumb):
        def work():
            tp = make_thumb(src)
            if tp:
                self._set_thumb(thumb, tp)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _set_thumb(self, thumb, tp):
        try:
            thumb.source = tp
            thumb.reload()
        except Exception:
            pass

    def open_day(self, day):
        self.day = day
        self._warmed = None
        self.selected = []
        self.rebuild()

    def back_to_days(self):
        self.day = None
        self._warmed = None
        self.selected = []
        self.rebuild()

    def open_photo(self, entry):
        """Просмотр фото: увеличивается двумя пальцами.
        Правка спрятана под кнопкой РЕДАКТИРОВАТЬ."""
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(6))

        frame = ZoomFrame()
        img = frame.img
        box.add_widget(frame)

        def refresh_img():
            cap = entry.get("caption", "")
            com = entry.get("comment", "")
            mtx = meter_text(entry)
            src = entry.get("file", "")
            ready = stamped_ready(src, cap, com, mtx)
            if ready:
                img.source = ready
                img.reload()
            else:
                quick = cached_thumb_path(src) or (src if os.path.exists(src)
                                                   else None)
                if quick:
                    img.source = quick
                self._prepare_stamped(src, cap, com, img, mtx)

        refresh_img()

        hint = body_label("Фото увеличивается двумя пальцами",
                          color=MUTED, size="11sp", h=dp(18), halign="center")
        box.add_widget(hint)

        erow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))

        def show_edit(on):
            erow.clear_widgets()
            if not on:
                eb = RoundedButton(text="РЕДАКТИРОВАТЬ", bg=BTN2, fg=TEXT,
                                   border=BORDER, font_size="13sp")
                eb.bind(on_release=lambda *a: show_edit(True))
                erow.add_widget(eb)
                return
            ea = RoundedButton(text="АДРЕС", bg=H("#ffd166"), fg=DARKTX,
                               font_size="12sp")
            ea.bind(on_release=lambda *a: self.edit_address_gal(entry,
                                                                refresh_img))
            ec = RoundedButton(text="КОММЕНТ.", bg=BTN2, fg=TEXT,
                               border=BORDER, font_size="12sp")
            ec.bind(on_release=lambda *a: self.edit_field(
                entry, "comment", "Изменить комментарий", "Комментарий",
                refresh_img))
            em = RoundedButton(text="ПОКАЗАНИЯ СЧЁТЧИКА", bg=BTN2,
                               fg=TEXT, border=BORDER,
                               font_size="10sp")
            em.bind(on_release=lambda *a: edit_meter_dialog(entry, refresh_img))
            erow.add_widget(ea)
            erow.add_widget(ec)
            erow.add_widget(em)

        show_edit(False)
        box.add_widget(erow)

        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             size_hint_y=None, height=dp(46), font_size="15sp")
        box.add_widget(back)
        p = Popup(title="", content=box, size_hint=(0.98, 0.94),
                  separator_height=0, background_color=(0, 0, 0, 1))
        back.bind(on_release=lambda *a: p.dismiss())
        p.open()

    def edit_address_gal(self, entry, on_done=None):
        st, ho, fl = parse_address(entry.get("caption", ""))
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        s_in = make_input("Улица"); s_in.text = st
        content.add_widget(s_in)
        row0 = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))
        h_in = make_num_input("Дом"); h_in.text = ho
        f_in = make_num_input("Кв"); f_in.text = fl
        row0.add_widget(h_in); row0.add_widget(f_in)
        content.add_widget(row0)

        pp = Popup(title="Изменить адрес", content=content,
                   size_hint=(0.94, None), height=dp(280),
                   pos_hint={"top": 0.98},
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            val = build_address(s_in.text, h_in.text, f_in.text)
            if val:
                entry["caption"] = val
            else:
                entry.pop("caption", None)
            app = App.get_running_app()
            app.remember_address(val)
            app.save()
            warm_entry(entry)
            pp.dismiss()
            if on_done:
                on_done()
            self.rebuild()

        row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="15sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel); row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        pp.open()

    def edit_field(self, entry, key, title, hint, on_done=None):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14))
        ti = make_input(hint)
        ti.text = entry.get(key, "")
        content.add_widget(ti)

        pp = Popup(title=title, content=content,
                   size_hint=(0.92, None), height=dp(220),
                   pos_hint={"top": 0.98},
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        _skip7 = [False]

        def _apply7(*a):
            val = ti.text.strip()
            if val:
                entry[key] = val
            else:
                entry.pop(key, None)
            App.get_running_app().save()
            warm_entry(entry)

        def save(*a):
            _apply7()
            _skip7[0] = True
            pp.dismiss()
            if on_done:
                on_done()
            self.rebuild()

        def _cancel7(*a):
            _skip7[0] = True
            pp.dismiss()

        def _dism7(*a):
            if not _skip7[0]:
                _apply7()
                if on_done:
                    on_done()
                self.rebuild()
            return False

        pp.bind(on_dismiss=_dism7)
        ti.bind(on_text_validate=lambda *a: save())

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="15sp")
        cancel.bind(on_release=_cancel7)
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        pp.open()

    def _prepare_stamped(self, src, cap, com, img, mtx=""):
        def work():
            path = stamped_image_path(src, cap, com, mtx)
            if path:
                self._set_thumb(img, path)
        threading.Thread(target=work, daemon=True).start()

    def go_archive(self):
        self.manager.transition.direction = "right"
        self.manager.current = "archive"

    def go_back(self):
        if self.day is not None:
            self.back_to_days()
        else:
            self.manager.transition.direction = "right"
            self.manager.current = "archive"


# =====================================================================
#  ЭКРАН 6: НАСТРОЙКИ (режим MMS + управление адресатами)
# =====================================================================

class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        self.add_widget(self.root)

    def on_enter(self, *a):
        self.rebuild()

    def rebuild(self):
        app = App.get_running_app()
        self.root.clear_widgets()
        self.root.add_widget(title_label("НАСТРОЙКИ", color=ACCENT, size="20sp"))

        # Адрес по умолчанию — подставляется в каждое новое фото
        self.root.add_widget(body_label("Адрес по умолчанию (для новых фото):",
                                        color=TEXT, size="14sp", h=dp(28)))
        adrow = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        adr = Card(bg=CARD2, border=H("#ffd166"), orientation="vertical",
                   padding=dp(8))
        adr.add_widget(body_label(app.data.get("default_address")
                                  or "Не задан",
                                  color=H("#ffd166"), size="15sp",
                                  h=dp(30), halign="center"))
        adrow.add_widget(adr)
        ab = RoundedButton(text="ИЗМ.", bg=H("#ffd166"), fg=DARKTX,
                           size_hint_x=None, width=dp(62), font_size="12sp")
        ab.bind(on_release=lambda *a: self.edit_default_address())
        adrow.add_widget(ab)
        self.root.add_widget(adrow)

        self.root.add_widget(body_label("Показ адресатов MMS:",
                                        color=TEXT, size="15sp", h=dp(30)))

        mode = app.data.get("settings", {}).get("mms_mode", "list")
        row = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(10))
        b_list = RoundedButton(
            text="СПИСОК ИМЁН",
            bg=ACCENT if mode == "list" else CARD,
            fg=DARKTX if mode == "list" else TEXT, border=BORDER, font_size="14sp")
        b_list.bind(on_release=lambda *a: self.set_mode("list"))
        b_last = RoundedButton(
            text="ПОСЛЕДНИЙ + ПЛЮС",
            bg=ACCENT if mode == "last" else CARD,
            fg=DARKTX if mode == "last" else TEXT, border=BORDER, font_size="14sp")
        b_last.bind(on_release=lambda *a: self.set_mode("last"))
        row.add_widget(b_list)
        row.add_widget(b_last)
        self.root.add_widget(row)

        self.root.add_widget(body_label("Адресаты для MMS (для MAX не нужны):",
                                        color=TEXT,
                                        size="15sp", h=dp(30)))

        scroll = ScrollView()
        col = GridLayout(cols=1, spacing=dp(10), size_hint_y=None, padding=[0, dp(4)])
        col.bind(minimum_height=col.setter("height"))

        recips = app.data.get("recipients", [])
        if not recips:
            col.add_widget(body_label("Список пуст.", color=MUTED,
                                      size="14sp", h=dp(36)))
        else:
            for i, r in enumerate(recips):
                line = Card(bg=CARD, orientation="horizontal", size_hint_y=None,
                            height=dp(64), padding=dp(10), spacing=dp(8))
                line.add_widget(body_label("%s  %s" % (r["name"], r["number"]),
                                           color=TEXT, size="14sp", h=dp(44)))
                ed = RoundedButton(text="ИЗМ.", bg=BTN2, fg=TEXT, border=BORDER,
                                   size_hint_x=None, width=dp(66), font_size="13sp")
                ed.bind(on_release=lambda *a, idx=i: self.edit_recipient(idx))
                line.add_widget(ed)
                d = RoundedButton(text="X", bg=DANGER, fg=TEXT,
                                  size_hint_x=None, width=dp(56), font_size="15sp")
                d.bind(on_release=lambda *a, idx=i: self.del_recipient(idx))
                line.add_widget(d)
                col.add_widget(line)

        scroll.add_widget(col)
        self.root.add_widget(scroll)

        add = RoundedButton(text="+  ДОБАВИТЬ АДРЕСАТА", bg=ACCENT2, fg=TEXT,
                            size_hint_y=None, height=dp(64), font_size="15sp")
        add.bind(on_release=lambda *a: self.add_recipient())
        self.root.add_widget(add)

        back = RoundedButton(text="НАЗАД", bg=BACKC, fg=TEXT, border=None,
                             size_hint_y=None, height=dp(64), font_size="15sp")
        back.bind(on_release=lambda *a: self.go_back())
        self.root.add_widget(back)

    def edit_default_address(self):
        """Адрес по умолчанию: улица, дом и квартира — отдельными полями."""
        app = App.get_running_app()
        st, ho, fl = parse_address(app.data.get("default_address", ""))

        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            padding=dp(14))
        content.add_widget(body_label("Улица:", color=MUTED, size="13sp",
                                      h=dp(22)))
        s_in = make_input("Улица")
        s_in.text = st
        content.add_widget(s_in)

        content.add_widget(body_label("Дом и квартира:", color=MUTED,
                                      size="13sp", h=dp(22)))
        row0 = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        h_in = make_num_input("Дом")
        h_in.text = ho
        f_in = make_num_input("Кв")
        f_in.text = fl
        row0.add_widget(h_in)
        row0.add_widget(f_in)
        content.add_widget(row0)

        pp = Popup(title="Адрес по умолчанию", content=content,
                   size_hint=(0.94, None), height=dp(320),
                   pos_hint={"top": 0.98},
                   title_color=TEXT, separator_color=ACCENT,
                   background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            app.data["default_address"] = build_address(
                s_in.text, h_in.text, f_in.text)
            app.save()
            pp.dismiss()
            self.rebuild()

        row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER,
                               font_size="15sp")
        cancel.bind(on_release=lambda *a: pp.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX,
                           font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        pp.open()

    def set_mode(self, mode):
        app = App.get_running_app()
        app.data.setdefault("settings", {})["mms_mode"] = mode
        app.save()
        self.rebuild()

    def del_recipient(self, index):
        app = App.get_running_app()
        recips = app.data.get("recipients", [])
        if 0 <= index < len(recips):
            del recips[index]
            if app.data.get("last_recipient", 0) >= len(recips):
                app.data["last_recipient"] = 0
            app.save()
            self.rebuild()

    def edit_recipient(self, index):
        app = App.get_running_app()
        recips = app.data.get("recipients", [])
        if not (0 <= index < len(recips)):
            return
        r = recips[index]
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14))
        name_in = make_input("Имя")
        name_in.text = r.get("name", "")
        num_in = make_input("Номер (+7...)")
        num_in.text = r.get("number", "")
        content.add_widget(name_in)
        content.add_widget(num_in)

        popup = Popup(title="Изменить адресата", content=content,
                      size_hint=(0.9, None), height=dp(300),
                      pos_hint={"top": 0.98},
                      title_color=TEXT, separator_color=ACCENT,
                      background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            name = name_in.text.strip()
            num = num_in.text.strip()
            if not name or not num:
                return
            recips[index] = {"name": name, "number": num}
            app.save()
            popup.dismiss()
            self.rebuild()

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER, font_size="15sp")
        cancel.bind(on_release=lambda *a: popup.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        popup.open()

    def add_recipient(self):
        app = App.get_running_app()
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14))
        name_in = make_input("Имя")
        num_in = make_input("Номер (+7...)")
        content.add_widget(name_in)
        content.add_widget(num_in)

        popup = Popup(title="Новый адресат", content=content,
                      size_hint=(0.9, None), height=dp(300),
                      pos_hint={"top": 0.98},
                      title_color=TEXT, separator_color=ACCENT,
                      background_color=(0.05, 0.05, 0.07, 1))

        def save(*a):
            name = name_in.text.strip()
            num = num_in.text.strip()
            if not name or not num:
                return
            app.data["recipients"].append({"name": name, "number": num})
            app.save()
            popup.dismiss()
            self.rebuild()

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12))
        cancel = RoundedButton(text="ОТМЕНА", bg=BTN2, fg=TEXT, border=BORDER, font_size="15sp")
        cancel.bind(on_release=lambda *a: popup.dismiss())
        ok = RoundedButton(text="СОХРАНИТЬ", bg=ACCENT, fg=DARKTX, font_size="15sp")
        ok.bind(on_release=save)
        row.add_widget(cancel)
        row.add_widget(ok)
        content.add_widget(row, index=len(content.children))  # кнопки над полем: иначе их закроет клавиатура
        popup.open()

    def go_back(self):
        self.manager.transition.direction = "right"
        self.manager.current = "archive"

# =====================================================================
#  ПРИЛОЖЕНИЕ
# =====================================================================

class PhotoSenderApp(App):
    def build(self):
        self.title = "Фото-отправщик"
        from kivy.core.window import Window as _Win
        from kivy.uix.button import Button as _Btn
        from kivy.uix.popup import Popup as _Pop
        from kivy.uix.boxlayout import BoxLayout as _Box
        from kivy.uix.label import Label as _Lab
        from kivy.graphics import Color as _EC, Line as _EL
        self._exit_btn = _Btn(background_normal="", background_down="", background_color=(0.16, 0.16, 0.2, 0.72), size_hint=(None, None), size=(dp(40), dp(40)))
        def _place_exit(*_a):
            self._exit_btn.pos = (_Win.width - dp(48), _Win.height - dp(55))
        def _draw_x(*_a):
            _b = self._exit_btn
            _b.canvas.after.clear()
            _cx = _b.center_x; _cy = _b.center_y; _s = dp(8)
            with _b.canvas.after:
                _EC(1, 1, 1, 0.30)
                _EL(rounded_rectangle=(_b.x + 1, _b.y + 1,
                                       _b.width - 2, _b.height - 2, dp(10)),
                    width=1.2)
                _EC(1, 1, 1, 0.85)
                _EL(points=[_cx - _s, _cy - _s, _cx + _s, _cy + _s], width=2.0)
                _EL(points=[_cx - _s, _cy + _s, _cx + _s, _cy - _s], width=2.0)
        def _ask_exit(*_a):
            _c = _Box(orientation="vertical", spacing=dp(12), padding=dp(16))
            _c.add_widget(_Lab(text="Выйти из приложения?"))
            _r = _Box(size_hint_y=None, height=dp(48), spacing=dp(12))
            _no = _Btn(text="ОТМЕНА"); _yes = _Btn(text="ВЫЙТИ")
            _r.add_widget(_no); _r.add_widget(_yes); _c.add_widget(_r)
            _pp = _Pop(title="Выход", content=_c, size_hint=(0.82, None), height=dp(180))
            _no.bind(on_release=lambda *a: _pp.dismiss())
            _yes.bind(on_release=lambda *a: self.stop())
            _pp.open()
        self._exit_btn.bind(on_release=_ask_exit, pos=_draw_x, size=_draw_x)
        _Win.bind(size=_place_exit)
        _place_exit()
        from kivy.clock import Clock as _Clk46
        _Clk46.schedule_once(lambda *a: (_Win.add_widget(self._exit_btn), _place_exit(), _draw_x()), 0)
        def _raise_exit(*_a):
            try:
                if self._exit_btn.parent is _Win:
                    _Win.remove_widget(self._exit_btn)
                _Win.add_widget(self._exit_btn)
                _place_exit(); _draw_x()
            except Exception:
                pass
        _Clk46.schedule_interval(_raise_exit, 0.5)
        Window.clearcolor = BG
        try:
            # «resize»: экран ужимается под клавиатуру, и кнопки внизу
            # остаются на виду. При «below_target» они прятались.
            Window.softinput_mode = "resize"
        except Exception:
            pass

        self.data = load_data()
        self.current_photo = None
        self.current_caption = ""
        self.current_comment = ""
        self.current_meter = ""
        self.current_meter_type = ""
        self._cam = None
        self._cam_ev = None

        Window.bind(on_keyboard=self._on_key)

        sm = ScreenManager(transition=SlideTransition(duration=0.18))
        sm.add_widget(CameraScreen(name="camera"))
        sm.add_widget(ReviewScreen(name="review"))
        sm.add_widget(SendMethodScreen(name="method"))
        sm.add_widget(MMSScreen(name="mms"))
        sm.add_widget(ArchiveScreen(name="archive"))
        sm.add_widget(GalleryScreen(name="gallery"))
        sm.add_widget(SettingsScreen(name="settings"))
        self.sm = sm
        return sm

    def save(self):
        save_data(self.data)

    # --- Кнопка «назад» телефона: ходим внутри приложения, не выходим ---
    def _on_key(self, window, key, *largs):
        if key != 27:  # 27 = кнопка «назад» / Esc
            return False
        cur = self.sm.current
        if cur == "review":
            try:
                if self.current_photo and os.path.exists(self.current_photo):
                    os.remove(self.current_photo)
            except Exception:
                pass
            self.current_photo = None
            self.sm.transition.direction = "right"
            self.sm.current = "camera"
            return True
        if cur == "method":
            self.sm.transition.direction = "right"
            self.sm.current = "review"
            return True
        if cur == "mms":
            self.sm.transition.direction = "right"
            self.sm.current = "method"
            return True
        if cur == "settings":
            self.sm.transition.direction = "right"
            self.sm.current = "archive"
            return True
        if cur == "gallery":
            scr = self.sm.get_screen("gallery")
            if getattr(scr, "selected", None):
                scr.clear_sel_gal()
                return True
            scr.go_back()
            return True
        if cur == "archive":
            scr = self.sm.get_screen("archive")
            if getattr(scr, "selected", None):
                scr.clear_selection()
                return True
            self.sm.transition.direction = "right"
            self.sm.current = "camera"
            return True
        # На главной — разрешаем стандартное поведение (выход)
        return False

    # --- Управление съёмкой (запуск + ожидание результата) ---
    def launch_camera(self, dest_path, on_done, status_cb):
        self._cam = None
        launch_native_camera(self, dest_path, on_done, status_cb)
        if getattr(self, "_cam", None):
            if self._cam_ev is not None:
                self._cam_ev.cancel()
            # Опрос на случай, если on_resume не сработает в Pydroid
            self._cam_ev = Clock.schedule_interval(self._poll_camera, 1.0)

    def _poll_camera(self, dt):
        cam = getattr(self, "_cam", None)
        if not cam:
            return False
        cam["tries"] += 1
        try:
            ok = finish_native_camera(cam["activity"], cam["uri"], cam["dest"])
        except Exception as e:
            print("poll err:", e)
            ok = False
        if ok:
            cb = cam["cb"]
            self._cam = None
            cb(cam["dest"])
            return False
        if cam["tries"] > 180:   # ~3 минуты ожидания — прекращаем
            self._cam = None
            return False
        return True

    def on_resume(self):
        # Камера вернула управление — сразу проверяем результат
        self._poll_camera(0)
        return True

    def on_pause(self):
        return True

    def remember_address(self, addr):
        """Ничего не запоминает — и это осознанно.
        Адрес по умолчанию задаётся только в НАСТРОЙКАХ и живёт там.
        Правка адреса у конкретного фото разовая: меняет только это
        фото, настройки остаются как были."""
        return

    def add_to_archive(self, method, recipient):
        """Добавить текущее фото в архив (с попыткой прочитать геометку)."""
        if not self.current_photo:
            return
        entry = {
            "file": self.current_photo,
            "date": datetime.now().strftime("%d.%m.%Y  %H:%M"),
            "recipient": recipient,
            "method": method,
        }
        cap = getattr(self, "current_caption", "") or ""
        if cap:
            entry["caption"] = cap
        com = getattr(self, "current_comment", "") or ""
        if com:
            entry["comment"] = com
        mt = getattr(self, "current_meter", "") or ""
        mtp = getattr(self, "current_meter_type", "") or ""
        if mt:
            entry["meter"] = mt
        if mtp:
            entry["meter_type"] = mtp
        gps = read_gps(self.current_photo)
        if gps:
            entry["lat"] = gps[0]
            entry["lon"] = gps[1]
        self.data["archive"].append(entry)
        self.current_caption = ""
        self.current_comment = ""
        self.current_meter = ""
        self.save()
        # Заранее готовим фото с плашкой и миниатюру — просмотр не будет ждать
        f = entry.get("file")
        c1 = entry.get("caption", "")
        c2 = entry.get("comment", "")
        c3 = meter_text(entry)

        def _warm():
            try:
                make_thumb(f)
                stamped_image_path(f, c1, c2, c3)
            except Exception as ex:
                print("warm:", ex)
        threading.Thread(target=_warm, daemon=True).start()


if __name__ == "__main__":
    PhotoSenderApp().run()

# =====================================================================
#  ЗАМЕТКИ ДЛЯ ДОРАБОТКИ (когда будем делать APK):
#   1) КАМЕРА: вызывается напрямую через jnius + MediaStore (штатная
#      камера). plyer НЕ нужен. Фото сохраняется в наш архив, а временная
#      запись в галерее удаляется. Если камера не открылась — текст ошибки
#      покажется прямо на экране (пришли скриншот, поправлю точечно).
#   2) РАЗРЕШЕНИЯ: на устройстве нужны разрешения на камеру и
#      хранилище/фото. В Pydroid они обычно уже есть; в APK их нужно
#      будет запрашивать (android.permission.CAMERA и др.).
#   3) ПОДЕЛИТЬСЯ / MMS: на Android 7+ вместо Uri.fromFile обычно
#      требуется FileProvider (иначе может быть ошибка доступа к файлу).
#      Для APK это добавим. В Pydroid чаще работает и так.
#   4) ГЕО-АДРЕС: чтение GPS требует Pillow (PIL). Адрес по координатам
#      требует интернета (Nominatim/OpenStreetMap). Нет — просто
#      показываются координаты или «Без геометки».
#   5) Всё в блоках Android/гео обёрнуто в try/except — при отсутствии
#      любой из возможностей приложение не падает.
# =====================================================================
