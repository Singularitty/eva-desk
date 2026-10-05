# kitty custom tab bar, Eva desk look: title-card blocks for tabs ("01 KITTY" lilac for the active one, the
# others with a purple underline), a MAGI readout on the right (tab count and the clock). Set by kitty.conf:
#   tab_bar_style custom   (this file lives next to kitty.conf)
# Colours follow eva.conf (rethemed by `eva-ctl theme`).
from datetime import datetime

from kitty.fast_data_types import Screen, get_options
from kitty.tab_bar import DrawData, ExtraData, TabBarData, as_rgb, draw_attributed_string
from kitty.utils import color_as_int

INK = as_rgb(0x0A0612)
INK_DEEP = as_rgb(0x050309)
LILAC = as_rgb(0xEBE6F7)
LILAC3 = as_rgb(0x857B9E)
DIM = as_rgb(0x5A4B7A)
PURPLE = as_rgb(0x6A2FB8)
GREEN = as_rgb(0x7DFF3F)
ORANGE = as_rgb(0xFF5A1F)


def _title(tab: TabBarData, max_len: int) -> str:
    t = (tab.title or "").strip()
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t.upper()


def draw_tab(draw_data: DrawData, screen: Screen, tab: TabBarData, before: int, max_title_length: int,
             index: int, is_last: bool, extra_data: ExtraData) -> int:
    screen.cursor.bg = INK_DEEP
    screen.cursor.fg = DIM
    if index == 1:
        screen.draw(" ")
    label = f" {index:02d} {_title(tab, max_title_length)} "
    if tab.is_active:
        screen.cursor.bg = LILAC
        screen.cursor.fg = INK
        screen.cursor.bold = True
        screen.draw(label)
    else:
        screen.cursor.bg = INK_DEEP
        screen.cursor.fg = ORANGE if tab.needs_attention else LILAC3
        screen.cursor.bold = False
        # the purple underline of an occupied-but-not-active tab, as on the desk bar
        screen.cursor.decoration = 1
        screen.cursor.decoration_fg = PURPLE
        screen.draw(label)
        screen.cursor.decoration = 0
    screen.cursor.bg = INK_DEEP
    screen.cursor.fg = DIM
    screen.cursor.bold = False
    screen.draw(" ")
    end = screen.cursor.x
    if is_last:
        _right_readout(screen, extra_data, index)
    return end


def _right_readout(screen: Screen, extra_data: ExtraData, count: int) -> None:
    clock = datetime.now().strftime("%H:%M")
    text = f"MAGI·{clock}  TABS {count:02d} "
    x = screen.columns - len(text)
    if x <= screen.cursor.x:
        return
    screen.cursor.x = x
    screen.cursor.bg = INK_DEEP
    screen.cursor.fg = GREEN
    screen.draw("MAGI")
    screen.cursor.fg = DIM
    screen.draw("·")
    screen.cursor.fg = LILAC3
    screen.draw(f"{clock}  TABS {count:02d} ")
