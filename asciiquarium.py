#!/usr/bin/env python3
#
#############################################################################
# Asciiquarium - An aquarium animation in ASCII art (Python port)
#
# Original Perl version by Kirk Baucom <kbaucom@schizoid.com>
# ASCII art by Joan Stark
# Improved marine biodiversity by Claudio Matsuoka
#
# Python port preserves all original ASCII art and behavior.
#
# License: GPL v2 (same as original)
#############################################################################

import curses
import random
import time
import sys
import signal

VERSION = "1.1"

# Parse -c flag for classic mode
classic_mode = '-c' in sys.argv

new_fish = 0 if classic_mode else 1
new_monster = 0 if classic_mode else 1

# Z depth constants
DEPTH = {
    'guiText': 0,
    'gui': 1,
    'shark': 2,
    'fish_start': 3,
    'fish_end': 20,
    'seaweed': 21,
    'castle': 22,
    'water_line3': 2,
    'water_gap3': 3,
    'water_line2': 4,
    'water_gap2': 5,
    'water_line1': 6,
    'water_gap1': 7,
    'water_line0': 8,
    'water_gap0': 9,
}

# Color mapping: letter -> (curses color, bold)
# Initialized after curses.start_color() in _setup_curses
COLOR_MAP = {}


def init_color_map():
    global COLOR_MAP
    COLOR_MAP = {
        'k': (curses.COLOR_BLACK, False),
        'K': (curses.COLOR_BLACK, True),
        'r': (curses.COLOR_RED, False),
        'R': (curses.COLOR_RED, True),
        'g': (curses.COLOR_GREEN, False),
        'G': (curses.COLOR_GREEN, True),
        'y': (curses.COLOR_YELLOW, False),
        'Y': (curses.COLOR_YELLOW, True),
        'b': (curses.COLOR_BLUE, False),
        'B': (curses.COLOR_BLUE, True),
        'm': (curses.COLOR_MAGENTA, False),
        'M': (curses.COLOR_MAGENTA, True),
        'c': (curses.COLOR_CYAN, False),
        'C': (curses.COLOR_CYAN, True),
        'w': (curses.COLOR_WHITE, False),
        'W': (curses.COLOR_WHITE, True),
    }


def rand_color(color_mask):
    """Replace numbered placeholders 1-9 with random colors.
    4 always maps to W (white) for eyes."""
    colors = ['c', 'C', 'r', 'R', 'y', 'Y', 'b', 'B', 'g', 'G', 'm', 'M']
    result = color_mask
    for i in range(1, 10):
        if i == 4:
            color = 'W'
        else:
            color = colors[random.randint(0, len(colors) - 2)]
        result = result.replace(str(i), color)
    return result


class Entity:
    """An animated entity in the aquarium."""

    def __init__(self, name=None, etype=None, shape=None, color=None,
                 position=None, default_color='w', callback_args=None,
                 die_offscreen=False, die_time=None, die_frame=None,
                 death_cb=None, physical=False, coll_handler=None,
                 auto_trans=False, transparent=None, depth=None,
                 callback=None):
        self.name = name or ('entity_' + str(random.random()))
        self.type = etype or ''
        self.default_color = default_color
        self.physical = physical
        self.die_offscreen = die_offscreen
        self.die_time = die_time
        self.die_frame = die_frame
        self.death_cb = death_cb
        self.coll_handler = coll_handler
        self.auto_trans = auto_trans
        self.transparent = transparent
        self.callback = callback
        self.callback_args = list(callback_args) if callback_args else [0, 0, 0, 1]
        self.depth = depth  # collision depth range
        self.alive = True
        self.frame_num = 0
        self.tick_count = 0

        # Position [x, y, z]
        self.x = position[0] if position else 0
        self.y = position[1] if position else 0
        self.z = position[2] if position else 0

        # Parse shapes
        if isinstance(shape, str):
            self.shapes = [shape]
        elif isinstance(shape, list):
            self.shapes = list(shape)
        else:
            self.shapes = ['']

        # Parse color masks
        if isinstance(color, str):
            self.color_masks = [color]
        elif isinstance(color, list):
            self.color_masks = list(color)
        else:
            self.color_masks = None

        # Pre-parse all shape frames into line arrays
        self.parsed_shapes = []
        self.width = 0
        self.height = 0
        for s in self.shapes:
            lines = s.split('\n')
            # Remove leading empty line if present
            if lines and lines[0] == '':
                lines = lines[1:]
            # Remove trailing empty line if present
            if lines and lines[-1] == '':
                lines = lines[:-1]
            self.parsed_shapes.append(lines)
            for line in lines:
                if len(line) > self.width:
                    self.width = len(line)
            if len(lines) > self.height:
                self.height = len(lines)

        # Pre-parse color masks
        self.parsed_colors = []
        if self.color_masks:
            for cm in self.color_masks:
                lines = cm.split('\n')
                if lines and lines[0] == '':
                    lines = lines[1:]
                if lines and lines[-1] == '':
                    lines = lines[:-1]
                self.parsed_colors.append(lines)

        # Movement accumulator for fractional speeds
        self._move_accum_x = 0.0
        self._move_accum_y = 0.0
        self._anim_accum = 0.0

        # Collisions list
        self.collisions_list = []

    def kill(self):
        self.alive = False

    def position(self):
        return [self.x, self.y, self.z]

    def size(self):
        return [self.width, self.height]

    def current_frame(self):
        idx = self.frame_num % len(self.parsed_shapes)
        return self.parsed_shapes[idx]

    def current_color_mask(self):
        if not self.parsed_colors:
            return None
        idx = self.frame_num % len(self.parsed_colors)
        return self.parsed_colors[idx]

    def advance_frame(self):
        """Advance animation frame based on anim_speed accumulator."""
        if len(self.parsed_shapes) > 1:
            anim_speed = self.callback_args[3] if len(self.callback_args) > 3 else 1
            self._anim_accum += anim_speed
            while self._anim_accum >= 1.0:
                self._anim_accum -= 1.0
                self.frame_num += 1

    def move(self):
        """Move entity based on callback_args velocity."""
        dx = self.callback_args[0]
        dy = self.callback_args[1]

        self._move_accum_x += dx
        self._move_accum_y += dy

        int_dx = int(self._move_accum_x)
        int_dy = int(self._move_accum_y)

        if int_dx != 0:
            self._move_accum_x -= int_dx
            self.x += int_dx
        if int_dy != 0:
            self._move_accum_y -= int_dy
            self.y += int_dy

        self.advance_frame()
        self.tick_count += 1


