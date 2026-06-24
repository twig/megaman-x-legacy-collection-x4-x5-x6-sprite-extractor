"""
Reader for the Capcom MT Framework ARC archive used by Mega Man X Legacy Collection.

Watto Studios' Game Extractor documents this family of formats; credit for the
format research goes to Watto Studios:
    https://www.watto.org/specs.html?specs=Archive_ARC_ARC_2
    https://github.com/wattostudios/GameExtractor

NOTE: the MMXLC `.arc` files are the MT Framework variant (4-byte "ARC\\0" magic,
per-file paths, zlib-compressed payloads), which differs from Watto's headerless
"ARC_2" spec. The layout below was confirmed against debug_data/st04_01_eng.arc.

All integers are little-endian.

Header (8 bytes):
    0x00  4  Magic "ARC\\0"
    0x04  2  Version (uint16, 7 for MMXLC)
    0x06  2  Number of files (uint16)

Directory: `num_files` entries of 80 bytes each, starting at 0x08:
    0x00  64  Filename / path, null-padded (backslash-separated, no extension)
    0x40   4  Type hash (jamcrc of the file extension; uint32)
    0x44   4  Compressed size (uint32)
    0x48   4  Decompressed size, low 29 bits; top 3 bits are flags (uint32)
    0x4C   4  Absolute offset of the file data within the archive (uint32)

Each file's data is a zlib stream at the given offset (older entries may be
stored uncompressed; we fall back to raw bytes if the stream is not zlib).
"""

import zlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

MAGIC = b"ARC\x00"
HEADER_SIZE = 8
ENTRY_SIZE = 80
NAME_LEN = 64
SIZE_MASK = 0x1FFFFFFF  # low 29 bits of the decompressed-size field; top 3 bits are flags


@dataclass
class ArcEntry:
    index: int
    name: str  # embedded path, backslash-separated, no extension
    type_hash: int  # jamcrc of the file extension
    comp_size: int
    decomp_size: int
    offset: int  # absolute byte offset of the (compressed) file data


@dataclass
class ArcHeader:
    version: int
    num_files: int
    entries: list[ArcEntry]


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 2], "little")


def _u32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 4], "little")


# Overrides where the content tag isn't the conventional extension.
_EXT_OVERRIDES = {"riff": "wav"}


def _guess_extension(data: bytes) -> str:
    # Derive an extension from the decompressed payload's 4-byte magic tag.
    # MMXLC files start with an ASCII tag (TEX, OMP, COL, RLST, ...) which both
    # names the type and disambiguates entries that share an embedded path.
    tag = data[:4].split(b"\x00")[0]
    if tag and all(0x20 < b < 0x7F for b in tag):
        ext = tag.decode("ascii").strip().lower()
        return "." + _EXT_OVERRIDES.get(ext, ext)
    return ".bin"


def parse_header(data: bytes) -> ArcHeader:
    # Parse the ARC header and directory table from the full archive bytes.
    if len(data) < HEADER_SIZE:
        raise ValueError(f"ARC file too small: {len(data)} bytes")
    if data[:4] != MAGIC:
        raise ValueError(f"Not an ARC archive: bad magic {data[:4]!r}")

    version = _u16(data, 0x04)
    num_files = _u16(data, 0x06)

    dir_end = HEADER_SIZE + num_files * ENTRY_SIZE
    if dir_end > len(data):
        raise ValueError(
            f"Invalid ARC directory: {num_files} entries exceed archive size {len(data)}"
        )

    entries: list[ArcEntry] = []
    for i in range(num_files):
        base = HEADER_SIZE + i * ENTRY_SIZE
        name = data[base : base + NAME_LEN].split(b"\x00")[0].decode("latin1")
        type_hash = _u32(data, base + NAME_LEN)
        comp_size = _u32(data, base + NAME_LEN + 4)
        decomp_size = _u32(data, base + NAME_LEN + 8) & SIZE_MASK
        offset = _u32(data, base + NAME_LEN + 12)
        if offset + comp_size > len(data):
            raise ValueError(
                f"Entry {i} ({name!r}): data range {offset}..{offset + comp_size} "
                f"exceeds archive size {len(data)}"
            )
        entries.append(
            ArcEntry(
                index=i,
                name=name,
                type_hash=type_hash,
                comp_size=comp_size,
                decomp_size=decomp_size,
                offset=offset,
            )
        )

    return ArcHeader(version=version, num_files=num_files, entries=entries)


