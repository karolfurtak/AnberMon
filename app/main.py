#!/usr/bin/env python3
"""AnbernMon — monitor aktywności bota i systemu na Anbernic RG40XX V."""
import os, sys, time, json, glob
from collections import deque
from pathlib import Path
from datetime import datetime

os.environ.pop('SDL_VIDEODRIVER', None)

import sdl2, sdl2.ext
from PIL import Image, ImageDraw, ImageFont
import ctypes

# ── Stałe ──────────────────────────────────────────────────────────────────
ACTIVITY_FILE = Path('/mnt/data/anberbot_activity.json')
WORK_DIR      = Path('/mnt/data/sprawozdania')
REFRESH_MS    = 2000
HISTORY_SIZE  = 120   # próbek × 2s = 4 minuty
FONT_PATH     = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
FONT_SM       = 11   # tekst główny
FONT_MD       = 13   # nagłówki sekcji
FONT_LG       = 15   # tytuł

BG   = (10,  12,  20,  255)
FG   = (200, 210, 220, 255)
ACC  = (80,  180, 255, 255)   # niebieski — nagłówki
GRN  = (80,  220, 100, 255)   # zielony — OK
YEL  = (255, 210, 60,  255)   # żółty — ostrzeżenia
RED  = (255, 80,  80,  255)   # czerwony — wysoki poziom
DIM  = (90,  100, 110, 255)   # szary — pomocniczy
SEP  = (40,  50,  65,  255)   # linia podziału

W, H = 640, 480
EXIT_KEYS = {354, 316}   # MENU (354 = KEY_MENU) lub BTN_MODE (316) — różne firmware
POWER_KEY = 116          # KEY_POWER (event0) — toggle ekranu
FB_BLANK  = '/sys/class/graphics/fb0/blank'  # 0=on, 4=off (działa nawet z SDL)

# ── Czytanie zasobów systemowych ────────────────────────────────────────────
def read_cpu() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.3)
    except Exception:
        return 0.0

def read_mem():
    try:
        import psutil
        m = psutil.virtual_memory()
        s = psutil.swap_memory()
        return m.percent, m.used >> 20, m.total >> 20, s.percent
    except Exception:
        return 0.0, 0, 0, 0.0

def read_temp() -> str:
    try:
        v = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())
        return f"{v/1000:.1f}°C"
    except Exception:
        return "N/A"

def read_bat() -> tuple:
    try:
        cap = int(Path('/sys/class/power_supply/axp2202-battery/capacity').read_text())
        status = Path('/sys/class/power_supply/axp2202-battery/status').read_text().strip()
        return cap, status
    except Exception:
        return None, None

def read_disk(path='/mnt/data'):
    """Zajętość dysku danych: (procent, MB zajęte, MB pojemność)."""
    try:
        import shutil
        u = shutil.disk_usage(path)
        used = u.total - u.free
        pct = used / u.total * 100 if u.total else 0.0
        return pct, used >> 20, u.total >> 20
    except Exception:
        return 0.0, 0, 0

TOKENS_FILE = Path('/mnt/data/anberbot_tokens.json')

def read_tokens():
    """Zużycie tokenów Claude (kumulacyjne, prune-safe). Zwraca dict lub None.
    Źródło: anberbot-token-tally.timer -> /mnt/data/anberbot_tokens.json."""
    try:
        d = json.loads(TOKENS_FILE.read_text(encoding='utf-8'))
        return {
            'io':    int(d.get('in', 0)) + int(d.get('out', 0)),
            'cache': int(d.get('cc', 0)) + int(d.get('cr', 0)),
            'n':     int(d.get('sessions_n', 0)),
        }
    except Exception:
        return None

def _htok(n) -> str:
    """Skrót liczby tokenów: 1234 -> 1.2K, 1_233_490 -> 3.23M.
    2 miejsca po przecinku w zakresie M, by widać było przyrost (~10k = 0.01M)."""
    if n >= 1_000_000:
        return f'{n/1_000_000:.2f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(int(n))

def read_boot_time():
    """Epoch czasu startu systemu (z /proc/stat btime). None gdy brak."""
    try:
        for line in Path('/proc/stat').read_text().splitlines():
            if line.startswith('btime'):
                return int(line.split()[1])
    except Exception:
        pass
    return None

def read_activity() -> dict:
    try:
        return json.loads(ACTIVITY_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'queue': 0, 'busy': False, 'messages': [], 'files': []}

