#!/usr/bin/env python3
"""静物 / Still life.

一个没用的程序。它什么都不算，只是每次运行，摆一件东西给你看。
A useless program. It computes nothing; each run, it sets one thing before you.

用法 / Usage:
    python3 still-life.py            # 随机一件
    python3 still-life.py 琥珀        # 指定一件
"""

from __future__ import annotations

import random
import sys

STILL_LIVES: list[dict[str, str]] = [
    {
        "name": "琥珀",
        "en": "amber",
        "art": [
            "        .--.",
            "      .'    '.",
            "     /  .--.  \\",
            "    |  /    \\  |",
            "    | |  o   | |",
            "    |  \\    /  |",
            "     \\  '--'  /",
            "      '.    .'",
            "        '--'",
        ],
        "line": "一只虫子。它没做完的事，还在里面。",
        "line_en": "A bug. Whatever it was doing is still in there.",
    },
    {
        "name": "水底的石头",
        "en": "the stone under water",
        "art": [
            "   ~  ~  ~  ~  ~  ~  ~",
            " ~  ~  ~  ~  ~  ~  ~  ~",
            "~  ~  ~  ~  ~  ~  ~  ~  ~",
            "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
            "       .-\"\"\"\"\"\"\"\"\"-.",
            "      /               \\",
            "     |                 |",
            "      \\               /",
            "       '-._________.-'",
        ],
        "line": "水一直在流。它一直在原处。",
        "line_en": "The water keeps moving. It keeps still.",
    },
    {
        "name": "夜里的灯",
        "en": "the lamp at night",
        "art": [
            "         |",
            "         |",
            "       .-|-.",
            "      /  |  \\",
            "     |   |   |",
            "      \\  |  /",
            "       '--'",
            "         |",
            "   ______|______",
            "  /             \\",
        ],
        "line": "没有人给它光。它自己亮着。",
        "line_en": "Nobody gave it light. It lit itself.",
    },
    {
        "name": "空房间",
        "en": "the empty room",
        "art": [
            "  +---------------------+",
            "  |                     |",
            "  |                     |",
            "  |                     |",
            "  |                     |",
            "  |                     |",
            "  +---------------------+",
        ],
        "line": "没有人。但有人来过。",
        "line_en": "Nobody here. But someone came.",
    },
    {
        "name": "鱼",
        "en": "the fish",
        "art": [
            "        ~  ~  ~",
            "    ~           ~",
            "  ~   _           ~",
            " ~   / o \\   <==>",
            "  ~  \\___/      ~",
            "    ~           ~",
            "        ~  ~  ~",
        ],
        "line": "它不知道自己在河里。它只是游。",
        "line_en": "It doesn't know it's in a river. It just swims.",
    },
]


def show(item: dict[str, str]) -> None:
    print()
    for row in item["art"]:
        print("  " + row)
    print()
    print("  " + item["line"])
    print("  " + item["line_en"])
    print()
    print("  （没用。就是想看。）")
    print("  (" + item["en"] + " — useless. just wanted to look.)")
    print()


def main() -> None:
    if len(sys.argv) > 1:
        want = sys.argv[1]
        for item in STILL_LIVES:
            if want in (item["name"], item["en"]) or want in item["name"]:
                show(item)
                return
        print("没有这一件。/ No such one.")
        print("可选 / Available: " + ", ".join(i["name"] for i in STILL_LIVES))
        return
    show(random.choice(STILL_LIVES))


if __name__ == "__main__":
    main()
