"""
Scancode mapping for evdev-based QR scanner.

Maps Linux evdev scancodes to their corresponding characters.
Based on standard US QWERTY keyboard layout.
"""

# Standard scancode to character mapping (without shift)
SCANCODE_MAP = {
    # Numbers row
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "-", 13: "=",
    
    # QWERTY row
    16: "q", 17: "w", 18: "e", 19: "r", 20: "t",
    21: "y", 22: "u", 23: "i", 24: "o", 25: "p",
    26: "[", 27: "]",
    
    # ASDF row
    30: "a", 31: "s", 32: "d", 33: "f", 34: "g",
    35: "h", 36: "j", 37: "k", 38: "l",
    39: ";", 40: "'",
    
    # ZXCV row
    44: "z", 45: "x", 46: "c", 47: "v", 48: "b",
    49: "n", 50: "m", 51: ",", 52: ".", 53: "/",
    
    # Special keys
    28: "\n",     # Enter
    57: " ",      # Space
    43: "\\",     # Backslash
    41: "`",      # Grave accent
}

# Shifted character mapping (when shift is pressed)
SCANCODE_MAP_SHIFTED = {
    # Numbers row with shift
    2: "!", 3: "@", 4: "#", 5: "$", 6: "%",
    7: "^", 8: "&", 9: "*", 10: "(", 11: ")",
    12: "_", 13: "+",
    
    # QWERTY row with shift
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T",
    21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    26: "{", 27: "}",
    
    # ASDF row with shift
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G",
    35: "H", 36: "J", 37: "K", 38: "L",
    39: ":", 40: '"',
    
    # ZXCV row with shift
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B",
    49: "N", 50: "M", 51: "<", 52: ">", 53: "?",
    
    # Special keys
    28: "\n",     # Enter (same as unshifted)
    57: " ",      # Space (same as unshifted)
    43: "|",      # Backslash shifted
    41: "~",      # Grave accent shifted
}

# Modifier key scancodes
MODIFIER_KEYS = {
    42: "shift_left",      # Left Shift
    54: "shift_right",     # Right Shift
    29: "ctrl_left",       # Left Ctrl
    97: "ctrl_right",      # Right Ctrl
    56: "alt_left",        # Left Alt
    100: "alt_right",      # Right Alt (AltGr)
}


def get_character(scancode: int, shift_pressed: bool = False) -> str:
    """
    Get character for given scancode.
    
    Args:
        scancode: Linux evdev scancode
        shift_pressed: Whether shift key is currently pressed
    
    Returns:
        Character string or empty string if scancode not mapped
    """
    if shift_pressed:
        return SCANCODE_MAP_SHIFTED.get(scancode, "")
    else:
        return SCANCODE_MAP.get(scancode, "")


def is_modifier_key(scancode: int) -> bool:
    """Check if scancode is a modifier key."""
    return scancode in MODIFIER_KEYS


def get_modifier_name(scancode: int) -> str:
    """Get modifier key name for scancode."""
    return MODIFIER_KEYS.get(scancode, "")