class Aquarium:
    """Main aquarium animation engine."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.entities = []
        self.color_pairs = {}
        self.next_pair_id = 1
        self._setup_curses()

    def _setup_curses(self):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        init_color_map()
        self.stdscr.nodelay(False)
        curses.halfdelay(1)

    def get_color_pair(self, fg, bold=False):
        """Get or create a curses color pair for the given foreground color."""
        key = (fg, bold)
        if key not in self.color_pairs:
            pair_id = self.next_pair_id
            self.next_pair_id += 1
            curses.init_pair(pair_id, fg, -1)
            self.color_pairs[key] = pair_id
        pair_id = self.color_pairs[key]
        attr = curses.color_pair(pair_id)
        if bold:
            attr |= curses.A_BOLD
        return attr

    def get_attr_for_color_char(self, ch, default_color='w'):
        """Get curses attribute for a color character code."""
        if ch == ' ' or ch == '?':
            ch = default_color
        if ch in COLOR_MAP:
            fg, bold = COLOR_MAP[ch]
            return self.get_color_pair(fg, bold)
        # fallback
        if default_color in COLOR_MAP:
            fg, bold = COLOR_MAP[default_color]
            return self.get_color_pair(fg, bold)
        return curses.A_NORMAL

    def width(self):
        return self.stdscr.getmaxyx()[1]

    def height(self):
        return self.stdscr.getmaxyx()[0]

    def add_entity(self, entity):
        self.entities.append(entity)

    def remove_entity(self, entity):
        if entity in self.entities:
            self.entities.remove(entity)

    def remove_all(self):
        self.entities.clear()

    def get_entities_of_type(self, etype):
        return [e for e in self.entities if e.type == etype]

    def draw(self):
        """Draw all entities sorted by z-depth (highest z first = background)."""
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        # Sort by z descending so low z (foreground) draws last (on top)
        sorted_entities = sorted(self.entities, key=lambda e: -e.z)

        for entity in sorted_entities:
            if not entity.alive:
                continue
            frame = entity.current_frame()
            color_mask = entity.current_color_mask()
            ex = int(entity.x)
            ey = int(entity.y)

            for row_idx, line in enumerate(frame):
                sy = ey + row_idx
                if sy < 0 or sy >= h:
                    continue

                color_line = None
                if color_mask and row_idx < len(color_mask):
                    color_line = color_mask[row_idx]

                for col_idx, ch in enumerate(line):
                    sx = ex + col_idx
                    if sx < 0 or sx >= w:
                        continue
                    # Skip last cell to avoid curses scroll error
                    if sy == h - 1 and sx == w - 1:
                        continue

                    # Transparency
                    if ch == ' ':
                        if entity.auto_trans:
                            continue
                        if entity.transparent == ' ':
                            continue

                    # Determine color
                    color_ch = None
                    if color_line and col_idx < len(color_line):
                        color_ch = color_line[col_idx]

                    if color_ch and color_ch != ' ':
                        attr = self.get_attr_for_color_char(color_ch, entity.default_color)
                    else:
                        attr = self.get_attr_for_color_char(entity.default_color, entity.default_color)

                    try:
                        self.stdscr.addch(sy, sx, ch, attr)
                    except curses.error:
                        pass

        try:
            self.stdscr.noutrefresh()
            curses.doupdate()
        except curses.error:
            pass

    def animate(self):
        """One animation tick: move entities, check lifecycle, check collisions."""
        now = time.time()

        # Move all entities and run callbacks
        for entity in self.entities:
            if not entity.alive:
                continue

            # Custom callback (for fish that blow bubbles)
            if entity.callback:
                entity.callback(entity, self)

            entity.move()

            # Check die_time
            if entity.die_time and now >= entity.die_time:
                entity.alive = False

            # Check die_frame
            if entity.die_frame and entity.tick_count >= entity.die_frame:
                entity.alive = False

            # Check die_offscreen
            if entity.die_offscreen and entity.alive:
                ex = int(entity.x)
                ey = int(entity.y)
                ew = entity.width
                eh = entity.height
                if (ex + ew < 0 or ex >= self.width() or
                        ey + eh < 0 or ey >= self.height()):
                    entity.alive = False

        # Collision detection among physical entities
        physical = [e for e in self.entities if e.physical and e.alive]
        for i in range(len(physical)):
            for j in range(i + 1, len(physical)):
                a = physical[i]
                b = physical[j]
                if self._check_collision(a, b):
                    a.collisions_list.append(b)
                    b.collisions_list.append(a)

        # Call collision handlers
        for entity in physical:
            if entity.collisions_list and entity.alive and entity.coll_handler:
                entity.coll_handler(entity, self)
            entity.collisions_list = []

        # Process dead entities
        for entity in list(self.entities):
            if not entity.alive:
                cb = entity.death_cb
                self.entities.remove(entity)
                if cb:
                    cb(entity, self)

    def _check_collision(self, a, b):
        """Check bounding box collision between two entities."""
        ax, ay = int(a.x), int(a.y)
        bx, by = int(b.x), int(b.y)

        # Check z-depth overlap
        a_z_min = a.z
        a_z_max = a.z + (a.depth if a.depth else 0)
        b_z_min = b.z
        b_z_max = b.z + (b.depth if b.depth else 0)

        if not (a_z_min <= b_z_max and b_z_min <= a_z_max):
            return False

        # Bounding box overlap
        if (ax < bx + b.width and ax + a.width > bx and
                ay < by + b.height and ay + a.height > by):
            return True
        return False


# =============================================================================
# ASCII Art Definitions
# =============================================================================

WATER_LINE_SEGMENTS = [
    '~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~',
    '^^^^ ^^^  ^^^   ^^^    ^^^^      ',
    '^^^^      ^^^^     ^^^    ^^     ',
    '^^      ^^^^      ^^^    ^^^^^^  ',
]

# Castle - no backslashes needing escaping
CASTLE_IMAGE = "\n".join([
    "               T~~",
    "               |",
    "              /^\\",
    "             /   \\",
    " _   _   _  /     \\  _   _   _",
    "[ ]_[ ]_[ ]/ _   _ \\[ ]_[ ]_[ ]",
    "|_=__-_ =_|_[ ]_[ ]_|_=-___-__|",
    " | _- =  | =_ = _    |= _=   |",
    " |= -[]  |- = _ =    |_-=_[] |",
    " | =_    |= - ___    | =_ =  |",
    " |=  []- |-  /| |\\   |=_ =[] |",
    " |- =_   | =| | | |  |- = -  |",
    " |_______|__|_|_|_|__|_______|",
])

CASTLE_MASK = "\n".join([
    "                RR",
    "",
    "",
    "              yyy",
    "             y   y",
    "            y     y",
    "           y       y",
    "",
    "",
    "",
    "              yyy",
    "             yy yy",
    "            y y y y",
    "            yyyyyyy",
])

# ---------------------------------------------------------------------------
# Old fish (classic) - pairs of (image, color_mask)
# Each pair: even index = right-facing, odd = left-facing
# In Perl q{}, \\ -> \, \} -> }, other \ are literal
# ---------------------------------------------------------------------------
OLD_FISH = [
    # pair 0: right-facing
    ("       \\\n"
     "     ...\\..,\n"
     "\\  /'       \\\n"
     " >=     (  ' >\n"
     "/  \\      / /\n"
     "    `\"'\"'/''",
     "\n       2\n"
     "     1112111\n"
     "6  11       1\n"
     " 66     7  4 5\n"
     "6  1      3 1\n"
     "    11111311"),
    # pair 1: left-facing
    ("      /\n"
     "  ,../...\n"
     " /       '\\  /\n"
     "< '  )     =<\n"
     " \\ \\      /  \\\n"
     "  `'\\'\"'\"'",
     "\n      2\n"
     "  1112111\n"
     " 1       11  6\n"
     "5 4  7     66\n"
     " 1 3      1  6\n"
     "  11311111"),
    # pair 2: right-facing
    ("    \\\n"
     "\\ /--\\\n"
     ">=  (o>\n"
     "/ \\__/\n"
     "    /",
     "\n    2\n"
     "6 1111\n"
     "66  745\n"
     "6 1111\n"
     "    3"),
    # pair 3: left-facing
    ("  /\n"
     " /--\\ /\n"
     "<o)  =<\n"
     " \\__/ \\\n"
     "  \\",
     "\n  2\n"
     " 1111 6\n"
     "547  66\n"
     " 1111 6\n"
     "  3"),
    # pair 4: right-facing (spiny)
    ("       \\:.\n"
     "\\;,   ,;\\\\,,\n"
     "  \\\\;;:::::::o\n"
     "  ///;;::::::::<\n"
     " /;` ``/////``",
     "\n       222\n"
     "666   1122211\n"
     "  6661111111114\n"
     "  66611111111115\n"
     " 666 113333311"),
    # pair 5: left-facing (spiny)
    ("      .:/\n"
     "   ,,///;,   ,;/\n"
     " o:::::::;;///\n"
     ">::::::::;;\\\\\n"
     "  ''\\\\\\\\'' ';\\",
     "\n      222\n"
     "   1122211   666\n"
     " 4111111111666\n"
     "51111111111666\n"
     "  113333311 666"),
    # pair 6: right-facing (tiny)
    ("  __\n"
     "><_'>\n"
     "   '",
     "  11\n"
     "61145\n"
     "   3"),
    # pair 7: left-facing (tiny)
    (" __\n"
     "<'_><\n"
     " `",
     " 11\n"
     "54116\n"
     " 3"),
    # pair 8: right-facing
    ("   ..\\,\n"
     ">='   ('>\n"
     "  '''/''",
     "\n   1121\n"
     "661   745\n"
     "  111311"),
    # pair 9: left-facing
    ("  ,/..\n"
     "<')   `=<\n"
     " ``\\```",
     "\n  1211\n"
     "547   166\n"
     " 113111"),
    # pair 10: right-facing
    ("   \\\n"
     "  / \\\n"
     ">=_('>\n"
     "  \\_/\n"
     "   /",
     "\n   2\n"
     "  1 1\n"
     "661745\n"
     "  111\n"
     "   3"),
    # pair 11: left-facing
    ("  /\n"
     " / \\\n"
     "<')_=<\n"
     " \\_/\n"
     "  \\",
     "\n  2\n"
     " 1 1\n"
     "547166\n"
     " 111\n"
     "  3"),
    # pair 12: right-facing
    ("  ,\\\n"
     ">=('>   \n"
     "  '/",
     "\n  12\n"
     "66745\n"
     "  13"),
    # pair 13: left-facing
    (" /,\n"
     "<')=<\n"
     " \\`",
     "\n 21\n"
     "54766\n"
     " 31"),
    # pair 14: right-facing
    ("  __\n"
     "\\/ o\\\n"
     "/\\__/",
     "\n  11\n"
     "61 41\n"
     "61111"),
    # pair 15: left-facing
    (" __\n"
     "/o \\/\n"
     "\\__/\\",
     "\n 11\n"
     "14 16\n"
     "11116"),
]

# ---------------------------------------------------------------------------
# New fish (non-classic)
# ---------------------------------------------------------------------------
NEW_FISH = [
    # pair 0: right-facing
    ("   \\\n"
     "  / \\\n"
     ">=_('>\n"
     "  \\_/\n"
     "   /",
     "\n   1\n"
     "  1 1\n"
     "663745\n"
     "  111\n"
     "   3"),
    # pair 1: left-facing
    ("  /\n"
     " / \\\n"
     "<')_=<\n"
     " \\_/\n"
     "  \\",
     "\n  2\n"
     " 111\n"
     "547366\n"
     " 111\n"
     "  3"),
    # pair 2: right-facing (fancy with } chars)
    ("     ,\n"
     "     }\\\n"
     "\\  .'  `\\\n"
     "}}<   ( 6>\n"
     "/  `,  .'\n"
     "     }/\n"
     "     '",
     "\n     2\n"
     "     22\n"
     "6  11  11\n"
     "661   7 45\n"
     "6  11  11\n"
     "     33\n"
     "     3"),
    # pair 3: left-facing (fancy with { chars)
    ("    ,\n"
     "   /{\n"
     " /'  `.  /\n"
     "<6 )   >{{\n"
     " `.  ,'  \\\n"
     "   \\{\n"
     "    `",
     "\n    2\n"
     "   22\n"
     " 11  11  6\n"
     "54 7   166\n"
     " 11  11  6\n"
     "   33\n"
     "    3"),
    # pair 4: right-facing (big fancy)
    ("            \\'`.\n"
     "             )  \\\n"
     "(`.??????_.-`' ' '`-.\n"
     " \\ `.??.`        (o) \\_\n"
     "  >  ><     (((       (\n"
     " / .`??`._      /_|  /'\n"
     "(.`???????`-. _  _.-`\n"
     "            /__/'\n",
     "\n            1111\n"
     "             1  1\n"
     "111      11111 1 1111\n"
     " 1 11  11        141 11\n"
     "  1  11     777       5\n"
     " 1 11  111      333  11\n"
     "111       111 1  1111\n"
     "            11111\n"),
    # pair 5: left-facing (big fancy)
    ("       .'`/\n"
     "      /  (\n"
     "  .-'` ` `'-._??????.')\n"
     "_/ (o)        '.??.' /\n"
     ")       )))     ><  <\n"
     "`\\  |_\\      _.'??'. \\\n"
     "  '-._  _ .-'???????'.)\n"
     "      `\\__\\",
     "\n       1111\n"
     "      1  1\n"
     "  1111 1 11111      111\n"
     "11 141        11  11 1\n"
     "5       777     11  1\n"
     "11  333      111  11 1\n"
     "  1111  1 111       111\n"
     "      11111"),
    # pair 6: right-facing
    ("       ,--,_\n"
     "__    _\\.---'-.\n"
     "\\ '.-\"     // o\\\n"
     "/_.'-._    \\\\  /\n"
     "       `\"--(/\"`",
     "\n       22222\n"
     "66    121111211\n"
     "6 6111     77 41\n"
     "6661111    77  1\n"
     "       11113311"),
    # pair 7: left-facing
    ("    _,--,\n"
     " .-'---./_    __\n"
     "/o \\\\     \"-.' /\n"
     "\\  //    _.-'._\\\n"
     " `\"\\)--\"`",
     "\n    22222\n"
     " 112111121    66\n"
     "14 77     1116 6\n"
     "1  77    1111666\n"
     " 11331111"),
]

# ---------------------------------------------------------------------------
# Shark
# ---------------------------------------------------------------------------
SHARK_IMAGE = [
    # right-facing (dir=0)
    ("\n"
     "                              __\n"
     "                             ( `\\\n"
     "  ,??????????????????????????)   `\\\n"
     ";' `.????????????????????????(     `\\__\n"
     " ;   `.?????????????__..---''          `~~~~-._\n"
     "  `.   `.____...--''                       (b  `--._\n"
     "    >                     _.-'      .((      ._     )\n"
     "  .`.-`--...__         .-'     -.___.....-(|/|/|/|/'\n"
     " ;.'?????????`. ...----`.___.',,,_______......---'\n"
     " '???????????'-'"),
    # left-facing (dir=1)
    ("\n"
     "                     __\n"
     "                    /' )\n"
     "                  /'   (??????????????????????????,\n"
     "              __/'     )????????????????????????.' `;\n"
     "      _.-~~~~'          ``---..__?????????????.'   ;\n"
     " _.--'  b)                       ``--...____.'   .'\n"
     "(     _.      )).      `-._                     <\n"
     " `\\|\\|\\|\\)-.....___.-     `-.         __...--'-.'.\n"
     "   `---......_______,,,`.___.'----... .'?????????`.;\n"
     "                                     `-`???????????`"),
]

SHARK_MASK = [
    # right-facing (dir=0)
    ("\n\n\n\n\n\n"
     "                                           cR\n"
     " \n"
     "                                          cWWWWWWWW\n\n"),
    # left-facing (dir=1)
    ("\n\n\n\n\n\n"
     "        Rc\n"
     "\n"
     "  WWWWWWWWc\n\n"),
]

# ---------------------------------------------------------------------------
# Ship
# ---------------------------------------------------------------------------
SHIP_IMAGE = [
    # right-facing (dir=0)
    ("\n"
     "     |    |    |\n"
     "    )_)  )_)  )_)\n"
     "   )___))___))___)\\\n"
     "  )____)____)_____)\\\\\n"
     "_____|____|____|____\\\\__\n"
     "\\                   /"),
    # left-facing (dir=1)
    ("\n"
     "         |    |    |\n"
     "        (_(  (_(  (_(\n"
     "      /(___((___((___(  \n"
     "    //(_____(____(____(  \n"
     "__///____|____|____|_____\n"
     "    \\                   /"),
]

SHIP_MASK = [
    # right-facing (dir=0)
    ("\n"
     "     y    y    y\n"
     "\n"
     "                  w\n"
     "                   ww\n"
     " yyyyyyyyyyyyyyyyyyyywwwyy\n"
     "y                   y"),
    # left-facing (dir=1)
    ("\n"
     "         y    y    y\n"
     "\n"
     "      w\n"
     "    ww\n"
     "yywwwyyyyyyyyyyyyyyyyyyyy\n"
     "    y                   y"),
]

# ---------------------------------------------------------------------------
# Whale
# ---------------------------------------------------------------------------
WHALE_IMAGE = [
    # right-facing (dir=0)
    ("\n"
     "        .-----:\n"
     "      .'       `.\n"
     ",????/       (o) \\\n"
     "\\`._/          ,__)"),
    # left-facing (dir=1)
    ("\n"
     "    :-----.\n"
     "  .'       `.\n"
     " / (o)       \\????,\n"
     "(__,          \\_.'/"),
]

WHALE_MASK = [
    # right-facing (dir=0)
    ("\n"
     "             C C\n"
     "           CCCCCCC\n"
     "           C  C  C\n"
     "        BBBBBBB\n"
     "      BB       BB\n"
     "B    B       BWB B\n"
     "BBBBB          BBBB"),
    # left-facing (dir=1)
    ("\n"
     "   C C\n"
     " CCCCCCC\n"
     " C  C  C\n"
     "    BBBBBBB\n"
     "  BB       BB\n"
     " B BWB       B    B\n"
     "BBBB          BBBBB"),
]

WATER_SPOUT = [
    "\n\n   :",
    "\n   :\n   :",
    "  . .\n  -:-\n   :",
    "  . .\n .-:-.\n   :",
    "  . .\n'.-:-.`\n'  :  '",
    "\n .- -.\n;  :  ;",
    "\n\n;     ;",
]

# ---------------------------------------------------------------------------
# Old Monster (classic)
# ---------------------------------------------------------------------------
OLD_MONSTER_IMAGE_RIGHT = [
    ("\n"
     "                                                          ____\n"
     "            __??????????????????????????????????????????/   o  \\\n"
     "          /    \\????????_?????????????????????_???????/     ____ >\n"
     "  _??????|  __  |?????/   \\????????_????????/   \\????|     |\n"
     " | \\?????|  ||  |????|     |?????/   \\?????|     |???|     |"),
    ("\n"
     "                                                          ____\n"
     "                                             __?????????/   o  \\\n"
     "             _?????????????????????_???????/    \\?????/     ____ >\n"
     "   _???????/   \\????????_????????/   \\????|  __  |???|     |\n"
     "  | \\?????|     |?????/   \\?????|     |???|  ||  |???|     |"),
    ("\n"
     "                                                          ____\n"
     "                                  __????????????????????/   o  \\\n"
     " _??????????????????????_???????/    \\????????_???????/     ____ >\n"
     "| \\??????????_????????/   \\????|  __  |?????/   \\????|     |\n"
     " \\ \\???????/   \\?????|     |???|  ||  |????|     |???|     |"),
    ("\n"
     "                                                          ____\n"
     "                       __???????????????????????????????/   o  \\\n"
     "  _??????????_???????/    \\????????_??????????????????/     ____ >\n"
     " | \\???????/   \\????|  __  |?????/   \\????????_??????|     |\n"
     "  \\ \\?????|     |???|  ||  |????|     |?????/   \\????|     |"),
]

OLD_MONSTER_IMAGE_LEFT = [
    ("    ____\n"
     "  /  o   \\??????????????????????????????????????????__\n"
     "< ____     \\???????_?????????????????????_????????/    \\\n"
     "      |     |????/   \\????????_????????/   \\?????|  __  |??????_\n"
     "      |     |???|     |?????/   \\?????|     |????|  ||  |?????/ |"),
    ("    ____\n"
     "  /  o   \\?????????__\n"
     "< ____     \\?????/    \\???????_?????????????????????_\n"
     "      |     |???|  __  |????/   \\????????_????????/   \\???????_\n"
     "      |     |???|  ||  |???|     |?????/   \\?????|     |?????/ |"),
    ("    ____\n"
     "  /  o   \\????????????????????__\n"
     "< ____     \\???????_????????/    \\???????_??????????????????????_\n"
     "      |     |????/   \\?????|  __  |????/   \\????????_??????????/ |\n"
     "      |     |???|     |????|  ||  |???|     |?????/   \\???????/ /"),
    ("    ____\n"
     "  /  o   \\???????????????????????????????__\n"
     "< ____     \\??????????????????_????????/    \\???????_??????????_\n"
     "      |     |??????_????????/   \\?????|  __  |????/   \\???????/ |\n"
     "      |     |????/   \\?????|     |????|  ||  |???|     |?????/ /"),
]

OLD_MONSTER_MASK_RIGHT = ("\n\n"
                          "                                                            W\n"
                          "\n\n")

OLD_MONSTER_MASK_LEFT = ("\n\n"
                         "     W\n"
                         "\n\n")

# ---------------------------------------------------------------------------
# New Monster
# ---------------------------------------------------------------------------
NEW_MONSTER_IMAGE_RIGHT = [
    ("\n"
     "         _???_?????????????????????_???_???????_a_a\n"
     "       _{.`=`.}_??????_???_??????_{.`=`.}_????{/ ''\\_\n"
     " _????{.'  _  '.}????{.`'`.}????{.'  _  '.}??{|  ._oo)\n"
     "{ \\??{/  .'?'.  \\}??{/ .-. \\}??{/  .'?'.  \\}?{/  |"),
    ("\n"
     "                      _???_????????????????????_a_a\n"
     "  _??????_???_??????_{.`=`.}_??????_???_??????{/ ''\\_\n"
     " { \\????{.`'`.}????{.'  _  '.}????{.`'`.}????{|  ._oo)\n"
     "  \\ \\??{/ .-. \\}??{/  .'?'.  \\}??{/ .-. \\}???{/  |"),
]

NEW_MONSTER_IMAGE_LEFT = [
    ("   a_a_???????_???_?????????????????????_???_\n"
     " _/'' \\}????_{.`=`.}_??????_???_??????_{.`=`.}_\n"
     "(oo_.  |}??{.'  _  '.}????{.`'`.}????{.'  _  '.}????_\n"
     "    |  \\}?{/  .'?'.  \\}??{/ .-. \\}??{/  .'?'.  \\}??/ }"),
    ("   a_a_????????????????????_   _\n"
     " _/'' \\}??????_???_??????_{.`=`.}_??????_???_??????_\n"
     "(oo_.  |}????{.`'`.}????{.'  _  '.}????{.`'`.}????/ }\n"
     "    |  \\}???{/ .-. \\}??{/  .'?'.  \\}??{/ .-. \\}??/ /"),
]

NEW_MONSTER_MASK_RIGHT = ("                                                W W\n"
                          "\n\n")

NEW_MONSTER_MASK_LEFT = ("   W W\n"
                         "\n\n")

# ---------------------------------------------------------------------------
# Big Fish 1
# ---------------------------------------------------------------------------
BIG_FISH_1_IMAGE = [
    # right-facing (dir=0)
    ("\n"
     " ______\n"
     "`\"\"-.  `````-----.....__\n"
     "     `.  .      .       `-.\n"
     "       :     .     .       `.\n"
     " ,?????:   .    .          _ :\n"
     ": `.???:                  (@) `._\n"
     " `. `..'     .     =`-.       .__)\n"
     "   ;     .        =  ~  :     .-\"\n"
     " .' .'`.   .    .  =.-'  `._ .'\n"
     ": .'???:               .   .'\n"
     " '???.'  .    .     .   .-'\n"
     "   .'____....----''.'=.'\n"
     "   \"\"?????????????.'.' \n"
     "               ''\"'`"),
    # left-facing (dir=1)
    ("\n"
     "                           ______\n"
     "          __.....-----'''''  .-\"\"'\n"
     "       .-'       .      .  .'\n"
     "     .'       .     .     :\n"
     "    : _          .    .   :?????,\n"
     " _.' (@)                  :???.' :\n"
     "(__.       .-'=     .     `..' .'\n"
     " \"-.     :  ~  =        .     ;\n"
     "   `. _.'  `-.=  .    .   .'`. `.\n"
     "     `.   .               :???`. :\n"
     "       `-.   .     .    .  `.???`\n"
     "          `.=`.``----....____`.\n"
     "            `.`.?????????????\"\"\n"
     "              '`\"``"),
]

BIG_FISH_1_MASK = [
    # right-facing (dir=0)
    ("\n"
     " 111111\n"
     "11111  11111111111111111\n"
     "     11  2      2       111\n"
     "       1     2     2       11\n"
     " 1     1   2    2          1 1\n"
     "1 11   1                  1W1 111\n"
     " 11 1111     2     1111       1111\n"
     "   1     2        1  1  1     111\n"
     " 11 1111   2    2  1111  111 11\n"
     "1 11   1               2   11\n"
     " 1   11  2    2     2   111\n"
     "   111111111111111111111\n"
     "   11             1111\n"
     "               11111"),
    # left-facing (dir=1)
    ("\n"
     "                           111111\n"
     "          11111111111111111  11111\n"
     "       111       2      2  11\n"
     "     11       2     2     1\n"
     "    1 1          2    2   1     1\n"
     " 111 1W1                  1   11 1\n"
     "1111       1111     2     1111 11\n"
     " 111     1  1  1        2     1\n"
     "   11 111  1111  2    2   1111 11\n"
     "     11   2               1   11 1\n"
     "       111   2     2    2  11   1\n"
     "          111111111111111111111\n"
     "            1111             11\n"
     "              11111"),
]

# ---------------------------------------------------------------------------
# Big Fish 2
# ---------------------------------------------------------------------------
BIG_FISH_2_IMAGE = [
    # right-facing (dir=0)
    ("\n"
     "                _ _ _\n"
     "             ='\\ \\ \\`\"=,\n"
     "           .'\\ \\ \\ \\ \\ \\ \\\n"
     "\\'=._?????/ \\ \\ \\_\\_\\_\\_\\_\\\n"
     "\\'=._'.??/\\ \\,-\"`- _ - _ - '-.\n"
     "  \\`=._\\|'.\\/- _ - _ - _ - _- \\\n"
     "  ;\"= ._\\=./_ -_ -_ \\{`\"=_    @ \\\n"
     "   ;\"=_-_=- _ -  _ - \\{\"=_\"-     \\\n"
     "   ;_=_--_.,          \\{_.='   .-/\n"
     "  ;.=\"` / ';\\        _.     _.-`\n"
     "  /_.='/ \\/ /;._ _ _\\{.-;`/\"`\n"
     "/._=_.'???'/ / / / /\\{.= /\n"
     "/.=' ??????`'./_/_.=`\\{_/"),
    # left-facing (dir=1)
    ("\n"
     "            _ _ _\n"
     "        ,=\"`/ / /'=.\n"
     "       / / / / / / /'.\n"
     "      /_/_/_/_/_/ / / \\?????_.='/\n"
     "   .-' - _ - _ -`\"-,/ /\\??.'_.='/\n"
     "  / -_ - _ - _ - _ -\\/.'|/_.=`/\n"
     " / @    _=\"`} _- _- _\\.=/_. =\";\n"
     "/     -\"_=\"} - _  - _ -=_-_\"=;\n"
     "\\-.   '=._}          ,._--_=_;\n"
     " `-._     ._        /;' \\ `\"=.;\n"
     "     `\"\\`;-.}_ _ _.;\\ \\/ \\'=._\\\n"
     "        \\ =.}\\ \\ \\ \\ \\'???'._=_.\\\n"
     "         \\_}`=.\\_\\.'`???????'=.\\"),
]

BIG_FISH_2_MASK = [
    # right-facing (dir=0)
    ("\n"
     "                1 1 1\n"
     "             1111 1 11111\n"
     "           111 1 1 1 1 1 1\n"
     "11111     1 1 1 11111111111\n"
     "1111111  11 111112 2 2 2 2 111\n"
     "  111111111112 2 2 2 2 2 2 22 1\n"
     "  111 1111 12 22 22 11111    W 1\n"
     "   11111112 2 2  2 2 111111     1\n"
     "   111111111          11111   111\n"
     "  11111 11111        11     1111\n"
     "  111111 11 1111 1 111111111\n"
     "1111111   11 1 1 1 1111 1\n"
     "1111       1111111111111"),
    # left-facing (dir=1)
    ("\n"
     "            1 1 1\n"
     "        11111 1 1111\n"
     "       1 1 1 1 1 1 111\n"
     "      11111111111 1 1 1     11111\n"
     "   111 2 2 2 2 211111 11  1111111\n"
     "  1 22 2 2 2 2 2 2 211111111111\n"
     " 1 W    11111 22 22 2111111 111\n"
     "1     111111 2 2  2 2 21111111\n"
     "111   11111          111111111\n"
     " 1111     11        111 1 11111\n"
     "     111111111 1 1111 11 111111\n"
     "        1 1111 1 1 1 11   1111111\n"
     "         1111111111111       1111"),
]

# ---------------------------------------------------------------------------
# Splat
# ---------------------------------------------------------------------------
SPLAT_FRAMES = [
    "\n\n   .\n  ***\n   '\n",
    "\n\n \",*;`\n \"*,**\n *\"'~'\n",
    "\n  , ,\n \" \",\"'\n *\" *'\"\n  \" ; .\n",
    "* ' , ' `\n' ` * . '\n ' `' \",'\n* ' \" * .\n\" * ', '",
]


# =============================================================================
# Entity creation functions
# =============================================================================

def add_environment(anim):
    """Add water line segments that tile across the screen."""
    segment_size = len(WATER_LINE_SEGMENTS[0])
    segment_repeat = anim.width() // segment_size + 1

    for i, seg in enumerate(WATER_LINE_SEGMENTS):
        tiled = seg * segment_repeat
        anim.add_entity(Entity(
            name="water_seg_%d" % i,
            etype="waterline",
            shape=tiled,
            position=[0, i + 5, DEPTH['water_line%d' % i]],
            default_color='c',
            physical=True,
        ))


def add_castle(anim):
    """Add the castle at the bottom-right of the screen."""
    anim.add_entity(Entity(
        name="castle",
        shape=CASTLE_IMAGE,
        color=CASTLE_MASK,
        position=[anim.width() - 32, anim.height() - 13, DEPTH['castle']],
        default_color='K',
    ))


def add_all_seaweed(anim):
    """Add seaweed scaled by screen width."""
    count = anim.width() // 15
    for _ in range(count):
        add_seaweed(None, anim)


def add_seaweed(old, anim):
    """Add a single seaweed entity with two animation frames."""
    height = random.randint(3, 6)
    frames = ['', '']
    for i in range(1, height + 1):
        left_side = i % 2
        right_side = 1 - left_side
        frames[left_side] += '(\n'
        frames[right_side] += ' )\n'

    x = random.randint(1, max(1, anim.width() - 3))
    y = anim.height() - height
    anim_speed = random.random() * 0.05 + 0.25

    anim.add_entity(Entity(
        name='seaweed_' + str(random.random()),
        shape=frames,
        position=[x, y, DEPTH['seaweed']],
        callback_args=[0, 0, 0, anim_speed],
        die_time=time.time() + random.randint(8 * 60, 12 * 60),
        death_cb=add_seaweed,
        default_color='g',
    ))


def add_bubble(fish, anim):
    """Add an air bubble near a fish's mouth."""
    cb = fish.callback_args
    pos = fish.position()
    sz = fish.size()
    bx = pos[0]
    by = pos[1] + sz[1] // 2
    bz = pos[2] - 1

    if cb[0] > 0:
        bx += sz[0]

    anim.add_entity(Entity(
        shape=['.', 'o', 'O', 'O', 'O'],
        etype='bubble',
        position=[bx, by, bz],
        callback_args=[0, -1, 0, 0.1],
        die_offscreen=True,
        physical=True,
        coll_handler=bubble_collision,
        default_color='C',
    ))


