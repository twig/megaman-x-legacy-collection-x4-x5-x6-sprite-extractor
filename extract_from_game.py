import shutil
import sys
from pathlib import Path
from tkinter import filedialog

from extract_arc import extract_all_from_arc

# Need
# - project path
# - RMXLC1 exe for X4
# - RMXLC2 exe for X5 and X6
EXTRACT_DIR = Path(r"./PC")
# eg. D:\Games\Steam\steamapps\common\Mega Man X Legacy Collection\RXC1.exe
print("Looking for RXC1.exe ...")
LC1_EXE = filedialog.askopenfilename(
    title="Select RXC1.exe",
    filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
)
# eg. D:\Games\Steam\steamapps\common\Mega Man X Legacy Collection 2\RXC2.exe
print("Looking for RXC2.exe ...")
LC2_EXE = filedialog.askopenfilename(
    title="Select RXC2.exe",
    filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
)

if not LC1_EXE and not LC2_EXE:
    print("Path for either RXC1.exe or RXC2.exe required")
    sys.exit(0)

LC1_EXE = Path(LC1_EXE) if LC1_EXE else None
LC2_EXE = Path(LC2_EXE) if LC2_EXE else None

if LC1_EXE and not LC1_EXE.exists():
    print("Invalid path for RXC1.exe")
    sys.exit(0)
if LC2_EXE and not LC2_EXE.exists():
    print("Invalid path for RXC2.exe")
    sys.exit(0)

# options
PREFER_ENGLISH = True
PREFER_X = True # False case "PREFER_Z" not fully implemented

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


## RMXLC1
if LC1_EXE:
    print("Starting X4...")
    X4_DATA_DIR = LC1_EXE.parent / "nativeDX10/X4/romPC"

    # X4
    # st*.arc, prefer st*_eng.arc
    X4_DATA_FILES = [
        file for file
        in sorted(X4_DATA_DIR.glob("st*.arc"))
        if should_extract(PREFER_ENGLISH, file)
    ]

    # don't extract
    # - kaiwa
    # - rlist
    # - sound
    for arc_file in X4_DATA_FILES:
        print(f"\rX4: extract {arc_file.name}", end="\r", flush=True)
        extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=["**/kaiwa/**", "**/rlist/**", "**/sound/**"])
    print("\nX4 done")

    print(f"Copying RXC1.exe")
    shutil.copy(LC1_EXE, EXTRACT_DIR)



## RMXLC2
if LC2_EXE:
    # X5
    # COL*.arc, prefer COL*_ENG.arc
    # ST*.arc, prefer ST*_ENG.arc
    print("Starting X5...")
    X5_DATA_DIR = LC2_EXE.parent / "nativeDX10/X5/romPC"

    X5_DATA_FILES = [
        file for file
        in sorted(
            list(X5_DATA_DIR.glob("COL*.arc")) +
            list(X5_DATA_DIR.glob("ST*.arc"))
        )
        if should_extract(PREFER_ENGLISH, file)
    ]

    # don't extract
    # - kaiwaData
    # - sound
    for arc_file in X5_DATA_FILES:
        print(f"\rX5: extract {arc_file.name}", end="\r", flush=True)
        extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=[
            "**/kaiwaData/**",
            "**/sound/**",
            "**/stage/*demo*/**",
        ])
    print("\nrX5 done")

    ## X6
    # st*.arc, prefer st*_eng.arc
    # result.arc, prefer result_eng.arc
    # title.arc, prefer title_eng.arc
    print("Starting X6...")
    X6_DATA_DIR = LC2_EXE.parent / "nativeDX10/X6/romPC"

    X6_DATA_FILES = [
        file for file
        in sorted(
            list(X6_DATA_DIR.glob("st*.arc")) +
            list(X6_DATA_DIR.glob("result*.arc")) +
            list(X6_DATA_DIR.glob("title*.arc"))
        )
        if should_extract(PREFER_ENGLISH, file)
    ]

    # whats this?
    # - kao (lots of COL boss files?)
    # ignore
    # - kaiwa
    # - sound
    for arc_file in X6_DATA_FILES:
        print(f"X6: extract {arc_file.name}", end="\r", flush=True)
        extract_all_from_arc(arc_file, EXTRACT_DIR, ignore=["**/kaiwa/**", "**/sound/**"])
    print("\nX6 done")

    print(f"Copying RXC2.exe")
    shutil.copy(LC2_EXE, EXTRACT_DIR)
