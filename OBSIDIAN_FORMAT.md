# What Obsidian Expects in a Vault

This document describes the file/folder conventions Obsidian uses to recognize and render a vault.

## Minimum Viable Vault

A folder becomes an Obsidian vault when it contains:

```
my-vault/
├── .obsidian/          ← required: settings directory
│   └── app.json        ← optional but recommended
└── *.md                ← your notes
```

That's it. Drop `.md` files in a folder, add a `.obsidian/` directory, and Obsidian will open it as a vault.

## Folder Structure

- **Folders** → Appear as collapsible groups in the sidebar
- **`.md` files** → Appear as notes
- **Non-`.md` files** → Treated as attachments (images, PDFs, etc.)
- **Nesting** → Unlimited depth, but deep nesting gets unwieldy

### ⚠️ Ordering (or Lack Thereof)

**Obsidian does not support explicit note/folder ordering.**

The sidebar sorts alphabetically by default. Your options for controlling order:

1. **Prefix with numbers** — `01 First Topic`, `02 Second Topic` (ugly but works)
2. **Community plugins** — "Bartender" or "Custom Sort" plugins exist but are fragile
3. **Accept chaos** — Just use search and links instead of browsing the tree

If you're coming from CherryTree (which has drag-and-drop ordering via `sequence` numbers in the database), this is... a downgrade. CherryTree stores explicit ordering. Obsidian refuses to.

## File Format

### Markdown Files

Standard CommonMark / GitHub-Flavored Markdown with extensions:

```markdown
---
created: 2024-01-15 10:30
modified: 2024-06-20 14:22
tags: [project, active]
---

# Note Title

Regular markdown content.

## Wikilinks

Link to another note: [[Other Note Name]]
Link with alias: [[Other Note Name|display text]]
Embed an image: ![[image.png]]
Embed a note: ![[Other Note]]

## Standard Markdown Links

Also supported: [display text](Other%20Note%20Name.md)
Images: ![alt text](attachments/image.png)
```

### YAML Frontmatter

The `---` delimited block at the top is optional but widely used:

| Field | Type | Notes |
|-------|------|-------|
| `created` | string/date | Creation timestamp |
| `modified` | string/date | Last modified timestamp |
| `tags` | list | `[tag1, tag2]` or `tags:\n  - tag1\n  - tag2` |
| `aliases` | list | Alternative names for the note (used in search/linking) |
| Any custom key | any | Obsidian ignores unknown keys; plugins can use them |

### Wikilinks vs Standard Links

Obsidian supports both:

| Style | Syntax | Notes |
|-------|--------|-------|
| Wikilink | `[[Note Name]]` | Obsidian-native, auto-resolves by filename |
| Standard | `[text](path/to/note.md)` | CommonMark-compatible, portable |

Wikilinks match by **filename only** (not path), so note names should be unique across the vault. If duplicates exist, Obsidian uses the shortest path.

## Attachment Handling

### Configuration (`app.json`)

```json
{
  "attachmentFolderPath": "attachments"
}
```

This tells Obsidian where to store pasted/dropped files. Common patterns:

| Setting | Behavior |
|---------|----------|
| `"attachments"` | Single `attachments/` folder at vault root |
| `"./"` | Same folder as the note |
| `"./assets"` | `assets/` subfolder relative to the note |

### Image References

```markdown
<!-- Obsidian-native (wikilink) -->
![[image.png]]

<!-- Standard markdown (more portable) -->
![description](attachments/image.png)
```

Both work. This converter uses standard Markdown image links for maximum portability.

## `.obsidian/` Directory

Contains Obsidian's configuration. Key files:

| File | Purpose |
|------|---------|
| `app.json` | Core settings (attachment path, default view, etc.) |
| `appearance.json` | Theme, font, CSS snippet settings |
| `core-plugins.json` | Which built-in plugins are enabled |
| `community-plugins.json` | Installed community plugins |
| `hotkeys.json` | Custom keyboard shortcuts |
| `workspace.json` | Window layout, open tabs (auto-generated) |

For a freshly converted vault, only `app.json` is needed. Obsidian generates the rest on first open.

### Minimal `app.json`

```json
{
  "attachmentFolderPath": "attachments"
}
```

## Limitations Compared to CherryTree

| Feature | CherryTree | Obsidian |
|---------|-----------|----------|
| Note ordering | Explicit drag-and-drop (stored as sequence numbers) | Alphabetical only (no native ordering) |
| Rich text | Native XML with inline formatting | Markdown (no colors, limited formatting) |
| Embedded code boxes | First-class with syntax highlighting, dimensions | Fenced code blocks only |
| Tables | Interactive grid editor | Markdown tables (painful to edit by hand) |
| Inline images | Stored in SQLite BLOB, positioned by character offset | File references only |
| Text colors | Full foreground/background color support | Not supported in standard Markdown |
| Node icons | Built-in icon picker | Not supported |
| Password protection | Built-in encryption (7zip) | Requires third-party sync encryption |
| File size | Single `.ctb` file (SQLite) | Thousands of individual files |