def bubble_collision(bubble, anim):
    """Pop bubble when it hits the waterline."""
    for col_obj in bubble.collisions_list:
        if col_obj.type == 'waterline':
            bubble.kill()
            break


def fish_callback(fish, anim):
    """Fish callback: randomly blow bubbles."""
    if random.randint(0, 99) > 97:
        add_bubble(fish, anim)


def fish_collision(fish, anim):
    """Fish collision: get eaten by shark teeth if small enough."""
    for col_obj in fish.collisions_list:
        if col_obj.type == 'teeth' and fish.height <= 5:
            pos = col_obj.position()
            add_splat(anim, pos[0], pos[1], pos[2])
            fish.kill()
            break


def add_all_fish(anim):
    """Add fish scaled by screen area below waterline."""
    screen_size = (anim.height() - 9) * anim.width()
    count = screen_size // 350
    for _ in range(count):
        add_fish(None, anim)


def add_fish(old, anim):
    """Add a fish - new or old style depending on mode."""
    if new_fish and random.randint(0, 11) > 8:
        add_fish_from_list(NEW_FISH, old, anim)
    else:
        add_fish_from_list(OLD_FISH, old, anim)


def add_fish_from_list(fish_list, old, anim):
    """Add a fish entity from a list of (image, mask) pairs."""
    num_pairs = len(fish_list)
    pair_idx = random.randint(0, num_pairs - 1)
    image, mask = fish_list[pair_idx]

    speed = random.random() * 2 + 0.25
    depth = random.randint(DEPTH['fish_start'], DEPTH['fish_end'])

    color_mask = mask.replace('4', 'W')
    color_mask = rand_color(color_mask)

    # Odd indices are left-facing (negative speed)
    if pair_idx % 2 == 1:
        speed *= -1

    entity = Entity(
        etype='fish',
        shape=image,
        auto_trans=True,
        color=color_mask,
        position=[0, 0, depth],
        callback=fish_callback,
        callback_args=[speed, 0, 0, 1],
        die_offscreen=True,
        death_cb=add_fish,
        physical=True,
        coll_handler=fish_collision,
    )

    max_height = 9
    min_height = anim.height() - entity.height
    if min_height <= max_height:
        min_height = max_height + 1
    entity.y = random.randint(max_height, min_height)

    if pair_idx % 2 == 1:
        entity.x = anim.width() - 2
    else:
        entity.x = 1 - entity.width

    anim.add_entity(entity)


