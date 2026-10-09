# ctb2obsidian

**CherryTree (.ctb) → Obsidian Vault Converter**

A Python tool that converts CherryTree SQLite notebooks into fully structured Obsidian-compatible Markdown vaults — with images, code blocks, tables, wikilinks, and folder hierarchy preserved.

> [!WARNING]
> **Author's note:** Despite having tried Obsidian numerous times, I find it genuinely awful. You cannot sort folders without prefixing names with numbers or maintaining some janky index file or installing community plugins just to get basic tree ordering — something CherryTree handles natively with drag-and-drop. The fact that a "knowledge management" tool ships without deterministic note ordering in the sidebar is bewildering. Holy trash.
>
> This converter exists because Obsidian is what people keep recommending, so here's a bridge. If you're converting *to* Obsidian, you've been warned. Don't do it! :)

---

## Features

- **Full hierarchy** → Folder structure mirrors CherryTree's tree
- **Rich text** → Markdown (bold, italic, strikethrough, monospace, headings h1–h6)
- **Links** → `[text](url)` for web, `[[note name]]` for internal node links, `file://` for local files and folders
- **Codeboxes** → Fenced code blocks with syntax language (```python, ```sh, etc.)
- **Tables** → Proper Markdown tables, header row on top
- **Embedded images** → Saved as PNGs in `attachments/` with `![]()` references, placed exactly where they sat in the note
- **File attachments** → Saved with original filenames
- **YAML frontmatter** → `created`, `modified`, `tags`, `cherrytree_id`
- **Child note links** → Parent notes list children as `[[wikilinks]]`
- **Dark-mode GUI** — or headless CLI, your choice
- **Detailed logging** → Every action written to `ctb2obsidian.log`

## Requirements

- Python 3.10+ (uses only the standard library — no pip installs needed)
- `tkinter` (included with most Python installs; needed for GUI mode only)

## Usage

### GUI Mode (no arguments)

```
python ctb2obsidian.py
```

Launches a dark-mode GUI with file pickers, progress bar, and live log output. The title bar is also dark on Windows 10/11.

### CLI Mode

```bash
# Specify input and output
python ctb2obsidian.py mynotes.ctb /path/to/vault

# Output defaults to <input_dir>/<basename>_vault
python ctb2obsidian.py mynotes.ctb

# Help
python ctb2obsidian.py --help
```

### Example

Converting a 27 MB CherryTree notebook with 689 nodes:

```
$ python ctb2obsidian.py notes-2026.ctb C:\notes

2026-02-06 10:24:29 [INFO   ] ctb2obsidian v1.0.0
2026-02-06 10:24:29 [INFO   ] Input:  C:\Users\user\Documents\notes-2026.ctb
2026-02-06 10:24:29 [INFO   ] Output: C:\notes
2026-02-06 10:24:29 [INFO   ] Loaded 689 nodes, 82 codeboxes, 22 tables, 178 images
2026-02-06 10:24:30 [INFO   ] Conversion complete.
2026-02-06 10:24:30 [INFO   ]
  Nodes converted: 689
  Images saved:    177
  Files saved:     1
  Codeboxes:       82
  Tables:          22
```

Output vault structure:

```
C:\notes\
├── .obsidian/
│   └── app.json
├── attachments/
│   ├── node51/
│   │   └── img_51_74_a1b2c3d4e5.png
│   ├── node242/
│   │   ├── img_242_116_f6g7h8i9j0.png
│   │   └── modem_mischief_transcript.txt
│   └── ...
├── TODO_LIFE ORGANIZATION/
│   ├── TODO_LIFE ORGANIZATION.md    ← parent node (has child links)
│   ├── TODO/
│   │   └── ...
│   ├── health/
│   │   └── ...
│   └── ...
├── AI/
│   ├── AI.md
│   ├── prompts/
│   └── ...
├── PROCEDURES/
│   ├── LINUX ADMIN/
│   ├── SECURITY/
│   └── ...
└── ctb2obsidian.log
```

Each Markdown file includes YAML frontmatter:

```yaml
---
created: 2022-01-12 00:58
modified: 2026-01-26 06:51
cherrytree_id: 2
---

# TODO/LIFE ORGANIZATION

(converted content here...)

## Child Notes

- [[TODO]]
- [[health]]
- [[MONTHLY FINANCIAL]]
```

## How It Works

1. Opens the `.ctb` file as a read-only SQLite database
2. Loads all nodes, codeboxes, tables, and images into memory
3. Builds a folder hierarchy from the `children` table
4. For each node, parses the rich-text XML and converts formatting to Markdown
5. Embeds (images, codeboxes, tables) are inserted at their exact positions in the text. CherryTree counts every earlier embed as one character, so the k-th embed goes at `offset − k` — see [CTB_FORMAT.md](CTB_FORMAT.md#character-offset-system)
6. Writes `.md` files and saves image/file attachments
7. Creates `.obsidian/app.json` so the folder is recognized as a vault

**Your original `.ctb` file is never modified.** The database is opened in SQLite's read-only mode, so a write is impossible, not just avoided.

## Limitations

- **CherryTree XML format only** — `.ctb` (SQLite) files are supported. `.ctd` (plain XML) files are not currently supported, though adding support would be straightforward.
- **Rich text colors** are not preserved (Markdown has no native color support). CherryTree's `foreground`/`background` attributes are silently dropped.
- **Node ordering in Obsidian** — CherryTree preserves explicit ordering via sequence numbers. Obsidian... does not believe in ordering things. Godspeed.
- **Nested formatting** (e.g., bold + italic on the same span) produces valid but potentially ugly Markdown like `***text***`.

## Changelog

### 1.0.2

- The `.ctb` is now opened in SQLite read-only mode (`?mode=ro`), so the converter cannot write to it under any circumstances.

### 1.0.1

- **Fixed: embeds in the wrong place.** Images, code blocks and tables after the first one in a note drifted further right with each embed, and ones near the end fell off the end of the note entirely. CherryTree counts each embed as one character in its offsets; the converter now accounts for that. On an 843-node notebook this moved 36 of 250 images to their correct spot.
- **Fixed: table headers at the bottom.** CherryTree stores a table's header row last; it's now moved to the top (9 of 22 tables in the same notebook were affected).
- **Fixed: local file and folder links.** CherryTree base64-encodes these paths; they were written out encoded and unusable. They now become `file://` links.
- `CTB_FORMAT.md` corrected on all three points.

### 1.0.0

- Initial release.

## See Also

- [CTB_FORMAT.md](CTB_FORMAT.md) — Detailed documentation of the CherryTree `.ctb` database schema
- [OBSIDIAN_FORMAT.md](OBSIDIAN_FORMAT.md) — What Obsidian expects in a vault

## License

MIT
