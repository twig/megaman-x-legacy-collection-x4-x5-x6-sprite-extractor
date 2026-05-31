from pathlib import Path

from utils.types import TexData, TexFormat


def parse_tex_header(data: bytes) -> tuple[int, int, int, int]:
    if len(data) < 0x30:
        raise ValueError(f"TEX file too small: {len(data)} bytes")

    # Check magic header
    if data[:4] != b"TEX\x00":
        raise ValueError(f"Not a TEX file: {data[:4]!r}")

    packed = int.from_bytes(data[0x08:0x0C], "little")
    format_code = data[0x0D]
    mip_count = packed & 0x3F
    width = (packed & 0x0007FFC0) >> 6
    height = (packed & 0xFFF80000) >> 19

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid dimensions: {width}x{height}")

    return format_code, width, height, mip_count


def load_tex(input_path: Path) -> TexData:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    data = input_path.read_bytes()
    format_code, width, height, mip_count = parse_tex_header(data)

    # print(
    #     "header",
    #     {
    #         "format_code": format_code,
    #         "width": width,
    #         "height": height,
    #         "_mip_count": mip_count,
    #     },
    # )

    if format_code == TexFormat.FORMAT_32BPP:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height * 4
        raw_image = data[base_offset : base_offset + expected_size]

    elif format_code == TexFormat.FORMAT_8BPP:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height
        raw_image = data[base_offset : base_offset + expected_size]

    else:
        raise NotImplementedError(
            f"Unsupported TEX format 0x{format_code:02x}. "
            "This extractor currently supports palette-mapped TEX files only."
        )

    if len(raw_image) != expected_size:
        raise ValueError(
            f"Payload size mismatch for {input_path.name}: "
            f"expected {expected_size} bytes, got {len(raw_image)}"
        )

    return {
        # Python types can't seem to determine whats been filtered out
        "format_code": format_code,  # type: ignore
        "width": width,
        "height": height,
        "mip_count": mip_count,
        "raw_image": raw_image,
    }