def add_splat(anim, x, y, z):
    """Add a blood splat animation when a fish is eaten."""
    anim.add_entity(Entity(
        shape=SPLAT_FRAMES,
        position=[x - 4, y - 2, z - 2],
        default_color='R',
        callback_args=[0, 0, 0, 0.25],
        transparent=' ',
        die_frame=15,
    ))


def shark_death(shark, anim):
    """When a shark dies, also kill its teeth entity, then spawn random object."""
    teeth = anim.get_entities_of_type('teeth')
    for t in teeth:
        anim.remove_entity(t)
    random_object(shark, anim)


def add_shark(old, anim):
    """Add a shark with associated teeth entity."""
    d = random.randint(0, 1)
    x = -53
    speed = 2
    y = random.randint(9, max(9, anim.height() - 19))
    teeth_x = -9
    teeth_y = y + 7

    if d:
        speed = -2
        x = anim.width() - 2
        teeth_x = x + 9

    # Teeth entity for collision
    anim.add_entity(Entity(
        etype='teeth',
        shape='*',
        position=[teeth_x, teeth_y, DEPTH['shark'] + 1],
        depth=DEPTH['fish_end'] - DEPTH['fish_start'],
        callback_args=[speed, 0, 0, 1],
        physical=True,
    ))

    anim.add_entity(Entity(
        etype='shark',
        color=SHARK_MASK[d],
        shape=SHARK_IMAGE[d],
        auto_trans=True,
        position=[x, y, DEPTH['shark']],
        default_color='C',
        callback_args=[speed, 0, 0, 1],
        die_offscreen=True,
        death_cb=shark_death,
    ))


