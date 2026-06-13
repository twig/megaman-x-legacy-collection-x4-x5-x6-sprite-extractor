"""
x4_pc_layout_offsets.py

Mega Man X4 stage layout offsets in RXC1.exe (Mega Man X Legacy Collection 1 PC).
Each offset points to the first byte of layer 0 (the foreground layer).
Full layout block = w * h * 3 bytes (3 consecutive layers, each w*h screen IDs).

Verification levels:
  verified  — max(exe[pc_offset : pc_offset + w*h]) == n_screens - 1
  compat    — exact PSX bytes found in PC exe; PC OMP has more screens
              (Legacy Collection expanded the OMP but kept the same layout data)

n_screens comes from PC/X4/stage/map/SCR*.omp (uint32LE @ byte 8 // 256)
"""

# fmt: off
X4_LAYOUT_OFFSETS: dict[str, dict] = {
    "ST01_00": {"pc_offset": 0x00B61308, "w": 28, "h": 9, "n_screens": 123},  # verified
    "ST02_01": {"pc_offset": 0x00B61BF8, "w": 29, "h": 8, "n_screens": 160},  # verified
    "ST03_00": {"pc_offset": 0x00B61EB0, "w": 25, "h": 10, "n_screens": 98},  # verified
    "ST08_00": {"pc_offset": 0x00B63C10, "w": 30, "h": 8, "n_screens": 48},  # verified
    "ST08_01": {"pc_offset": 0x00B63EE0, "w": 40, "h": 6, "n_screens": 81},  # verified
    "ST0A_00": {"pc_offset": 0x00B641B0, "w": 25, "h": 10, "n_screens": 64},  # verified
    "ST00_00": {"pc_offset": 0x00B60D08, "w": 32, "h": 8, "n_screens": 86},  # compat (PC OMP expanded)
    "ST00_01": {"pc_offset": 0x00B61008, "w": 32, "h": 8, "n_screens": 74},  # compat (PC OMP expanded)
    "ST01_01": {"pc_offset": 0x00B61608, "w": 28, "h": 9, "n_screens": 115},  # compat (PC OMP expanded)
    "ST02_00": {"pc_offset": 0x00B61908, "w": 25, "h": 10, "n_screens": 157},  # compat (PC OMP expanded)
    "ST03_01": {"pc_offset": 0x00B621A0, "w": 25, "h": 10, "n_screens": 80},  # compat (PC OMP expanded)
    "ST04_00": {"pc_offset": 0x00B62490, "w": 32, "h": 8, "n_screens": 80},  # compat (PC OMP expanded)
    "ST04_01": {"pc_offset": 0x00B62790, "w": 32, "h": 8, "n_screens": 83},  # compat (PC OMP expanded)
    "ST05_00": {"pc_offset": 0x00B62A90, "w": 255, "h": 1, "n_screens": 84},  # compat (PC OMP expanded)
    "ST05_01": {"pc_offset": 0x00B62D90, "w": 128, "h": 2, "n_screens": 107},  # compat (PC OMP expanded)
    "ST06_00": {"pc_offset": 0x00B63090, "w": 25, "h": 10, "n_screens": 112},  # compat (PC OMP expanded)
    "ST06_01": {"pc_offset": 0x00B63380, "w": 25, "h": 10, "n_screens": 160},  # compat (PC OMP expanded)
    "ST07_00": {"pc_offset": 0x00B63670, "w": 30, "h": 8, "n_screens": 81},  # compat (PC OMP expanded)
    "ST07_01": {"pc_offset": 0x00B63940, "w": 30, "h": 8, "n_screens": 64},  # compat (PC OMP expanded)
    "ST0C_00": {"pc_offset": 0x00B64618, "w": 20, "h": 10, "n_screens": 81},  # compat (PC OMP expanded)
    "ST0C_01": {"pc_offset": 0x00B64870, "w": 10, "h": 5, "n_screens": 21},  # compat (PC OMP expanded)
}
# fmt: on

# Block byte size per stage = w * h * 3  (layer0 + layer1 + layer2)