def _read_file(data: bytes, entry: ArcEntry) -> bytes:
    raw = data[entry.offset : entry.offset + entry.comp_size]
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw  # stored uncompressed


def _peek_head(data: bytes, entry: ArcEntry, n: int = 4) -> bytes:
    # Decompress only the first `n` bytes — enough to read the content tag
    # without inflating the whole payload (used for listing).
    raw = data[entry.offset : entry.offset + entry.comp_size]
    try:
        return zlib.decompressobj().decompress(raw, n)
    except zlib.error:
        return raw[:n]


def _is_ignored(entry: ArcEntry, ignore: list[str] | None) -> bool:
    path = PureWindowsPath(entry.name)
    return any(path.full_match(pat) for pat in (ignore or []))


def _rel_path(entry: ArcEntry, head: bytes) -> Path:
    rel = Path(*entry.name.split("\\")) if entry.name else Path(f"file_{entry.index}")
    return rel.with_name(rel.name + _guess_extension(head))


def list_arc(input_path: Path, ignore: list[str] | None = None) -> list[tuple[Path, bool]]:
    """Return [(relative output path, ignored), ...] for every entry without extracting.

    `ignore` uses the same glob patterns as `extract_all_from_arc`.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    data = input_path.read_bytes()
    header = parse_header(data)
    return [
        (_rel_path(entry, _peek_head(data, entry)), _is_ignored(entry, ignore))
        for entry in header.entries
    ]


def extract_all_from_arc(
    input_path: Path, dest_path: Path, ignore: list[str] | None = None
) -> list[Path]:
    """Extract and decompress every file from `input_path` into `dest_path`.

    The embedded backslash paths are preserved as subdirectories, and an
    extension is appended from each file's content tag. Returns the list of
    written file paths.

    `ignore` is a list of case-insensitive glob patterns matched against each
    entry's full path (e.g. ["**/sound/**", "**/rlist/**"]).
    """
    input_path = Path(input_path)
    dest_path = Path(dest_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    data = input_path.read_bytes()
    header = parse_header(data)

    written: list[Path] = []
    for entry in header.entries:
        if _is_ignored(entry, ignore):
            continue
        payload = _read_file(data, entry)
        rel = _rel_path(entry, payload)
        out_path = dest_path / rel

        # Disambiguate the rare case of two entries resolving to the same path.
        if out_path.exists():
            out_path = out_path.with_name(f"{rel.stem}_{entry.index}{rel.suffix}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        written.append(out_path)

    return written


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract a Capcom MT Framework ARC archive.")
    parser.add_argument("input", type=Path, help="input .arc file")
    parser.add_argument("dest", type=Path, nargs="?", help="destination directory")
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="PATTERN",
        help="skip entries whose path matches the glob PATTERN, e.g. **/sound/** (repeatable, case-insensitive)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="dry run: list archive contents ([x] marks entries filtered by --ignore) without extracting",
    )
    args = parser.parse_args()

    if args.list:
        listing = list_arc(args.input, ignore=args.ignore)
        for rel, ignored in listing:
            print(f"[{'x' if ignored else ' '}] {rel.as_posix()}")
        kept = sum(not ignored for _, ignored in listing)
        print(f"\n{len(listing)} files ({kept} kept, {len(listing) - kept} ignored)")
    else:
        if args.dest is None:
            parser.error("dest is required unless --list is given")
        files = extract_all_from_arc(args.input, args.dest, ignore=args.ignore)
        print(f"Extracted {len(files)} files to {args.dest}")