def add_ship(old, anim):
    """Add a ship that sails across the surface."""
    d = random.randint(0, 1)
    x = -24
    speed = 1
    if d:
        speed = -1
        x = anim.width() - 2

    anim.add_entity(Entity(
        color=SHIP_MASK[d],
        shape=SHIP_IMAGE[d],
        auto_trans=True,
        position=[x, 0, DEPTH['water_gap1']],
        default_color='W',
        callback_args=[speed, 0, 0, 1],
        die_offscreen=True,
        death_cb=random_object,
    ))


def add_whale(old, anim):
    """Add a whale with water spout animation."""
    d = random.randint(0, 1)
    speed = 1
    if d:
        spout_align = 1
        speed = -1
        x = anim.width() - 2
    else:
        spout_align = 11
        x = -18

    whale_anim = []
    whale_anim_mask = []

    # No water spout frames
    for _ in range(5):
        whale_anim.append("\n\n\n" + WHALE_IMAGE[d])
        whale_anim_mask.append(WHALE_MASK[d])

    # Animate water spout
    for spout_frame in WATER_SPOUT:
        lines = spout_frame.split('\n')
        aligned = ('\n' + ' ' * spout_align).join(lines)
        frame = aligned + WHALE_IMAGE[d]
        whale_anim.append(frame)
        whale_anim_mask.append(WHALE_MASK[d])

    anim.add_entity(Entity(
        color=whale_anim_mask,
        shape=whale_anim,
        auto_trans=True,
        position=[x, 0, DEPTH['water_gap2']],
        default_color='W',
        callback_args=[speed, 0, 0, 1],
        die_offscreen=True,
        death_cb=random_object,
    ))


