# CherryTree `.ctb` Database Format

This document describes the internal structure of CherryTree's `.ctb` (SQLite) notebook format, based on reverse-engineering actual `.ctb` files and the [CherryTree source code](https://github.com/giuspen/cherrytree).

## Overview

A `.ctb` file is a standard **SQLite 3 database**. You can open it with any SQLite client:

```bash
sqlite3 mynotes.ctb ".tables"
```

CherryTree also supports `.ctd` (plain XML) and `.ctz`/`.ctx` (compressed archives of the same), but this document covers only the `.ctb` SQLite format.

## Tables

### `node`

The primary table. Each row is one note/page in the tree.

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | Unique node identifier (primary key) |
| `name` | TEXT | Display name of the node (shown in the tree sidebar) |
| `txt` | TEXT | Content — stored as **XML** (see [Content Format](#content-format) below) |
| `syntax` | TEXT | Syntax highlighting mode. `custom-colors` = rich text, `plain-text` = plain, or a language name (e.g., `python`) for code nodes |
| `tags` | TEXT | Comma-separated tags |
| `is_ro` | INTEGER | Read-only flag (0 or 1) |
| `is_richtxt` | INTEGER | 1 if rich text, 0 if plain/code |
| `has_codebox` | INTEGER | 1 if node contains embedded code boxes |
| `has_table` | INTEGER | 1 if node contains embedded tables |
| `has_image` | INTEGER | 1 if node contains embedded images or file attachments |
| `level` | INTEGER | Depth level in the tree (0 = root) |
| `ts_creation` | INTEGER | Unix timestamp — when the node was created |
| `ts_lastsave` | INTEGER | Unix timestamp — last modification |

### `children`

Defines the tree hierarchy and ordering.

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | The child node |
| `father_id` | INTEGER | The parent node (0 = top-level / root) |
| `sequence` | INTEGER | Sort order among siblings (1-based) |
| `master_id` | INTEGER | Used for node aliases/shortcuts (typically 0) |

To reconstruct the tree, start with `father_id = 0` (top-level nodes), then recursively query children by `father_id = <node_id>`, ordering by `sequence`.

### `codebox`

Embedded code blocks within rich-text nodes.

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | Parent node |
| `offset` | INTEGER | **Character offset** within the node's text content where this codebox is inserted |
| `justification` | TEXT | Alignment (`left`, `center`, `right`) |
| `txt` | TEXT | The actual code content (plain text, not XML) |
| `syntax` | TEXT | Language for syntax highlighting (e.g., `python`, `sh`, `sql`) |
| `width` | INTEGER | Display width |
| `height` | INTEGER | Display height |
| `is_width_pix` | INTEGER | Whether width is in pixels (1) or percentage (0) |
| `do_highl_bra` | INTEGER | Highlight matching brackets |
| `do_show_linenum` | INTEGER | Show line numbers |

### `grid`

Embedded tables within rich-text nodes.

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | Parent node |
| `offset` | INTEGER | Character offset for insertion point |
| `justification` | TEXT | Alignment |
| `txt` | TEXT | Table content as **XML** (see below) |
| `col_min` | INTEGER | Minimum column width |
| `col_max` | INTEGER | Maximum column width |

Grid XML format:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<table col_widths="0,0">
  <row>
    <cell>Header 1</cell>
    <cell>Header 2</cell>
  </row>
  <row>
    <cell>Data 1</cell>
    <cell>Data 2</cell>
  </row>
</table>
```

### `image`

Embedded images, anchors, and file attachments.

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | Parent node |
| `offset` | INTEGER | Character offset for insertion point |
| `justification` | TEXT | Alignment |
| `anchor` | TEXT | Named anchor (for internal linking within a node) — empty string if not an anchor |
| `png` | BLOB | Binary image data (PNG format) **or** raw file bytes for attachments |
| `filename` | TEXT | Original filename — empty for images, populated for file attachments |
| `link` | TEXT | Associated hyperlink (usually empty) |
| `time` | INTEGER | Timestamp |

**Important distinction:**
- If `filename` is empty → it's an **embedded image** (PNG data in `png` column)
- If `filename` is set → it's a **file attachment** (raw file bytes in `png` column despite the column name)
- If `anchor` is set → it's a **named anchor** for in-page linking

### `bookmark`

Bookmarked nodes (starred/favorited).

| Column | Type | Description |
|--------|------|-------------|
| `node_id` | INTEGER | Bookmarked node |
| `sequence` | INTEGER | Display order in bookmarks bar |

## Content Format

The `txt` column in the `node` table contains XML-formatted rich text:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<node>
  <rich_text>Plain text content here.</rich_text>
  <rich_text weight="heavy">This is bold text.</rich_text>
  <rich_text style="italic">This is italic.</rich_text>
  <rich_text link="webs https://example.com">clickable link</rich_text>
  <rich_text scale="h1">This is a heading</rich_text>
  <rich_text family="monospace">inline code</rich_text>
  <rich_text foreground="#ff0000">colored text</rich_text>
  <rich_text justification="left"></rich_text>
</node>
```

### `rich_text` Attributes

| Attribute | Values | Meaning |
|-----------|--------|---------|
| `weight` | `heavy` | Bold text |
| `style` | `italic` | Italic text |
| `strikethrough` | `true` | Strikethrough |
| `family` | `monospace` | Monospace / code font |
| `scale` | `h1`–`h6`, `small`, `sub`, `sup` | Text scale / heading level |
| `foreground` | `#rrggbb` | Text color |
| `background` | `#rrggbb` | Highlight color |
| `link` | See below | Hyperlink |
| `justification` | `left`, `center`, `right` | Text alignment |

### Link Format

The `link` attribute uses a prefix to indicate the link type:

| Prefix | Example | Meaning |
|--------|---------|---------|
| `webs ` | `webs https://example.com` | Web URL |
| `node ` | `node 42` | Internal link to node_id 42 |
| `file ` | `file /path/to/file` | Link to local file |
| `fold ` | `fold /path/to/folder` | Link to local folder |

## Character Offset System

CherryTree uses a **character offset** system to position embedded objects (codeboxes, tables, images) within the text flow. The offset represents the position in the **concatenated plain text** of all `<rich_text>` elements where the object should be inserted.

For example, if a node's text content is "Hello World" (11 characters) and an image has `offset=5`, the image appears between "Hello" and " World".

When converting, you must:
1. Parse all `<rich_text>` elements and track cumulative character positions
2. Query the `codebox`, `grid`, and `image` tables for the node
3. Insert each embedded object at its character offset position

This is the trickiest part of any CherryTree converter — many tools get this wrong and place images/codeboxes at the end of the document instead of inline.