def read_ip() -> str:
    """Adres IPv4 aktywnego interfejsu (preferuj wlan0)."""
    try:
        import socket, subprocess
        # spróbuj wlan0 najpierw
        for iface in ('wlan0', 'wlan1', 'eth0'):
            try:
                r = subprocess.run(['ip', '-4', 'addr', 'show', iface],
                                   capture_output=True, text=True, timeout=2)
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('inet '):
                        return line.split()[1].split('/')[0]
            except Exception:
                continue
        # fallback: connect do publicznego IP (bez ruchu) — zwraca local-side IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(('8.8.8.8', 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return 'brak'

def bot_online() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(['cmdline']):
            if any('anberbot' in (a or '') for a in (p.info['cmdline'] or [])):
                return True
        return False
    except Exception:
        return False

def count_files() -> int:
    return sum(1 for f in WORK_DIR.rglob('*')
               if f.is_file() and not f.name.endswith('.meta.json'))

# ── Bar helper ───────────────────────────────────────────────────────────────
def bar(pct: float, width: int = 12) -> str:
    filled = int(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)

def pct_color(pct: float):
    if pct < 60: return GRN
    if pct < 80: return YEL
    return RED

# ── Renderer ─────────────────────────────────────────────────────────────────
class Monitor:
    def __init__(self):
        self._dbg = open('/mnt/data/anbermon_debug.log', 'a')
        self._dbg.write(f'\n=== START {datetime.now():%H:%M:%S} ===\n'); self._dbg.flush()

        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
            self._dbg.write(f'SDL_Init FAIL: {sdl2.SDL_GetError()}\n'); self._dbg.flush()
        else:
            self._dbg.write('SDL_Init OK\n'); self._dbg.flush()

        self.win = sdl2.SDL_CreateWindow(
            b"AnbernMon",
            sdl2.SDL_WINDOWPOS_UNDEFINED, sdl2.SDL_WINDOWPOS_UNDEFINED,
            0, 0,
            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP | sdl2.SDL_WINDOW_SHOWN
        )
        self._dbg.write(f'win={self.win}\n'); self._dbg.flush()

        self.ren = sdl2.SDL_CreateRenderer(self.win, -1, sdl2.SDL_RENDERER_SOFTWARE)
        if not self.ren:
            self.ren = sdl2.SDL_CreateRenderer(self.win, -1, 0)
        self._dbg.write(f'ren={self.ren} err={sdl2.SDL_GetError()}\n'); self._dbg.flush()

        self.img  = Image.new('RGBA', (W, H), BG)
        self.draw = ImageDraw.Draw(self.img)
        self.fsm  = ImageFont.truetype(FONT_PATH, FONT_SM)
        self.fmd  = ImageFont.truetype(FONT_PATH, FONT_MD)
        self.flg  = ImageFont.truetype(FONT_PATH, FONT_LG)

        self._tex = None
        self._file_count = 0
        self._file_ts    = 0.0
        self._history: deque = deque(maxlen=HISTORY_SIZE)  # (cpu, ram, temp_c)

        # evdev dla MENU (event1 = ANBERNIC-keys)
        self._gp = None
        try:
            import evdev
            self._gp = evdev.InputDevice('/dev/input/event1')
            self._gp.grab()
            self._dbg.write(f'evdev OK grab: {self._gp.name}\n'); self._dbg.flush()
            import select as _sel
            while _sel.select([self._gp.fd], [], [], 0)[0]:
                self._gp.read()
        except Exception as _ex:
            self._dbg.write(f'evdev grab FAIL ({_ex}), retry no-grab\n'); self._dbg.flush()
            try:
                import evdev as _ev
                self._gp = _ev.InputDevice('/dev/input/event1')
                self._dbg.write(f'evdev OK no-grab: {self._gp.name}\n'); self._dbg.flush()
            except Exception as _ex2:
                self._dbg.write(f'evdev FAIL entirely: {_ex2}\n'); self._dbg.flush()
                self._gp = None

        # event0 = power button (axp2202-pek) — grab → toggle fb0/blank
        self._pwr = None
        self._screen_off = False
        try:
            import evdev as _ev2
            self._pwr = _ev2.InputDevice('/dev/input/event0')
            self._pwr.grab()
            self._dbg.write(f'evdev power grab OK: {self._pwr.name}\n'); self._dbg.flush()
        except Exception as _ex3:
            self._dbg.write(f'evdev power FAIL: {_ex3}\n'); self._dbg.flush()
            self._pwr = None

    def _toggle_screen(self):
        try:
            self._screen_off = not self._screen_off
            val = '4' if self._screen_off else '0'
            Path(FB_BLANK).write_text(val)
            self._dbg.write(f'screen {"OFF" if self._screen_off else "ON"} fb0={val}\n'); self._dbg.flush()
        except Exception as e:
            self._dbg.write(f'screen toggle ERR: {e}\n'); self._dbg.flush()

    def _cw(self, font) -> int:
        bb = font.getbbox('M')
        return bb[2] - bb[0]

    def _ch(self, font) -> int:
        bb = font.getbbox('Mg')
        return bb[3] - bb[1] + 2

    def _text(self, x, y, txt, font, color):
        self.draw.text((x, y), txt, font=font, fill=color)

    def _hline(self, y):
        self.draw.line([(0, y), (W, y)], fill=SEP, width=1)


    def _draw_chart(self, x0: int, y0: int, w: int, h: int):
        d = self.draw
        hist = self._history
        # tło i ramka
        d.rectangle([(x0, y0), (x0 + w, y0 + h)], fill=(14, 17, 28, 255))
        d.rectangle([(x0, y0), (x0 + w, y0 + h)], outline=SEP)
        # linie siatki 25 / 50 / 75 %
        for pct in (25, 50, 75):
            gy = y0 + h - int(pct / 100 * h)
            d.line([(x0 + 1, gy), (x0 + w - 1, gy)], fill=SEP, width=1)
            self._text(x0 + 3, gy - 10, f'{pct}', self.fsm, DIM)
        # legenda (prawa strona, nad ramką)
        lx = x0 + w - 130
        self._text(lx,      y0 + 2, 'CPU',  self.fsm, GRN)
        self._text(lx + 32, y0 + 2, 'RAM',  self.fsm, ACC)
        self._text(lx + 64, y0 + 2, 'TEMP', self.fsm, RED)
        if len(hist) < 2:
            return
        n   = len(hist)
        dx  = w / HISTORY_SIZE
        off = HISTORY_SIZE - n   # gdy historia jeszcze niepełna

        def series(idx, scale=1.0):
            pts = []
            for i, s in enumerate(hist):
                xi = x0 + int((off + i) * dx)
                yi = y0 + h - 1 - int(min(s[idx] * scale, 100) / 100 * (h - 2))
                pts.append((xi, yi))
            return pts

        for pts, col in [
            (series(0),       GRN),   # CPU %
            (series(1),       ACC),   # RAM %
            (series(2, 1.0),  RED),   # Temp °C → 0-100 skala
        ]:
            if len(pts) >= 2:
                d.line(pts, fill=col, width=1)

    def render(self):
        d = self.draw
        d.rectangle([(0,0),(W,H)], fill=BG)

        now   = datetime.now().strftime('%Y-%m-%d  %H:%M:%S')
        cpu   = read_cpu()
        ram_p, ram_u, ram_t, swp_p = read_mem()
        act   = read_activity()
        try:
            temp_c = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
        except Exception:
            temp_c = 0.0
        self._history.append((cpu, ram_p, temp_c))

        # ── Nagłówek ────────────────────────────────────────────────────────
        self._text(8, 4, '⬡ ANBERNIC MONITOR', self.fmd, ACC)
        tw = self.fmd.getlength(now)
        self._text(W - int(tw) - 8, 4, now, self.fmd, DIM)
        self._hline(22)

        # ── Lewa kolumna: SYSTEM ────────────────────────────────────────────
        y = 28
        self._text(8, y, 'SYSTEM', self.fsm, ACC); y += 16

        for label, pct in [('CPU ', cpu), ('RAM ', ram_p), ('Swap', swp_p)]:
            col = pct_color(pct)
            line = f'{label} {pct:5.1f}%  {bar(pct, 10)}'
            self._text(8, y, line, self.fsm, col); y += 14

        temp_col = GRN if temp_c < 60 else (YEL if temp_c < 75 else RED)
        self._text(8, y, f'Temp {temp_c:.1f}°C  {bar(min(temp_c,100), 10)}', self.fsm, temp_col); y += 14
        self._text(8, y, f'RAM  {ram_u}/{ram_t} MB', self.fsm, DIM); y += 14

        disk_p, disk_u, disk_t = read_disk()
        self._text(8, y, f'Disk {disk_u}/{disk_t} MB  {bar(disk_p, 10)}', self.fsm, pct_color(disk_p)); y += 14

        bat_cap, bat_status = read_bat()
        if bat_cap is not None:
            bat_col = GRN if bat_cap > 50 else (YEL if bat_cap > 20 else RED)
            bat_s   = '(laduje)' if bat_status == 'Charging' else ('(pelna)' if bat_status == 'Full' else '')
            self._text(8, y, f'Bat  {bat_cap:3d}%  {bar(bat_cap, 10)} {bat_s}', self.fsm, bat_col)
        y += 14

        # ── Prawa kolumna: BOT ──────────────────────────────────────────────
        bx = 240
        y2 = 28
        self._text(bx, y2, 'BOT', self.fsm, ACC); y2 += 16
        online  = bot_online()
        net_col = GRN if online else RED
        net_st  = 'online' if online else 'offline'
        self._text(bx, y2, f'Bot:     {net_st}', self.fsm, net_col); y2 += 14
        bot_col = YEL if act.get('busy') else GRN
        bot_st  = 'przetwarza...' if act.get('busy') else 'gotowy'
        self._text(bx, y2, f'Status:  {bot_st}', self.fsm, bot_col); y2 += 14
        q = act.get('queue', 0)
        self._text(bx, y2, f'Kolejka: {q} zadań', self.fsm, YEL if q else FG); y2 += 14

        # liczba plików (odświeżana co 10s żeby nie obciążać)
        now_ts = time.time()
        if now_ts - self._file_ts > 10:
            self._file_count = count_files()
            self._file_ts = now_ts
        self._text(bx, y2, f'Pliki:   {self._file_count} total', self.fsm, FG); y2 += 14

        uptime_raw = Path('/proc/uptime').read_text().split()[0]
        up_s = int(float(uptime_raw))
        up_str = f'{up_s//3600}h {(up_s%3600)//60}m'
        bt = read_boot_time()
        bt_s = f'  (od {datetime.fromtimestamp(bt):%m-%d %H:%M})' if bt else ''
        self._text(bx, y2, f'Uptime:  {up_str}{bt_s}', self.fsm, DIM); y2 += 14
        self._text(bx, y2, f'IP: {read_ip()}', self.fsm, ACC); y2 += 14

        tok = read_tokens()
        if tok:
            self._text(bx, y2,
                       f'Tokeny:  {_htok(tok["io"])} I/O +{_htok(tok["cache"])} cache · {tok["n"]} ses',
                       self.fsm, GRN)
        else:
            self._text(bx, y2, 'Tokeny:  brak danych', self.fsm, YEL)

        # ── Separator ───────────────────────────────────────────────────────
        sep_y = y + 4
        self._hline(sep_y)

        # ── Wykres CPU / RAM / TEMP ──────────────────────────────────────────
        CHART_H = 100
        chart_y = sep_y + 4
        self._draw_chart(8, chart_y, W - 16, CHART_H)
        sep2_y = chart_y + CHART_H + 4
        self._hline(sep2_y)

        # ── Wiadomości Discord ───────────────────────────────────────────────
        y = sep2_y + 4
        self._text(8, y, 'WIADOMOŚCI DISCORD', self.fsm, ACC); y += 14

        msgs = act.get('messages', [])[-12:]
        for m in reversed(msgs):
            ts      = m.get('time', '')
            author  = m.get('author', '')[:12]
            thread  = m.get('thread') or m.get('channel', '')
            content = m.get('content', '').split('\n')[0].strip()
            att     = m.get('att', 0)
            bot_msg = m.get('bot', False)

            thread_s = f'[#{thread[:18]}] ' if thread else ''
            att_s    = f' 📎×{att}' if att else ''
            line = f'{ts}  {thread_s}{author}: {content}{att_s}'
            col  = ACC if bot_msg else FG
            # truncate to fit
            max_ch = (W - 16) // self._cw(self.fsm)
            if len(line) > max_ch:
                line = line[:max_ch-1] + '…'
            self._text(8, y, line, self.fsm, col)
            y += 13
            if y > H - 55:
                break

        # ── Ostatnie pliki ───────────────────────────────────────────────────
        self._hline(H - 52)
        y = H - 50
        self._text(8, y, 'OSTATNIE PLIKI', self.fsm, ACC); y += 14

        files = act.get('files', [])[-3:]
        for f in reversed(files):
            ts   = f.get('time', '')
            name = f.get('name', '')[:22]
            proj = f.get('project', 'incoming')[:20]
            sz   = f.get('size', 0) >> 10
            line = f'{ts}  {proj}/{name}  ({sz} KB)'
            max_ch = (W - 16) // self._cw(self.fsm)
            if len(line) > max_ch:
                line = line[:max_ch-1] + '…'
            self._text(8, y, line, self.fsm, DIM)
            y += 13

        # ── Stopka ───────────────────────────────────────────────────────────
        self._text(8, H-14, 'MENU = wyjście  |  POWER = ekran off/on', self.fsm, DIM)

        # ── SDL blit ─────────────────────────────────────────────────────────
        raw = self.img.tobytes()
        surf = sdl2.SDL_CreateRGBSurfaceWithFormatFrom(
            raw, W, H, 32, W*4, sdl2.SDL_PIXELFORMAT_RGBA32)
        if self._tex:
            sdl2.SDL_DestroyTexture(self._tex)
        self._tex = sdl2.SDL_CreateTextureFromSurface(self.ren, surf)
        sdl2.SDL_FreeSurface(surf)
        sdl2.SDL_RenderClear(self.ren)
        sdl2.SDL_RenderCopy(self.ren, self._tex, None, None)
        sdl2.SDL_RenderPresent(self.ren)

    def run(self):
        self._dbg.write('run() START\n'); self._dbg.flush()
        ev   = sdl2.SDL_Event()
        last = 0
        # odrzuć eventy zgromadzone podczas nawigacji dmenu
        drained = 0
        while sdl2.SDL_PollEvent(ctypes.byref(ev)):
            drained += 1
        self._dbg.write(f'SDL drained {drained} events\n'); self._dbg.flush()
        start_ms = sdl2.SDL_GetTicks()
        GUARD_MS = 5000  # pierwsze 5s — ignoruj quit/esc

        last_blank_re = 0
        while True:
            now = sdl2.SDL_GetTicks()

            # gdy ekran ma być OFF, ponawiaj write co 200ms (kernel ma tendencję do przywracania)
            if self._screen_off and now - last_blank_re >= 200:
                try: Path(FB_BLANK).write_text('4')
                except Exception: pass
                last_blank_re = now

            # render tylko gdy ekran włączony
            if not self._screen_off and now - last >= REFRESH_MS:
                self.render()
                last = now

            guard = (now - start_ms) < GUARD_MS

            # evdev — loguj wszystkie key-events, wyjdź na MENU_KEY
            if self._gp:
                import select, evdev
                if select.select([self._gp.fd], [], [], 0)[0]:
                    for e in self._gp.read():
                        if e.type == 1:  # EV_KEY
                            self._dbg.write(f'evdev key code={e.code} val={e.value} guard={guard}\n'); self._dbg.flush()
                            if not guard and e.value == 1 and e.code in EXIT_KEYS:
                                self._dbg.write(f'EXIT key code={e.code}\n'); self._dbg.flush()
                                self.quit(); return

            # event0 = power button → toggle screen przez fb0/blank
            if self._pwr:
                import select
                if select.select([self._pwr.fd], [], [], 0)[0]:
                    for e in self._pwr.read():
                        if e.type == 1 and e.code == POWER_KEY and e.value == 1 and not guard:
                            self._toggle_screen()

            # SDL events — wyjdź TYLKO przez ESC (BT klawiatura).
            # SDL_QUIT i inne KEYDOWN ignorowane — żeby przeżyć uśpienie/wybudzenie.
            while sdl2.SDL_PollEvent(ctypes.byref(ev)):
                if guard:
                    continue
                if ev.type == sdl2.SDL_QUIT:
                    self._dbg.write('SDL_QUIT (ignoruję — pewnie sleep)\n'); self._dbg.flush()
                    continue
                if ev.type == sdl2.SDL_KEYDOWN:
                    self._dbg.write(f'KEYDOWN sym={ev.key.keysym.sym}\n'); self._dbg.flush()
                    if ev.key.keysym.sym == sdl2.SDLK_ESCAPE:
                        self._dbg.write('EXIT ESC\n'); self._dbg.flush()
                        self.quit(); return

            sdl2.SDL_Delay(50)

    def quit(self):
        # zawsze przywróć ekran ON żeby nie zostawić ciemnego wyświetlacza
        try: Path(FB_BLANK).write_text('0')
        except Exception: pass
        if self._pwr:
            try: self._pwr.ungrab()
            except Exception: pass
        if self._gp:
            try: self._gp.ungrab()
            except Exception: pass
        if self._tex:
            sdl2.SDL_DestroyTexture(self._tex)
        sdl2.SDL_DestroyRenderer(self.ren)
        sdl2.SDL_DestroyWindow(self.win)
        sdl2.SDL_Quit()

if __name__ == '__main__':
    Monitor().run()