def add_monster(old, anim):
    """Add a sea monster."""
    if new_monster:
        add_new_monster(old, anim)
    else:
        add_old_monster(old, anim)


def add_new_monster(old, anim):
    """Add the new-style sea monster."""
    d = random.randint(0, 1)
    speed = 2
    if d:
        speed = -2
        x = anim.width() - 2
        images = NEW_MONSTER_IMAGE_LEFT
        mask = NEW_MONSTER_MASK_LEFT
    else:
        x = -54
        images = NEW_MONSTER_IMAGE_RIGHT
        mask = NEW_MONSTER_MASK_RIGHT

    mask_list = [mask, mask]

    anim.add_entity(Entity(
        shape=images,
        auto_trans=True,
        color=mask_list,
        position=[x, 2, DEPTH['water_gap2']],
        callback_args=[speed, 0, 0, 0.25],
        death_cb=random_object,
        die_offscreen=True,
        default_color='G',
    ))


def add_old_monster(old, anim):
    """Add the old-style (classic) sea monster."""
    d = random.randint(0, 1)
    speed = 2
    if d:
        speed = -2
        x = anim.width() - 2
        images = OLD_MONSTER_IMAGE_LEFT
        mask = OLD_MONSTER_MASK_LEFT
    else:
        x = -64
        images = OLD_MONSTER_IMAGE_RIGHT
        mask = OLD_MONSTER_MASK_RIGHT

    mask_list = [mask] * 4

    anim.add_entity(Entity(
        shape=images,
        auto_trans=True,
        color=mask_list,
        position=[x, 2, DEPTH['water_gap2']],
        callback_args=[speed, 0, 0, 0.25],
        death_cb=random_object,
        die_offscreen=True,
        default_color='G',
    ))


