# -*- coding: utf-8 -*-
"""
종목 퀵뷰 - 올인원 버전

한 번 실행하면:
  1. 빨간 테두리 박스가 화면에 뜹니다 -> 위쪽 얇은 선에 마우스를 올리면 이동 손잡이가 나옵니다.
     그걸로 종목코드 위로 옮기고, 오른쪽 아래 모서리를 드래그해서 크기를 맞추세요.
  2. 노란 메모창이 뜹니다 -> 마찬가지로 위쪽에 마우스를 올리면 이동 손잡이가 나옵니다.
  3. 이후로는 그냥 켜두기만 하면 종목이 바뀔 때마다 자동으로 갱신됩니다.
  4. 위치/크기는 자동 저장되어 다음에 실행해도 그대로 유지됩니다.
  5. 메모창 오른쪽 위 ⚙ 을 누르면 테두리 박스를 다시 보이게/숨기게 하거나 종료할 수 있습니다.
"""
import json
import os
import re
import sys
import time
import hashlib
import traceback
import threading
import subprocess
import webbrowser
import tkinter as tk
from tkinter import messagebox
from concurrent.futures import ThreadPoolExecutor

from paths import get_base_dir

LOG_PATH = os.path.join(get_base_dir(), "error.log")


def _fatal_error(title, message):
    """무슨 일이 있어도 창이 조용히 사라지지 않도록, 에러를 로그+팝업으로 반드시 보여줍니다."""
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(message)
    except Exception:
        pass
    print(message)
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(title, message[:1500] + ("\n\n(전체 내용은 error.log 참고)" if len(message) > 1500 else ""))
        r.destroy()
    except Exception:
        pass
    sys.exit(1)


try:
    import mss
    import pytesseract
    from PIL import Image, ImageOps

    from stock_db import load_stock_db, code_to_name, is_valid_code
    from crawler import (
        get_sector, get_quarterly_financials, get_latest_news,
        get_from_kiwoom_bridge, get_theme_from_kiwoom_bridge,
        detect_corp_action,
    )
    import local_cache
except Exception:
    _fatal_error(
        "라이브러리 로드 실패",
        "필요한 라이브러리를 불러오지 못했습니다.\n\n"
        "run.bat을 다시 실행하거나, 아래 명령을 직접 실행해보세요:\n"
        "python -m pip install -r requirements.txt\n\n"
        "상세 오류:\n" + traceback.format_exc(),
    )

# ── Tesseract-OCR 경로 자동 탐색 (사용자가 직접 코드를 고칠 필요 없음) ──
def _auto_find_tesseract():
    import shutil

    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


_tesseract_path = _auto_find_tesseract()
if _tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_path
    print(f"[Tesseract] 자동으로 찾음: {_tesseract_path}")
else:
    print("[Tesseract] 못 찾음. Tesseract-OCR이 설치되어 있는지 확인이 필요합니다.")

CONFIG_PATH = os.path.join(get_base_dir(), "config.json")
POLL_INTERVAL_SEC = 0.15
BORDER_THICKNESS = 4
STRIP_THIN = 4     # 평소(마우스 안 올렸을 때) 이동바 두께
STRIP_FAT = 16      # 마우스 올렸을 때 이동바 두께

