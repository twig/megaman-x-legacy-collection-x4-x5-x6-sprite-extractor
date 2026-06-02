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
    PALETTE_PATH = Path(r"PC\X5\col\stage\col00_0x_eng.col")
    TEX_PATH_TEMPLATE = Path(r"PC\X5\chr\stage\obj00_0a_{:03d}.tex")
    MAX_QUADS = 800

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
            # Use the quad.clut as CLUT row index for preview (relative mapping)
            key = (q.tpage, q.clut)
            if key not in image_cache:
                try:
                    tex_img = convert_tex_to_image(tex_data, palette, clut_index=q.clut)
                    image_cache[key] = tex_img
                except Exception as e:
                    image_cache[key] = None
                    print(
                        f"convert_tex_to_image failed for tpage={q.tpage} clut={q.clut}: {e}"
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