def add_big_fish(old, anim):
    """Add a big fish - type 1 or type 2."""
    if new_fish and random.randint(0, 2) > 1:
        add_big_fish_2(old, anim)
    else:
        add_big_fish_1(old, anim)


def add_big_fish_1(old, anim):
    """Add big fish type 1."""
    d = random.randint(0, 1)
    speed = 3
    if d:
        x = anim.width() - 1
        speed = -3
    else:
        x = -34

    max_height = 9
    min_height = anim.height() - 15
    if min_height <= max_height:
        min_height = max_height + 1
    y = random.randint(max_height, min_height)

    color_mask = rand_color(BIG_FISH_1_MASK[d])

    anim.add_entity(Entity(
        shape=BIG_FISH_1_IMAGE[d],
        auto_trans=True,
        color=color_mask,
        position=[x, y, DEPTH['shark']],
        callback_args=[speed, 0, 0, 1],
        death_cb=random_object,
        die_offscreen=True,
        default_color='Y',
    ))


def add_big_fish_2(old, anim):
    """Add big fish type 2."""
    d = random.randint(0, 1)
    speed = 2.5
    if d:
        x = anim.width() - 1
        speed = -2.5
    else:
        x = -33

    max_height = 9
    min_height = anim.height() - 14
    if min_height <= max_height:
        min_height = max_height + 1
    y = random.randint(max_height, min_height)

    color_mask = rand_color(BIG_FISH_2_MASK[d])

    anim.add_entity(Entity(
        shape=BIG_FISH_2_IMAGE[d],
        auto_trans=True,
        color=color_mask,
        position=[x, y, DEPTH['shark']],
        callback_args=[speed, 0, 0, 1],
        death_cb=random_object,
        die_offscreen=True,
        default_color='Y',
    ))


RANDOM_OBJECTS = [add_ship, add_whale, add_monster, add_big_fish, add_shark]


def random_object(old, anim):
    """Spawn a random special object (ship, whale, monster, big fish, or shark)."""
    fn = random.choice(RANDOM_OBJECTS)
    fn(old, anim)


# =============================================================================
# Main
# =============================================================================

def main(stdscr):
    anim = Aquarium(stdscr)
    paused = False

    while True:
        # Set up all entities
        add_environment(anim)
        add_castle(anim)
        add_all_seaweed(anim)
        add_all_fish(anim)
        random_object(None, anim)

        anim.draw()

        while True:
            try:
                ch = stdscr.getch()
            except curses.error:
                ch = -1

            if ch != -1:
                c = chr(ch).lower() if 0 <= ch < 256 else ''
                if c == 'q':
                    return
                elif c == 'r':
                    break
                elif c == 'p':
                    paused = not paused

            if not paused:
                anim.animate()
                anim.draw()

        # Redraw: remove everything and restart
        anim.remove_all()


if __name__ == '__main__':
    # Ignore SIGWINCH to avoid crashing on terminal resize
    signal.signal(signal.SIGWINCH, signal.SIG_IGN)
    curses.wrapper(main)
