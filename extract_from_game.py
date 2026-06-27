import shutil
import sys
from pathlib import Path

from extract_arc import extract_all_from_arc

# Need
# - project path
EXTRACT_DIR = Path(r"./PC")
# - RMXLC1 exe for X4
LC1_EXE = Path(r"D:\Games\Steam\steamapps\common\Mega Man X Legacy Collection\RXC1.exe")
# - RMXLC2 exe for X5 and X6
LC2_EXE = Path(r"D:\Games\Steam\steamapps\common\Mega Man X Legacy Collection 2\RXC2.exe")

# options
PREFER_ENGLISH = True
PREFER_X = True

# helpers
def is_english_file(file: Path) -> bool:
    # X4/X6 eng, X5 ENG
    return (file.stem.endswith('_eng') or file.stem.endswith('_ENG'))

def has_english_alternative(file: Path) -> bool:
    # X4/X6 eng, X5 ENG
    return file.with_stem(file.stem + "_eng").exists() or file.with_stem(file.stem + "_ENG").exists()

def should_extract(prefer_english: bool, file: Path) -> bool:
    if not prefer_english and is_english_file(file):
        # print(f"should_extract: skip {file.name}, is English")
        return False

    if prefer_english and has_english_alternative(file):
        # print(f"should_extract: skip {file.name}, has English alternative")
        return False

    if PREFER_X and 'z' in file.stem.lower():
        return False

    return True

# Infer
X4_DATA_DIR = LC1_EXE.parent / "nativeDX10/X4/romPC"
X5_DATA_DIR = LC2_EXE.parent / "nativeDX10/X5/romPC"
X6_DATA_DIR = LC2_EXE.parent / "nativeDX10/X6/romPC"

X4_DATA_FILES = [
    file for file
    in sorted(X4_DATA_DIR.glob("st*.arc"))
    if should_extract(PREFER_ENGLISH, file)
]
X5_DATA_FILES = [
    file for file
    in sorted(
        list(X5_DATA_DIR.glob("COL*.arc")) +
        list(X5_DATA_DIR.glob("ST*.arc"))
    )
    if should_extract(PREFER_ENGLISH, file)
]
X6_DATA_FILES = [
    file for file
    in sorted(
        list(X6_DATA_DIR.glob("st*.arc")) +
        list(X6_DATA_DIR.glob("result*.arc")) +
        list(X6_DATA_DIR.glob("title*.arc"))
    )
    if should_extract(PREFER_ENGLISH, file)
]

# RXC1
# Steam\steamapps\common\Mega Man X Legacy Collection
# RXC1.exe

## X4
# Steam\steamapps\common\Mega Man X Legacy Collection\nativeDX10\X4\romPC
# st*.arc, prefer st*_eng.arc
#
# don't extract
# - kaiwa
# - rlist
# - sound
print("Starting X4...")
for arc_file in X4_DATA_FILES:
    print(f"\rX4: extract {arc_file.name}", end="\r", flush=True)
    extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=["**/kaiwa/**", "**/rlist/**", "**/sound/**"])
print("\nX4 done")

# RXC2
# Steam\steamapps\common\Mega Man X Legacy Collection 2
# RXC2.exe

## X5
# Steam\steamapps\common\Mega Man X Legacy Collection 2\nativeDX10\X5\romPC
# COL*.arc, prefer COL*_ENG.arc
# ST*.arc, prefer ST*_ENG.arc
#
# don't extract
# - kaiwaData
# - sound
print("Starting X5...")
for arc_file in X5_DATA_FILES:
    print(f"\rX5: extract {arc_file.name}", end="\r", flush=True)
    extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=[
        "**/kaiwaData/**",
        "**/sound/**",
        "**/stage/*demo*/**",
    ])
print("\nrX5 done")

## X6
# Steam\steamapps\common\Mega Man X Legacy Collection 2\nativeDX10\X6\romPC
# st*.arc, prefer st*_eng.arc
# result.arc, prefer result_eng.arc
# title.arc, prefer title_eng.arc
#
# whats this?
# - kao (lots of COL boss files?)
print("Starting X6...")
for arc_file in X6_DATA_FILES:
    print(f"X6: extract {arc_file.name}", end="\r", flush=True)
    extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=["**/kaiwa/**", "**/sound/**"])
print("\nX6 done")

if LC1_EXE.exists():
    print(f"Copying RXC1.exe")
    shutil.copy(LC1_EXE, EXTRACT_DIR)

if LC2_EXE.exists():
    print(f"Copying RXC2.exe")
    shutil.copy(LC2_EXE, EXTRACT_DIR)
