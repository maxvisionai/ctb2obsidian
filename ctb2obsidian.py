#!/usr/bin/env python3
"""
ctb2obsidian — CherryTree (.ctb) to Obsidian Vault Converter

Usage:
  python ctb2obsidian.py                          # Launch GUI
  python ctb2obsidian.py input.ctb output_dir     # CLI mode
  python ctb2obsidian.py input.ctb                # CLI, output = input dir / <basename>_vault
  python ctb2obsidian.py --help                   # Show help

Converts a CherryTree SQLite (.ctb) notebook into a structured Obsidian vault
with Markdown files, embedded images, code blocks, tables, and wikilinks.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import logging
import os
import re
import sqlite3
import sys
import textwrap
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

__version__ = "1.0.1"

LOG_FILENAME = "ctb2obsidian.log"

# ─── Logging Setup ───────────────────────────────────────────────────────────

def setup_logging(log_dir: Path | None = None) -> logging.Logger:
  """Configure file + console logging. Returns the root logger."""
  logger = logging.getLogger("ctb2obsidian")
  logger.setLevel(logging.DEBUG)
  logger.handlers.clear()

  fmt = logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
  )

  # Console handler (INFO+)
  ch = logging.StreamHandler(sys.stdout)
  ch.setLevel(logging.INFO)
  ch.setFormatter(fmt)
  logger.addHandler(ch)

  # File handler (DEBUG+) — written to output dir or cwd
  log_path = (log_dir or Path.cwd()) / LOG_FILENAME
  try:
    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.debug("Log file: %s", log_path)
  except OSError as exc:
    logger.warning("Could not create log file %s: %s", log_path, exc)

  return logger


# ─── Helpers ─────────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
  """Make a string safe for use as a file/folder name on Windows + POSIX."""
  name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
  name = re.sub(r"_+", "_", name)
  name = re.sub(r"\s+", " ", name)
  name = name.strip(" ._")
  if not name:
    name = "untitled"
  reserved = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
  }
  if name.upper() in reserved:
    name += "_"
  if len(name) > 100:
    name = name[:100].rstrip(" ._")
  return name


# ─── Core Converter ─────────────────────────────────────────────────────────

ATTACHMENTS_DIR = "attachments"


class ConversionStats:
  """Accumulates conversion statistics."""

  def __init__(self) -> None:
    self.nodes = 0
    self.images_saved = 0
    self.files_saved = 0
    self.codeboxes = 0
    self.tables = 0
    self.errors: list[str] = []

  def summary(self) -> str:
    lines = [
      f"  Nodes converted: {self.nodes}",
      f"  Images saved:    {self.images_saved}",
      f"  Files saved:     {self.files_saved}",
      f"  Codeboxes:       {self.codeboxes}",
      f"  Tables:          {self.tables}",
    ]
    if self.errors:
      lines.append(f"  Errors:          {len(self.errors)}")
    return "\n".join(lines)


class CTBConverter:
  """Converts a CherryTree .ctb SQLite database into an Obsidian vault."""

  def __init__(
    self,
    ctb_path: str | Path,
    output_dir: str | Path,
    *,
    progress_callback: Any | None = None,
  ) -> None:
    self.ctb_path = Path(ctb_path)
    self.output_dir = Path(output_dir)
    self.attachments_dir = self.output_dir / ATTACHMENTS_DIR
    self.progress_callback = progress_callback  # callable(current, total, message)

    self.log = logging.getLogger("ctb2obsidian")
    self.stats = ConversionStats()

    # Data stores — populated by load_data()
    self.conn: sqlite3.Connection | None = None
    self.nodes: dict[int, dict] = {}
    self.children: dict[int, list[tuple[int, int]]] = {}
    self.node_paths: dict[int, Path] = {}
    self.node_names: dict[int, str] = {}
    self.codeboxes: dict[int, list[dict]] = {}
    self.grids: dict[int, list[dict]] = {}
    self.images: dict[int, list[dict]] = {}

  # ── Validation ────────────────────────────────────────────────────────

  def validate(self) -> list[str]:
    """Pre-flight checks. Returns list of error strings (empty = OK)."""
    errors = []
    if not self.ctb_path.exists():
      errors.append(f"Input file not found: {self.ctb_path}")
    elif self.ctb_path.suffix.lower() != ".ctb":
      errors.append(f"Input file is not a .ctb file: {self.ctb_path}")
    else:
      try:
        conn = sqlite3.connect(str(self.ctb_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        required = {"node", "children"}
        missing = required - tables
        if missing:
          errors.append(
            f"Not a valid CherryTree DB — missing tables: {missing}"
          )
      except sqlite3.Error as exc:
        errors.append(f"Cannot open as SQLite database: {exc}")

    if self.output_dir.exists() and not self.output_dir.is_dir():
      errors.append(f"Output path exists but is not a directory: {self.output_dir}")

    return errors

  # ── Data Loading ──────────────────────────────────────────────────────

  def load_data(self) -> None:
    """Load all data from the CTB database into memory."""
    self.conn = sqlite3.connect(str(self.ctb_path))
    self.conn.row_factory = sqlite3.Row

    cur = self.conn.cursor()

    cur.execute("SELECT * FROM node")
    for row in cur.fetchall():
      d = dict(row)
      self.nodes[d["node_id"]] = d
      self.node_names[d["node_id"]] = d["name"]

    cur.execute(
      "SELECT node_id, father_id, sequence FROM children ORDER BY father_id, sequence"
    )
    for row in cur.fetchall():
      self.children.setdefault(row["father_id"], []).append(
        (row["node_id"], row["sequence"])
      )

    # Optional tables — may not exist in every CTB
    for table, store, order in [
      ("codebox", self.codeboxes, "node_id, offset"),
      ("grid", self.grids, "node_id, offset"),
    ]:
      try:
        cur.execute(f"SELECT * FROM {table} ORDER BY {order}")
        for row in cur.fetchall():
          store.setdefault(row["node_id"], []).append(dict(row))
      except sqlite3.OperationalError:
        self.log.debug("Table '%s' not found — skipping", table)

    try:
      cur.execute(
        "SELECT node_id, offset, justification, anchor, png, filename, link, time "
        "FROM image ORDER BY node_id, offset"
      )
      for row in cur.fetchall():
        self.images.setdefault(row["node_id"], []).append(dict(row))
    except sqlite3.OperationalError:
      self.log.debug("Table 'image' not found — skipping")

    total_cb = sum(len(v) for v in self.codeboxes.values())
    total_gr = sum(len(v) for v in self.grids.values())
    total_im = sum(len(v) for v in self.images.values())
    self.log.info(
      "Loaded %d nodes, %d codeboxes, %d tables, %d images",
      len(self.nodes), total_cb, total_gr, total_im,
    )

  # ── Hierarchy ─────────────────────────────────────────────────────────

  def build_paths(self) -> None:
    """Assign a filesystem path (relative to output_dir) to every node."""
    def walk(father_id: int, parent_path: Path) -> None:
      for node_id, _seq in self.children.get(father_id, []):
        safe = sanitize_filename(self.node_names.get(node_id, "untitled"))
        self.node_paths[node_id] = parent_path / safe
        walk(node_id, parent_path / safe)

    walk(0, Path(""))

  # ── Rich Text → Markdown ─────────────────────────────────────────────

  def parse_rich_text_xml(self, xml_text: str, node_id: int) -> str:
    """Parse CherryTree rich-text XML into Markdown."""
    if not xml_text:
      return ""

    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      try:
        root = ET.fromstring(f"<root>{xml_text}</root>")
      except ET.ParseError:
        self.log.warning(
          "Node %d: XML parse failed — returning stripped text", node_id
        )
        return re.sub(r"<[^>]+>", "", xml_text)

    # Collect text segments with character offsets
    segments: list[tuple[int, int, str, dict]] = []
    char_offset = 0
    for elem in root.iter("rich_text"):
      text = elem.text or ""
      if text:
        segments.append((char_offset, char_offset + len(text), text, dict(elem.attrib)))
        char_offset += len(text)

    # Collect embedded objects as (db offset, markdown)
    objects: list[tuple[int, str]] = []

    for cb in self.codeboxes.get(node_id, []):
      lang = cb.get("syntax", "") or ""
      if lang in ("plain-text", "custom-colors"):
        lang = ""
      objects.append((cb["offset"], f'\n\n```{lang}\n{cb.get("txt", "")}\n```\n\n'))
      self.stats.codeboxes += 1

    for grid in self.grids.get(node_id, []):
      objects.append((grid["offset"], self._grid_to_markdown(grid.get("txt", ""))))
      self.stats.tables += 1

    for img in self.images.get(node_id, []):
      objects.append((img["offset"], self._save_image(img, node_id)))

    # CherryTree's offsets are positions in the editor buffer, where every
    # embedded object occupies one character. The k-th object (in offset
    # order) therefore sits at text position offset - k. Several objects can
    # share a text position, so keep them as an ordered list.
    objects.sort(key=lambda o: o[0])
    embeds: list[tuple[int, str]] = [
      (offset - k, md) for k, (offset, md) in enumerate(objects)
    ]

    # Merge text and embeds by text position
    parts: list[str] = []
    ei = 0

    for seg_start, seg_end, text, attribs in segments:
      while ei < len(embeds) and embeds[ei][0] <= seg_start:
        parts.append(embeds[ei][1])
        ei += 1
      while ei < len(embeds) and embeds[ei][0] < seg_end:
        eo = embeds[ei][0]
        split_pos = eo - seg_start
        before = text[:split_pos]
        if before:
          parts.append(self._format_text(before, attribs))
        parts.append(embeds[ei][1])
        text = text[split_pos:]
        seg_start = eo
        ei += 1
      if text:
        parts.append(self._format_text(text, attribs))

    while ei < len(embeds):
      parts.append(embeds[ei][1])
      ei += 1

    md = "".join(parts)
    md = re.sub(r"\n{4,}", "\n\n\n", md)
    return md

  def _format_text(self, text: str, attribs: dict) -> str:
    """Apply Markdown formatting based on rich_text XML attributes."""
    if not text or not text.strip():
      return text

    # Headings
    scale = attribs.get("scale", "")
    heading_map = {"h1": "# ", "h2": "## ", "h3": "### ",
             "h4": "#### ", "h5": "##### ", "h6": "###### "}
    if scale in heading_map:
      lines = text.split("\n")
      out = []
      for line in lines:
        s = line.strip()
        out.append(f"\n\n{heading_map[scale]}{s}\n" if s else "")
      return "\n".join(out)

    # Links
    link = attribs.get("link", "")
    if link:
      if link.startswith("webs "):
        url = link[5:]
        display = text.strip()
        return f"[{display}]({url})" if display != url else f"<{url}>"
      if link.startswith("node "):
        try:
          tid = int(link[5:].strip())
          return f"[[{self.node_names.get(tid, str(tid))}]]"
        except ValueError:
          pass
      if link.startswith(("file ", "fold ")):
        # CherryTree stores local file/folder paths base64-encoded
        try:
          target = base64.b64decode(link[5:], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
          target = link[5:]
        return f"[{text.strip()}](<file://{target}>)"
      return f"[{text.strip()}]({link})"

    result = text

    # Bold
    if attribs.get("weight") == "heavy":
      result = self._wrap_lines(result, "**")

    # Italic
    if attribs.get("style") == "italic":
      result = self._wrap_lines(result, "*")

    # Strikethrough
    if attribs.get("strikethrough") == "true":
      result = self._wrap_lines(result, "~~")

    # Monospace
    if attribs.get("family") == "monospace":
      stripped = result.strip()
      if "\n" in stripped:
        result = f"\n```\n{stripped}\n```\n"
      elif stripped:
        result = f"`{stripped}`"

    return result

  @staticmethod
  def _wrap_lines(text: str, marker: str) -> str:
    """Wrap non-empty lines with a Markdown marker (**, *, ~~)."""
    lines = text.split("\n")
    out = []
    for line in lines:
      s = line.strip()
      out.append(f"{marker}{s}{marker}" if s else line)
    return "\n".join(out)

  def _grid_to_markdown(self, xml_text: str) -> str:
    """Convert CherryTree table XML to a Markdown table."""
    if not xml_text:
      return ""
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      try:
        root = ET.fromstring(f"<root>{xml_text}</root>")
      except ET.ParseError:
        return f"\n\n```\n{xml_text}\n```\n\n"

    rows: list[list[str]] = []
    for row_elem in root.iter("row"):
      cells = []
      for cell_elem in row_elem.iter("cell"):
        cells.append(
          (cell_elem.text or "").replace("\n", " ").replace("|", "\\|").strip()
        )
      if cells:
        rows.append(cells)

    if not rows:
      return ""

    # CherryTree stores the header row last
    rows.insert(0, rows.pop())

    max_cols = max(len(r) for r in rows)
    for r in rows:
      r.extend([""] * (max_cols - len(r)))

    lines = ["\n"]
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in rows[1:]:
      lines.append("| " + " | ".join(row) + " |")
    lines.append("\n")
    return "\n".join(lines)

  def _save_image(self, img_data: dict, node_id: int) -> str:
    """Save an embedded image/file and return Markdown reference."""
    png_data = img_data.get("png")
    if not png_data:
      return ""

    filename = img_data.get("filename", "") or ""

    if filename:
      orig_ext = Path(filename).suffix
      safe_base = sanitize_filename(Path(filename).stem)
      safe_fn = safe_base + orig_ext if orig_ext else safe_base
      save_path = self.attachments_dir / f"node{node_id}" / safe_fn
      save_path.parent.mkdir(parents=True, exist_ok=True)
      try:
        save_path.write_bytes(png_data)
        self.stats.files_saved += 1
        self.log.debug("Saved attachment: %s", save_path)
      except OSError as exc:
        self.log.error("Failed to save attachment %s: %s", save_path, exc)
        self.stats.errors.append(f"Attachment {save_path}: {exc}")
        return f"\n\n📎 {filename} *(save failed)*\n\n"
      rel = f"{ATTACHMENTS_DIR}/node{node_id}/{safe_fn}"
      return f"\n\n📎 [{filename}]({rel})\n\n"

    img_hash = hashlib.md5(png_data).hexdigest()[:10]
    img_name = f"img_{node_id}_{img_data['offset']}_{img_hash}.png"
    save_path = self.attachments_dir / f"node{node_id}" / img_name
    save_path.parent.mkdir(parents=True, exist_ok=True)
    try:
      save_path.write_bytes(png_data)
      self.stats.images_saved += 1
      self.log.debug("Saved image: %s", save_path)
    except OSError as exc:
      self.log.error("Failed to save image %s: %s", save_path, exc)
      self.stats.errors.append(f"Image {save_path}: {exc}")
      return "\n\n*(image save failed)*\n\n"
    rel = f"{ATTACHMENTS_DIR}/node{node_id}/{img_name}"
    return f"\n\n![]({rel})\n\n"

  # ── Node → Markdown ──────────────────────────────────────────────────

  def convert_node(self, node_id: int) -> str:
    """Convert a single CherryTree node to Markdown."""
    node = self.nodes[node_id]
    name = node["name"]
    content = self.parse_rich_text_xml(node.get("txt", "") or "", node_id)

    ts_create = node.get("ts_creation", 0)
    ts_save = node.get("ts_lastsave", 0)
    tags = node.get("tags", "") or ""

    parts = ["---"]
    if ts_create:
      parts.append(
        f"created: {datetime.fromtimestamp(ts_create).strftime('%Y-%m-%d %H:%M')}"
      )
    if ts_save:
      parts.append(
        f"modified: {datetime.fromtimestamp(ts_save).strftime('%Y-%m-%d %H:%M')}"
      )
    if tags:
      tag_list = [t.strip() for t in tags.split(",") if t.strip()]
      if tag_list:
        parts.append(f"tags: [{', '.join(tag_list)}]")
    parts.append(f"cherrytree_id: {node_id}")
    parts.extend(["---", "", f"# {name}", "", content.strip(), ""])

    child_nodes = self.children.get(node_id, [])
    if child_nodes:
      parts.extend(["", "## Child Notes", ""])
      for cid, _seq in child_nodes:
        cname = self.node_names.get(cid, f"node_{cid}")
        parts.append(f"- [[{cname}]]")
      parts.append("")

    return "\n".join(parts)

  # ── Write Vault ──────────────────────────────────────────────────────

  def write_vault(self) -> None:
    """Write all nodes as Markdown files in the Obsidian vault."""
    self.attachments_dir.mkdir(parents=True, exist_ok=True)
    used_paths: dict[str, int] = {}
    total = len(self.node_paths)

    for idx, (node_id, rel_path) in enumerate(self.node_paths.items()):
      try:
        node = self.nodes[node_id]
        has_children = bool(self.children.get(node_id))

        if has_children:
          folder = self.output_dir / rel_path
          folder.mkdir(parents=True, exist_ok=True)
          file_path = folder / f"{sanitize_filename(node['name'])}.md"
        else:
          parent = (self.output_dir / rel_path).parent
          parent.mkdir(parents=True, exist_ok=True)
          file_path = (self.output_dir / rel_path).with_suffix(".md")

        # Collision avoidance
        orig = file_path
        counter = 1
        while str(file_path) in used_paths:
          file_path = orig.with_stem(f"{orig.stem}_{counter}")
          counter += 1
        used_paths[str(file_path)] = node_id

        md = self.convert_node(node_id)
        file_path.write_text(md, encoding="utf-8")
        self.stats.nodes += 1
        self.log.debug("Wrote: %s", file_path)

        if self.progress_callback and total > 0:
          self.progress_callback(idx + 1, total, node["name"])

      except Exception as exc:
        msg = f"Node {node_id} ({self.node_names.get(node_id, '?')}): {exc}"
        self.log.error(msg)
        self.stats.errors.append(msg)

    # Obsidian config
    obsidian_dir = self.output_dir / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    app_cfg = obsidian_dir / "app.json"
    if not app_cfg.exists():
      app_cfg.write_text(
        '{\n  "attachmentFolderPath": "attachments"\n}\n', encoding="utf-8"
      )

  # ── Public API ────────────────────────────────────────────────────────

  def run(self) -> ConversionStats:
    """Execute the full conversion pipeline. Returns stats."""
    self.log.info("ctb2obsidian v%s", __version__)
    self.log.info("Input:  %s", self.ctb_path)
    self.log.info("Output: %s", self.output_dir)

    errors = self.validate()
    if errors:
      for e in errors:
        self.log.error("Validation: %s", e)
      raise ValueError("\n".join(errors))

    self.load_data()
    self.build_paths()
    self.write_vault()

    self.log.info("Conversion complete.")
    self.log.info("\n%s", self.stats.summary())
    if self.stats.errors:
      for e in self.stats.errors[:20]:
        self.log.warning("  ! %s", e)

    if self.conn:
      self.conn.close()

    return self.stats


# ─── GUI ─────────────────────────────────────────────────────────────────────

def run_gui() -> None:
  """Launch the dark-mode tkinter GUI."""
  import tkinter as tk
  from tkinter import filedialog, messagebox, ttk
  import ctypes
  import threading

  # ── Dark theme colors ─────────────────────────────────────────────
  BG = "#1e1e2e"
  BG_LIGHT = "#2a2a3c"
  BG_INPUT = "#313244"
  FG = "#cdd6f4"
  FG_DIM = "#6c7086"
  ACCENT = "#89b4fa"
  ACCENT_HOVER = "#74c7ec"
  SUCCESS = "#a6e3a1"
  ERROR = "#f38ba8"
  BORDER = "#45475a"

  root = tk.Tk()
  root.title("ctb2obsidian")
  root.geometry("680x560")
  root.minsize(580, 500)
  root.configure(bg=BG)
  root.resizable(True, True)

  # ── Dark title bar (Windows 10/11) ────────────────────────────────
  try:
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
      hwnd,
      DWMWA_USE_IMMERSIVE_DARK_MODE,
      ctypes.byref(ctypes.c_int(1)),
      ctypes.sizeof(ctypes.c_int),
    )
  except Exception:
    pass  # Non-Windows or older build — title bar stays light

  # ── Configure ttk styles ──────────────────────────────────────────
  style = ttk.Style(root)
  style.theme_use("clam")

  style.configure(".", background=BG, foreground=FG, fieldbackground=BG_INPUT,
           bordercolor=BORDER, troughcolor=BG_LIGHT, arrowcolor=FG)
  style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
  style.configure("Title.TLabel", background=BG, foreground=FG,
           font=("Segoe UI", 16, "bold"))
  style.configure("Subtitle.TLabel", background=BG, foreground=FG_DIM,
           font=("Segoe UI", 9))
  style.configure("Status.TLabel", background=BG, foreground=FG_DIM,
           font=("Segoe UI", 9))
  style.configure("TButton", background=BG_LIGHT, foreground=FG,
           font=("Segoe UI", 10), padding=(12, 6), borderwidth=1,
           relief="flat")
  style.map("TButton",
        background=[("active", BG_INPUT), ("disabled", BG)],
        foreground=[("disabled", FG_DIM)])
  style.configure("Accent.TButton", background=ACCENT, foreground="#1e1e2e",
           font=("Segoe UI", 11, "bold"), padding=(16, 8))
  style.map("Accent.TButton",
        background=[("active", ACCENT_HOVER), ("disabled", BG_LIGHT)],
        foreground=[("disabled", FG_DIM)])
  style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
           insertcolor=FG, borderwidth=1, padding=6)
  style.configure("Horizontal.TProgressbar", troughcolor=BG_LIGHT,
           background=ACCENT, bordercolor=BORDER, lightcolor=ACCENT,
           darkcolor=ACCENT)

  # ── Widgets ───────────────────────────────────────────────────────
  main = tk.Frame(root, bg=BG, padx=24, pady=16)
  main.pack(fill="both", expand=True)

  ttk.Label(main, text="ctb2obsidian", style="Title.TLabel").pack(anchor="w")
  ttk.Label(main, text="CherryTree → Obsidian vault converter",
        style="Subtitle.TLabel").pack(anchor="w", pady=(0, 16))

  # Input file
  input_frame = tk.Frame(main, bg=BG)
  input_frame.pack(fill="x", pady=(0, 8))
  ttk.Label(input_frame, text="CherryTree file (.ctb):").pack(anchor="w")
  input_row = tk.Frame(input_frame, bg=BG)
  input_row.pack(fill="x", pady=(4, 0))

  input_var = tk.StringVar()
  input_entry = tk.Entry(input_row, textvariable=input_var, bg=BG_INPUT, fg=FG,
               insertbackground=FG, relief="flat", font=("Segoe UI", 10),
               bd=0, highlightthickness=1, highlightcolor=ACCENT,
               highlightbackground=BORDER)
  input_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

  def browse_input():
    path = filedialog.askopenfilename(
      title="Select CherryTree file",
      filetypes=[("CherryTree DB", "*.ctb"), ("All files", "*.*")],
    )
    if path:
      input_var.set(path)
      if not output_var.get():
        out = Path(path).parent / (Path(path).stem + "_vault")
        output_var.set(str(out))

  ttk.Button(input_row, text="Browse…", command=browse_input).pack(side="right")

  # Output directory
  output_frame = tk.Frame(main, bg=BG)
  output_frame.pack(fill="x", pady=(0, 16))
  ttk.Label(output_frame, text="Output vault directory:").pack(anchor="w")
  output_row = tk.Frame(output_frame, bg=BG)
  output_row.pack(fill="x", pady=(4, 0))

  output_var = tk.StringVar()
  output_entry = tk.Entry(output_row, textvariable=output_var, bg=BG_INPUT, fg=FG,
              insertbackground=FG, relief="flat", font=("Segoe UI", 10),
              bd=0, highlightthickness=1, highlightcolor=ACCENT,
              highlightbackground=BORDER)
  output_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

  def browse_output():
    path = filedialog.askdirectory(title="Select output directory")
    if path:
      output_var.set(path)

  ttk.Button(output_row, text="Browse…", command=browse_output).pack(side="right")

  # Progress
  progress_var = tk.DoubleVar(value=0)
  progress_bar = ttk.Progressbar(main, variable=progress_var, maximum=100,
                  style="Horizontal.TProgressbar")
  progress_bar.pack(fill="x", pady=(0, 4))

  status_var = tk.StringVar(value="Ready")
  status_label = ttk.Label(main, textvariable=status_var, style="Status.TLabel")
  status_label.pack(anchor="w", pady=(0, 8))

  # Log area
  log_frame = tk.Frame(main, bg=BORDER, bd=1, relief="flat")
  log_frame.pack(fill="both", expand=True, pady=(0, 12))
  log_text = tk.Text(log_frame, bg=BG_LIGHT, fg=FG, font=("Cascadia Code", 9),
             relief="flat", bd=0, padx=8, pady=8, wrap="word",
             state="disabled", insertbackground=FG,
             selectbackground=ACCENT, selectforeground="#1e1e2e")
  log_scroll = tk.Scrollbar(log_frame, command=log_text.yview,
                 bg=BG_LIGHT, troughcolor=BG_LIGHT,
                 activebackground=BG_INPUT)
  log_text.configure(yscrollcommand=log_scroll.set)
  log_scroll.pack(side="right", fill="y")
  log_text.pack(fill="both", expand=True)

  # Tag for errors
  log_text.tag_configure("error", foreground=ERROR)
  log_text.tag_configure("success", foreground=SUCCESS)
  log_text.tag_configure("accent", foreground=ACCENT)

  def log_append(msg: str, tag: str = "") -> None:
    log_text.configure(state="normal")
    log_text.insert("end", msg + "\n", tag)
    log_text.see("end")
    log_text.configure(state="disabled")

  # Convert button
  button_frame = tk.Frame(main, bg=BG)
  button_frame.pack(fill="x")

  converting = threading.Event()

  def on_convert():
    ctb = input_var.get().strip()
    out = output_var.get().strip()
    if not ctb:
      messagebox.showwarning("Missing input", "Please select a .ctb file.")
      return
    if not out:
      messagebox.showwarning("Missing output", "Please select an output directory.")
      return

    convert_btn.configure(state="disabled")
    progress_var.set(0)
    log_text.configure(state="normal")
    log_text.delete("1.0", "end")
    log_text.configure(state="disabled")
    converting.set()

    def progress_cb(current: int, total: int, name: str) -> None:
      pct = current / total * 100 if total else 0
      root.after(0, lambda: progress_var.set(pct))
      root.after(0, lambda: status_var.set(f"Converting: {name} ({current}/{total})"))

    def do_convert():
      try:
        logger = setup_logging(Path(out))
        log_append(f"Input:  {ctb}", "accent")
        log_append(f"Output: {out}", "accent")
        log_append("")

        converter = CTBConverter(ctb, out, progress_callback=progress_cb)
        errors = converter.validate()
        if errors:
          for e in errors:
            root.after(0, lambda e=e: log_append(f"ERROR: {e}", "error"))
          root.after(0, lambda: status_var.set("Validation failed"))
          root.after(0, lambda: convert_btn.configure(state="normal"))
          return

        stats = converter.run()

        root.after(0, lambda: progress_var.set(100))
        root.after(0, lambda: log_append(""))
        root.after(0, lambda: log_append("═" * 50, "success"))
        root.after(0, lambda: log_append("  CONVERSION COMPLETE", "success"))
        root.after(0, lambda: log_append("═" * 50, "success"))
        root.after(0, lambda: log_append(stats.summary()))
        if stats.errors:
          for e in stats.errors[:20]:
            root.after(0, lambda e=e: log_append(f"  ! {e}", "error"))
        root.after(0, lambda: log_append(
          f"\nLog file: {Path(out) / LOG_FILENAME}", "accent"
        ))
        root.after(0, lambda: status_var.set(
          f"Done — {stats.nodes} notes converted"
        ))
      except Exception as exc:
        root.after(0, lambda: log_append(f"\nFATAL: {exc}", "error"))
        root.after(0, lambda: log_append(traceback.format_exc(), "error"))
        root.after(0, lambda: status_var.set("Conversion failed"))
      finally:
        root.after(0, lambda: convert_btn.configure(state="normal"))
        converting.clear()

    threading.Thread(target=do_convert, daemon=True).start()

  convert_btn = ttk.Button(button_frame, text="Convert", style="Accent.TButton",
                command=on_convert)
  convert_btn.pack(side="right")

  version_label = ttk.Label(button_frame, text=f"v{__version__}",
                 style="Subtitle.TLabel")
  version_label.pack(side="left")

  # Center window on screen
  root.update_idletasks()
  w, h = root.winfo_width(), root.winfo_height()
  x = (root.winfo_screenwidth() - w) // 2
  y = (root.winfo_screenheight() - h) // 2
  root.geometry(f"+{x}+{y}")

  root.mainloop()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def run_cli(args: list[str]) -> int:
  """Run in CLI mode. Returns exit code."""
  parser = argparse.ArgumentParser(
    prog="ctb2obsidian",
    description="Convert a CherryTree .ctb notebook to an Obsidian vault.",
  )
  parser.add_argument("input", help="Path to the CherryTree .ctb file")
  parser.add_argument(
    "output",
    nargs="?",
    default=None,
    help="Output directory for the Obsidian vault (default: <input_dir>/<basename>_vault)",
  )
  parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

  parsed = parser.parse_args(args)

  ctb_path = Path(parsed.input)
  if parsed.output:
    output_dir = Path(parsed.output)
  else:
    output_dir = ctb_path.parent / (ctb_path.stem + "_vault")

  logger = setup_logging(output_dir if output_dir.exists() else None)

  try:
    converter = CTBConverter(ctb_path, output_dir)
    stats = converter.run()
    if stats.errors:
      return 1
    return 0
  except Exception as exc:
    logger.error("Fatal: %s", exc)
    logger.debug(traceback.format_exc())
    return 2


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main() -> None:
  """Dispatch to GUI (no args) or CLI (with args)."""
  # If run with positional arguments → CLI mode
  # Skip flags like --help which argparse handles
  positional_args = [a for a in sys.argv[1:] if not a.startswith("-")]
  if positional_args or "--help" in sys.argv or "-h" in sys.argv or "--version" in sys.argv or "-v" in sys.argv:
    sys.exit(run_cli(sys.argv[1:]))
  else:
    run_gui()


if __name__ == "__main__":
  main()
