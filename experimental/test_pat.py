from pathlib import Path
from utils.pat import load_pat
from pprint import pformat

loaded = load_pat(Path(r"PC\X5\pat\stage\obj00_00.pat"))
print("quads", len(loaded.quads))
# print("quad counts", loaded.unique_frame_quad_counts)
print("anim_count", loaded.anim_count)
print("frame_counts", loaded.frame_counts)
print("sequence pairs", loaded.sequence_pairs)
# print("timing values", loaded.timing_values)
# print("unique frames", loaded.get_unique_frames())
print("animation sequence", loaded.get_animation_sequence(0))

# with open('pat_quads.txt', 'w') as f:
#     f.write(pformat(loaded.quads))


# Render a PNG preview using actual TEX tiles and a COL palette.
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None

if Image is None:
    print("Pillow not installed — install with: pip install pillow")
else:
    from utils.tex import load_tex, convert_tex_to_image
    from utils.palette import load_col_palettes

    # Config — adjust as needed
    TILE = 16
    PALETTE_PATH = Path(r"PC\X5\col\stage\col00_0x.col")
    TEX_PATH_TEMPLATE = Path(r"PC\X5\chr\stage\obj00_0a_{:03d}.tex")
    MAX_QUADS = 800
    # Hardcoded CLUT base for obj00_0a in stage st000.
    # quad.clut is a 2-bit *relative* offset; the absolute CLUT index is:
    #   absolute_clut = ocl_entry.clut_base + quad.clut
    # To resolve this properly at runtime, load the OCL table and look up the
    # entry that corresponds to this object:
    #
    #   from utils.ocl import load_ocl
    #   ocl_entries = load_ocl(Path(r"PC\X5\stage\st000\st000.ocl"))
    #   OCL_INDEX = 39  # obj00_0a, st000 — confirmed in utils/ocl.py docs
    #   CLUT_BASE = ocl_entries[OCL_INDEX].clut_base  # == 28
    CLUT_BASE = 28  # ocl_entries[39].clut_base for obj00_0a / st000

    # Load palette once
    palette = load_col_palettes(PALETTE_PATH)

    # Cache tex_data and converted images per (tpage, clut_index)
    tex_cache: dict[int, dict] = {}
    image_cache: dict[tuple[int, int], Image.Image] = {}

    N = min(MAX_QUADS, len(loaded.quads))
    img_w, img_h = 1536, 1536
    cx, cy = img_w // 2, img_h // 2
    im = Image.new("RGBA", (img_w, img_h), (30, 30, 30, 255))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for i, q in enumerate(loaded.quads[:N]):
        if i > 45:
            break

        # Load tex data for this tpage if missing
        if q.tpage not in tex_cache:
            tex_path = TEX_PATH_TEMPLATE.with_name(
                TEX_PATH_TEMPLATE.name.format(q.tpage)
            )
            try:
                tex_cache[q.tpage] = load_tex(tex_path)
            except Exception as e:
                tex_cache[q.tpage] = None
                print(f"Unable to load TEX {tex_path}: {e}")

        tex_data = tex_cache[q.tpage]

        x = cx + q.x
        y = cy + q.y

        tile_img = None
        if tex_data:
            # Resolve relative quad.clut (0–3) to absolute CLUT row via CLUT_BASE.
            absolute_clut = CLUT_BASE + q.clut
            key = (q.tpage, absolute_clut)
            if key not in image_cache:
                try:
                    tex_img = convert_tex_to_image(tex_data, palette, clut_index=absolute_clut)
                    image_cache[key] = tex_img
                except Exception as e:
                    image_cache[key] = None
                    print(
                        f"convert_tex_to_image failed for tpage={q.tpage} clut={absolute_clut}: {e}"
                    )

            tex_img = image_cache[key]
            if tex_img:
                w, h = tex_img.size
                cols = w // TILE
                tx = (q.tex % cols) * TILE
                ty = (q.tex // cols) * TILE
                tile_box = (tx, ty, tx + TILE, ty + TILE)
                tile_img = tex_img.crop(tile_box)
                if q.flip_h:
                    tile_img = tile_img.transpose(Image.FLIP_LEFT_RIGHT)
                if q.flip_v:
                    tile_img = tile_img.transpose(Image.FLIP_TOP_BOTTOM)

        if tile_img is None:
            # Fallback: draw placeholder rectangle
            r = (q.tex * 37) & 0xFF
            g = (q.tex * 71) & 0xFF
            b = (q.tex * 97) & 0xFF
            bbox = [x, y, x + TILE - 1, y + TILE - 1]
            draw.rectangle(bbox, fill=(r, g, b, 255), outline=(0, 0, 0))
            draw.text(
                (x + 1, y + 1), f"{q.tex}/{q.clut}", fill=(255, 255, 255), font=font
            )
        else:
            im.alpha_composite(tile_img.convert("RGBA"), dest=(x, y))

    out = "pat_quads_preview.png"
    im.save(out)
    print("Saved", out)
