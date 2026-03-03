#!/usr/bin/env python3
"""
Generate a small terminal-style GIF for the README.

No external recording tools required. This renders the stdout of:
  python3 examples/full_task_lifecycle.py --task_id ... --apply_fixes

Dependencies (local only):
  pip install pillow
"""

from __future__ import annotations

import argparse
import os
import subprocess
import textwrap
from dataclasses import dataclass
from typing import List, Sequence, Tuple


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        return Image, ImageDraw, ImageFont
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "Missing dependency: Pillow.\n"
            "Install with:\n"
            "  python3 -m pip install pillow\n"
            f"\nOriginal error: {e}\n"
        )


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run(cmd: Sequence[str], cwd: str) -> str:
    proc = subprocess.run(
        list(cmd),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.stdout


def _load_font(ImageFont, size: int):
    """Load a monospace TrueType font, falling back across platforms.

    Lookup order: macOS system fonts → Linux common paths → Windows paths.
    If no TrueType font is found, falls back to Pillow's built-in bitmap font
    (tiny but functional — the GIF will still render correctly).
    """
    candidates = [
        # macOS
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Monaco.ttf",
        # Linux (common mono fonts)
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
        # Windows
        "C:/Windows/Fonts/consola.ttf",   # Consolas
        "C:/Windows/Fonts/cour.ttf",      # Courier New
        "C:/Windows/Fonts/lucon.ttf",     # Lucida Console
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


@dataclass(frozen=True)
class RenderConfig:
    width: int = 1200
    height: int = 720
    padding: int = 22
    font_size: int = 18
    max_cols: int = 96
    max_lines: int = 26
    frame_ms: int = 110
    end_hold_ms: int = 1400
    bg: Tuple[int, int, int] = (13, 17, 23)
    fg: Tuple[int, int, int] = (230, 237, 243)
    dim: Tuple[int, int, int] = (148, 163, 184)
    accent: Tuple[int, int, int] = (56, 189, 248)


def _wrap_lines(raw: str, max_cols: int) -> List[str]:
    out: List[str] = []
    for line in raw.splitlines():
        if not line.strip():
            out.append("")
            continue
        wrapped = textwrap.wrap(line, width=max_cols, replace_whitespace=False, drop_whitespace=False)
        out.extend(wrapped if wrapped else [""])
    return out


def _render_frames(Image, ImageDraw, font, cfg: RenderConfig, lines: List[str]) -> Tuple[list, List[int]]:
    """Render incremental frames (like terminal scroll).

    Subsampling thresholds keep the GIF under ~200 frames to avoid
    bloating file size while staying within the 60-second constraint:
      - <=220 lines: step=1 → every line is a frame (up to ~220 frames)
      - 221-380 lines: step=2 → every other line (~110-190 frames)
      - >380 lines: step=3 → every third line (~127+ frames)
    At 110ms per frame, 200 frames = 22s, well under the 60s budget.
    """
    frames: list = []
    durations: List[int] = []

    # Subsample when output is long to cap frame count and GIF size.
    # Thresholds chosen so frame_count stays <=~220 (see docstring).
    step = 1
    if len(lines) > 220:
        step = 2
    if len(lines) > 380:
        step = 3

    lh = int(cfg.font_size * 1.35)
    header = "Governor — guard loop (demo)"

    def draw_frame(window: List[str]):
        img = Image.new("RGB", (cfg.width, cfg.height), cfg.bg)
        d = ImageDraw.Draw(img)
        d.text((cfg.padding, cfg.padding), header, font=font, fill=cfg.accent)
        d.text((cfg.padding, cfg.padding + lh), "↓ stdout", font=font, fill=cfg.dim)

        top = cfg.padding + int(lh * 2.4)
        y = top
        for text_line in window:
            d.text((cfg.padding, y), text_line, font=font, fill=cfg.fg)
            y += lh
        return img

    for i in range(1, len(lines) + 1, step):
        window = lines[max(0, i - cfg.max_lines):i]
        frames.append(draw_frame(window))
        durations.append(cfg.frame_ms)

    if frames:
        durations[-1] = cfg.end_hold_ms
    return frames, durations


def main() -> int:
    Image, ImageDraw, ImageFont = _require_pillow()

    parser = argparse.ArgumentParser(description="Render README demo GIF from terminal output.")
    parser.add_argument("--task_id", required=True, help="Task ID to run the demo against (Neo4j must be configured).")
    parser.add_argument("--out", default="docs/assets/governor_lifecycle_demo.gif", help="Output GIF path (repo-relative).")
    parser.add_argument("--apply_fixes", action="store_true", help="Apply fixes during demo (writes to Neo4j).")
    args = parser.parse_args()

    repo_root = _repo_root()
    out_path = os.path.join(repo_root, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    cmd = ["python3", "examples/full_task_lifecycle.py", "--task_id", args.task_id]
    if args.apply_fixes:
        cmd.append("--apply_fixes")

    stdout = _run(cmd, cwd=repo_root)

    cfg = RenderConfig()
    font = _load_font(ImageFont, cfg.font_size)
    lines = _wrap_lines(stdout, cfg.max_cols)
    frames, durations = _render_frames(Image, ImageDraw, font, cfg, lines)
    if not frames:
        raise SystemExit("No output captured; refusing to write empty GIF.")

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Wrote: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