DEFAULT_CONFIG = {
    "region1": {"x": 80, "y": 80, "w": 160, "h": 40},
    "sticker": {"x": 400, "y": 150, "w": 280, "h": 260},
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[save_config] 저장 실패:", e)


# ── OCR ──────────────────────────────────────────
def _binarize(gray_img, threshold):
    return gray_img.point(lambda p: 255 if p > threshold else 0)


def ocr_code(img: Image.Image):
    """이미지 안에서 6자리 종목코드를 찾아 반환. 못 찾으면 None."""
    gray = img.convert("L")

    pixels = list(gray.getdata())
    mean = sum(pixels) / max(1, len(pixels))
    if mean < 128:  # 어두운 배경이면 반전
        gray = ImageOps.invert(gray)

    gray = ImageOps.autocontrast(gray)

    for threshold in (140, 100):  # 임계값 2개로 재시도 (속도 우선)
        bw = _binarize(gray, threshold)
        big = bw.resize((bw.width * 4, bw.height * 4), Image.LANCZOS)
        try:
            text = pytesseract.image_to_string(
                big, config="--psm 7 -c tessedit_char_whitelist=0123456789"
            )
        except pytesseract.TesseractNotFoundError:
            return "TESSERACT_NOT_FOUND"
        match = re.search(r"\d{6}", text)
        if match:
            return match.group(0)
    return None


class HoverDragStrip:
    """
    평소엔 얇은 선만 보이다가, 마우스를 올리면 두꺼워지며 손잡이(⠿⠿⠿)가 나타나는 이동 바.
    """
    def __init__(self, parent_toplevel, bg_thin, bg_fat, on_drag_move, on_drag_end):
        self.top = parent_toplevel
        self.bg_thin = bg_thin
        self.bg_fat = bg_fat
        self.on_drag_move = on_drag_move
        self.on_drag_end = on_drag_end
        self._drag = {}
        self._fat = False

        self.strip = tk.Frame(self.top, bg=bg_thin, height=STRIP_THIN, cursor="fleur")
        self.strip.place(x=0, y=0, relwidth=1, height=STRIP_THIN)

        self.grip_label = tk.Label(self.strip, text="⠿⠿⠿⠿⠿⠿⠿⠿⠿⠿", bg=bg_fat, fg="#666")
        # grip_label은 fat 상태일 때만 표시

        self.strip.bind("<Enter>", self._on_enter)
        self.strip.bind("<Leave>", self._on_leave)
        self.strip.bind("<ButtonPress-1>", self._start)
        self.strip.bind("<B1-Motion>", self._move)
        self.strip.bind("<ButtonRelease-1>", self._end)

    def _on_enter(self, e):
        self._fat = True
        self.strip.place_configure(height=STRIP_FAT)
        self.strip.config(bg=self.bg_fat)
        self.grip_label.place(relx=0.5, rely=0.5, anchor="center")

    def _on_leave(self, e):
        if self._drag.get("mode") == "move":
            return  # 드래그 중엔 안 줄어들게
        self._shrink()

    def _shrink(self):
        self._fat = False
        self.grip_label.place_forget()
        self.strip.place_configure(height=STRIP_THIN)
        self.strip.config(bg=self.bg_thin)

    def _start(self, e):
        self._drag = {"mode": "move", "x": e.x, "y": e.y}

    def _move(self, e):
        if self._drag.get("mode") != "move":
            return
        x = self.top.winfo_pointerx() - self._drag["x"]
        y = self.top.winfo_pointery() - self._drag["y"]
        self.top.geometry(f"+{x}+{y}")
        self.on_drag_move()

    def _end(self, e):
        self._drag = {}
        self.on_drag_end()
        # 마우스가 이미 벗어난 상태에서 놓았으면 줄여줌
        px, py = self.top.winfo_pointerxy()
        wx, wy = self.strip.winfo_rootx(), self.strip.winfo_rooty()
        ww, wh = self.strip.winfo_width(), max(self.strip.winfo_height(), STRIP_FAT)
        if not (wx <= px <= wx + ww and wy <= py <= wy + wh):
            self._shrink()


# ── 드래그로 이동/크기조절 가능한 캡처 영역 박스 ──────────────
class RegionOverlay:
    def __init__(self, root, geom, on_change):
        self.on_change = on_change
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        try:
            self.top.attributes("-transparentcolor", "magenta")
        except tk.TclError:
            pass
        self.top.config(bg="magenta")
        self.top.geometry(f"{geom['w']}x{geom['h']}+{geom['x']}+{geom['y']}")

        self.border = tk.Frame(self.top, bg="magenta",
                                highlightbackground="#ff3b3b", highlightthickness=BORDER_THICKNESS)
        self.border.place(x=0, y=0, relwidth=1, relheight=1)

        self.strip = HoverDragStrip(self.top, bg_thin="#ff3b3b", bg_fat="#ff3b3b",
                                     on_drag_move=lambda: None, on_drag_end=self._commit)

        self.grip = tk.Frame(self.top, bg="#ff3b3b", width=14, height=14, cursor="bottom_right_corner")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.grip.bind("<ButtonPress-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._do_resize)
        self.grip.bind("<ButtonRelease-1>", self._commit)

        self._drag = {}

        # 캡처 스레드(백그라운드)가 tkinter 함수를 직접 부르면 불안정/지연이 생기므로,
        # 좌표는 메인 스레드에서만 갱신되는 "캐시"에 저장해두고, 캡처는 이 캐시만 읽는다.
        self._geom_cache = dict(geom)
        self.top.after(50, self._refresh_geom_cache)  # 창이 실제로 뜬 뒤 한 번 더 정확히 동기화

    def _refresh_geom_cache(self):
        """메인 스레드에서만 호출됨 (tkinter 이벤트/after 콜백)"""
        self.top.update_idletasks()
        self._geom_cache = {
            "x": self.top.winfo_rootx(), "y": self.top.winfo_rooty(),
            "w": self.top.winfo_width(), "h": self.top.winfo_height(),
        }

    def _start_resize(self, e):
        self._drag = {"w": self.top.winfo_width(), "h": self.top.winfo_height(),
                      "px": e.x_root, "py": e.y_root}

    def _do_resize(self, e):
        dw = e.x_root - self._drag["px"]
        dh = e.y_root - self._drag["py"]
        new_w = max(40, self._drag["w"] + dw)
        new_h = max(24, self._drag["h"] + dh)
        self.top.geometry(f"{new_w}x{new_h}")

    def _commit(self, e=None):
        self._refresh_geom_cache()  # 메인 스레드(이벤트 핸들러)에서 호출되므로 안전
        self.on_change(self._geom_cache)

    def outer_geometry(self):
        """메인 스레드에서만 호출할 것 (설정 저장 등 용도)"""
        self._refresh_geom_cache()
        return dict(self._geom_cache)

    def capture_bbox(self):
        """백그라운드 캡처 스레드에서 호출됨 - tkinter를 절대 직접 건드리지 않고 캐시만 읽음"""
        g = self._geom_cache
        bt = BORDER_THICKNESS
        return {"x": g["x"] + bt, "y": g["y"] + bt,
                "w": max(1, g["w"] - 2 * bt), "h": max(1, g["h"] - 2 * bt)}

    def set_visible(self, visible):
        if visible:
            self.top.deiconify()
        else:
            self.top.withdraw()

    def is_visible(self):
        return self.top.state() != "withdrawn"


# ── 크기조절/이동 가능한 스티커 메모 ──────────────
class StickerMemo:
    def __init__(self, root, geom, on_change, on_toggle_region, on_quit, on_start_collector=None):
        self.on_change = on_change
        self.root = root
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.config(bg="#fef5c1")
        self.top.geometry(f"{geom['w']}x{geom['h']}+{geom['x']}+{geom['y']}")

        self.strip = HoverDragStrip(self.top, bg_thin="#e9d16a", bg_fat="#d8bd4a",
                                     on_drag_move=lambda: None, on_drag_end=self._commit)

        body = tk.Frame(self.top, bg="#fef5c1")
        body.place(x=0, y=STRIP_THIN, relwidth=1, relheight=1, height=-STRIP_THIN)

        self.lbl_name = tk.Label(body, text="종목 대기중...", font=("맑은 고딕", 14, "bold"),
                                  bg="#fef5c1", anchor="w", justify="left")
        self.lbl_name.pack(fill="x", padx=10, pady=(8, 2))

        self.lbl_sector = tk.Label(body, text="", font=("맑은 고딕", 10),
                                    bg="#fef5c1", anchor="w", justify="left", wraplength=240)
        self.lbl_sector.pack(fill="x", padx=10, pady=2)

        self.lbl_finance = tk.Label(body, text="", font=("맑은 고딕", 10),
                                     bg="#fef5c1", anchor="w", justify="left", wraplength=240)
        self.lbl_finance.pack(fill="x", padx=10, pady=2)

        tk.Label(body, text="📰 관련뉴스", font=("맑은 고딕", 10, "bold"),
                 bg="#fef5c1", anchor="w").pack(fill="x", padx=10, pady=(6, 0))

        self.news_frame = tk.Frame(body, bg="#fef5c1")
        self.news_frame.pack(fill="both", expand=True, padx=10, pady=2)

        gear = tk.Label(self.top, text="⚙", bg="#fef5c1", fg="#886", font=("맑은 고딕", 11, "bold"),
                         cursor="hand2")
        gear.place(relx=1.0, x=-28, y=STRIP_THIN + 4, anchor="ne")
        gear.bind("<Button-1>", self._show_menu)

        close_btn = tk.Label(self.top, text="✕", bg="#fef5c1", fg="#888",
                              font=("맑은 고딕", 10, "bold"), cursor="hand2")
        close_btn.place(relx=1.0, x=-4, y=STRIP_THIN + 4, anchor="ne")
        close_btn.bind("<Button-1>", lambda e: on_quit())

        self.grip = tk.Frame(self.top, bg="#c9a227", width=14, height=14, cursor="bottom_right_corner")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.grip.bind("<ButtonPress-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._do_resize)
        self.grip.bind("<ButtonRelease-1>", self._commit)

        self._menu = tk.Menu(self.top, tearoff=0)
        self._menu.add_command(label="캡처 영역 보이기/숨기기", command=on_toggle_region)
        if on_start_collector:
            self._menu.add_command(label="📥 데이터 미리 받기 시작 (전종목)", command=on_start_collector)
        self._menu.add_separator()
        self._menu.add_command(label="종료", command=on_quit)

        self._drag = {}
        self._current_wrap = 240

    def _show_menu(self, e):
        self._menu.tk_popup(e.x_root, e.y_root)

    def _start_resize(self, e):
        self._drag = {"w": self.top.winfo_width(), "h": self.top.winfo_height(),
                      "px": e.x_root, "py": e.y_root}

    def _do_resize(self, e):
        dw = e.x_root - self._drag["px"]
        dh = e.y_root - self._drag["py"]
        new_w = max(220, self._drag["w"] + dw)
        new_h = max(160, self._drag["h"] + dh)
        self.top.geometry(f"{new_w}x{new_h}")
        wrap = new_w - 30
        self._current_wrap = wrap
        self.lbl_sector.config(wraplength=wrap)
        self.lbl_finance.config(wraplength=wrap)
        for child in self.news_frame.winfo_children():
            child.config(wraplength=wrap)

    def _commit(self, e=None):
        self.on_change(self.geometry())

    def geometry(self):
        self.top.update_idletasks()
        return {"x": self.top.winfo_x(), "y": self.top.winfo_y(),
                "w": self.top.winfo_width(), "h": self.top.winfo_height()}

    def show_message(self, msg):
        self.lbl_name.config(text=msg)
        self.lbl_sector.config(text="")
        self.lbl_finance.config(text="")
        for w in self.news_frame.winfo_children():
            w.destroy()

    def show_name_only(self, name):
        """네트워크 요청 없이 즉시 표시 (반응 속도 개선용)"""
        self.lbl_name.config(text=name or "종목 확인중...")
        self.lbl_sector.config(text="🏷 업종: 불러오는 중...")
        self.lbl_finance.config(text="💰 실적: 불러오는 중...")
        for w in self.news_frame.winfo_children():
            w.destroy()
        tk.Label(self.news_frame, text="불러오는 중...", bg="#fef5c1",
                 font=("맑은 고딕", 9), fg="#888").pack(anchor="w")

    def update_sector_only(self, sector):
        """업종(테마)이 나중에 도착했을 때, 다른 내용은 그대로 두고 업종 줄만 갱신"""
        self.lbl_sector.config(text=f"🏷 업종: {sector}" if sector else "🏷 업종: 정보없음")

    def update_info(self, name, sector, finance, news_list):
        self.lbl_name.config(text=name or "알 수 없음")
        self.lbl_sector.config(text=f"🏷 업종: {sector}" if sector else "🏷 업종: 정보없음")

        if finance:
            lines = [
                f"💰 매출액({finance['quarter']}): {finance['sales']}",
                f"📈 영업이익({finance['quarter']}): {finance['profit']}",
            ]
            streak = finance.get("profit_streak")
            if streak is not None and streak > 0:
                lines.append(f"🔥 영업이익 {streak}분기 연속 흑자")
            if finance.get("profit_turnaround"):
                lines.append("✨ 이번 분기 영업이익 흑자 전환")
            if finance.get("sales_turnaround"):
                lines.append("✨ 매출 성장세로 전환")
            self.lbl_finance.config(text="\n".join(lines))
        else:
            self.lbl_finance.config(text="💰 실적 정보를 찾을 수 없습니다")

        for w in self.news_frame.winfo_children():
            w.destroy()

        if not news_list:
            tk.Label(self.news_frame, text="관련 뉴스 없음", bg="#fef5c1",
                     font=("맑은 고딕", 9), fg="#888").pack(anchor="w")
        else:
            for title, link in news_list:
                lbl = tk.Label(self.news_frame, text=f"• {title}", bg="#fef5c1",
                               fg="#1a5fb4", font=("맑은 고딕", 9, "underline"),
                               cursor="hand2", anchor="w", justify="left",
                               wraplength=self._current_wrap)
                lbl.pack(fill="x", anchor="w")
                lbl.bind("<Button-1>", lambda e, url=link: webbrowser.open(url))


# ── 전체 앱 ──────────────────────────────────────
class App:
    def __init__(self):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()

        self.stock_db = None  # 백그라운드에서 채워짐 (GUI를 안 막기 위해)

        self.region = RegionOverlay(self.root, self.cfg["region1"], self.save_region1)
        self.sticker = StickerMemo(self.root, self.cfg["sticker"], self.save_sticker,
                                    self.toggle_region, self.quit_app, self.start_data_collector)
        self.sticker.show_message("영역을 코드 위로 옮기고\n크기를 맞춰주세요\n(종목 목록 불러오는 중...)")

        self.last_code = None
        self.busy = False
        self._tesseract_warned = False
        self._stop = False
        self._executor = ThreadPoolExecutor(max_workers=3)

        # 종목 리스트는 시간이 걸릴 수 있어서 별도 스레드에서 불러옴 (GUI를 막지 않음)
        threading.Thread(target=self._load_stock_db_bg, daemon=True).start()

    def _load_stock_db_bg(self):
        try:
            db = load_stock_db()
        except Exception as e:
            print("[App] 종목 리스트 로드 중 예외:", e)
            db = None
        self.stock_db = db
        print(f"[App] 종목 리스트 준비 완료: {'실패(None)' if db is None else f'{len(db)}개'}")

    def save_region1(self, geom):
        self.cfg["region1"] = geom
        save_config(self.cfg)

    def save_sticker(self, geom):
        self.cfg["sticker"] = geom
        save_config(self.cfg)

    def toggle_region(self):
        self.region.set_visible(not self.region.is_visible())

    def start_data_collector(self):
        """메모창 메뉴에서 바로 데이터 수집기를 새 콘솔 창으로 실행"""
        base = get_base_dir()
        exe_path = os.path.join(base, "DataCollector.exe")
        script_path = os.path.join(base, "data_collector", "collect_all.py")

        try:
            if os.path.exists(exe_path):
                subprocess.Popen([exe_path], creationflags=subprocess.CREATE_NEW_CONSOLE,
                                  cwd=os.path.dirname(exe_path))
            elif os.path.exists(script_path):
                subprocess.Popen(["python", "collect_all.py"],
                                  creationflags=subprocess.CREATE_NEW_CONSOLE,
                                  cwd=os.path.dirname(script_path))
            else:
                messagebox.showinfo(
                    "데이터 수집기",
                    "data_collector 폴더나 DataCollector.exe를 찾을 수 없습니다.\n"
                    "data_collector\\run.bat을 먼저 실행해보세요."
                )
        except Exception as e:
            messagebox.showerror("데이터 수집기 실행 실패", str(e))

    def quit_app(self):
        self._stop = True
        self.root.destroy()

    def quick_hash(self, img):
        small = img.convert("L").resize((40, 16))
        return hashlib.md5(small.tobytes()).hexdigest()

    # ── 캡처+OCR은 화면 그리기와 완전히 분리된 백그라운드 스레드에서 실행 ──
    def _capture_loop(self):
        sct = mss.mss()  # mss는 스레드마다 별도 인스턴스가 필요함
        last_hash = None
        while not self._stop:
            try:
                bbox = self.region.capture_bbox()
                if bbox["w"] > 0 and bbox["h"] > 0:
                    monitor = {"left": bbox["x"], "top": bbox["y"],
                               "width": bbox["w"], "height": bbox["h"]}
                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    h = self.quick_hash(img)

                    if h != last_hash:
                        last_hash = h
                        code = ocr_code(img)

                        if code == "TESSERACT_NOT_FOUND":
                            if not self._tesseract_warned:
                                self._tesseract_warned = True
                                self.root.after(0, lambda: self.sticker.show_message(
                                    "⚠ Tesseract-OCR을 못 찾았어요\n"
                                    "https://github.com/UB-Mannheim/tesseract/wiki\n"
                                    "에서 설치해주세요 (설치만 하면 자동 인식됩니다)"))
                        elif code and is_valid_code(self.stock_db, code) and code != self.last_code:
                            self.last_code = code
                            if not self.busy:
                                self.busy = True
                                self._executor.submit(self.fetch_and_update, code)
            except Exception as e:
                print("[_capture_loop] 오류:", e)
            time.sleep(POLL_INTERVAL_SEC)

    def fetch_and_update(self, code):
        try:
            # 1) 종목명은 로컬 캐시에서 즉시 확인 -> 네트워크 없이 바로 화면 갱신 (체감속도 개선)
            name = code_to_name(self.stock_db, code)
            self.root.after(0, lambda: self.sticker.show_name_only(name or code))

            # 2) 실적(빠른 kiwoom /info, 없으면 네이버)과 뉴스를 먼저 받아서 즉시 표시
            #    -> 업종(테마)은 기다리지 않고 "불러오는 중" 상태로 먼저 보여줌
            kiwoom_data = get_from_kiwoom_bridge(code)

            if kiwoom_data and (kiwoom_data.get("매출액") or kiwoom_data.get("영업이익")):
                finance = {
                    "quarter": kiwoom_data.get("결산월", "") or "최근",
                    "sales": kiwoom_data.get("매출액"),
                    "profit": kiwoom_data.get("영업이익"),
                }
                if name is None:
                    name = kiwoom_data.get("종목명") or None
            else:
                finance = get_quarterly_financials(code)

            news = get_latest_news(code)

            # 뉴스에 사명/업종 변경 등을 암시하는 내용이 있으면, 그 종목의 캐시만 지움
            # (이미 어차피 받아온 뉴스를 재활용하는 것이라 추가 비용 없음)
            if detect_corp_action(news):
                local_cache.invalidate("sector", code)
                local_cache.invalidate("finance", code)
                print(f"[fetch_and_update] {code} 변경 감지 -> 캐시 무효화, 업종 재조회 예정")

            self.root.after(0, lambda: self.sticker.update_info(name, "불러오는 중...", finance, news))
        except Exception as e:
            print("[fetch_and_update] 오류:", e)
        finally:
            # 여기서 busy를 풀어야, 업종(테마)을 기다리는 동안에도 다음 종목 전환이 안 막힘
            self.busy = False

        # 3) 업종(테마)은 별도로(느긋하게) 조회. 그 사이에 다른 종목으로 바뀌었으면 결과를 버림.
        try:
            sector = get_theme_from_kiwoom_bridge(code)
            if not sector:
                sector = get_sector(code)
            if code == self.last_code:  # 아직도 같은 종목을 보고 있을 때만 반영
                self.root.after(0, lambda: self.sticker.update_sector_only(sector))
        except Exception as e:
            print("[fetch_and_update] 업종 조회 오류:", e)

    def run(self):
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self.root.mainloop()


if __name__ == "__main__":
    try:
        App().run()
    except Exception:
        _fatal_error(
            "실행 중 오류 발생",
            "프로그램 실행 중 오류가 발생했습니다.\n\n" + traceback.format_exc(),
        )
