"""The SP103's remote codes, as pulses on the IR line.

Decoded from the groove-rig profile (internal/catalog/profiles/acoustic_solutions_sp103.yaml,
captured with a Broadlink RM4): a long leader, the bytes 20 E1 DB, the command byte, its
inverse and two 1 bits, always LSB first. After 24 ms comes the repeat code, just like
the remote sends. tools/test_ir.py checks the bits against the profile.

frame() runs the same in MicroPython (Pico) and in the computer's Python.
"""

COMMANDS = {"power_toggle": 0x77, "volume_up": 0x7F, "volume_down": 0x7B, "bass": 0x6F, "treble": 0x73,
            "select_phono": 0x63, "select_tuner": 0x57, "select_tape_aux": 0x5B, "select_cd": 0x67,
            "select_dvd": 0x6B, "select_dab": 0x5F}

PREFIX = (0x20, 0xE1, 0xDB)
# Times in µs measured on the IR line itself, with the real remote (2026-11-06). The Broadlink's
# are about 5% longer, and with them the controller did not react.
LEADER_MARK, LEADER_SPACE = 9030, 4470
MARK, SPACE_0, SPACE_1 = 600, 545, 1665
REPEAT_GAP = 22750
END_SPACE = 1000                        # the list always ends with a space (see ir.py)


def frame(command):
    """A command's times in µs: line at 0, line released, line at 0, and so on."""
    code = COMMANDS[command]
    words = [LEADER_MARK, LEADER_SPACE]
    for byte in PREFIX + (code, code ^ 0xFF):
        for bit in range(8):
            words += [MARK, SPACE_1 if byte >> bit & 1 else SPACE_0]
    words += [MARK, SPACE_1, MARK, SPACE_1]
    words += [MARK, REPEAT_GAP, LEADER_MARK, LEADER_SPACE, MARK, END_SPACE]
    return words
