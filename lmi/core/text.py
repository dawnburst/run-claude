"""Decoding text that may carry a byte order mark.

One implementation, three callers: the prompt file, the state file's body as
it is inlined into the next prompt, and the state file's first line in the
completion check. They must agree - a state file that check_complete reads as
UTF-16 must not be inlined into the prompt as mojibake.

ANSI text carries no mark and stays undetectable by construction; that limit
is inherited from run-claude.bat and is not fixable here.
"""

BOM_UTF8 = b"\xef\xbb\xbf"
BOMS_UTF16 = (b"\xff\xfe", b"\xfe\xff")


def decode_with_bom(raw, errors="strict"):
    """Decode `raw`, honouring a UTF-8 or UTF-16 BOM, else assuming UTF-8.

    With errors="strict" a non-UTF-8, non-UTF-16 payload raises
    UnicodeDecodeError, which is what the prompt reader turns into a usage
    error. With errors="replace" nothing raises.
    """
    if raw.startswith(BOM_UTF8):
        return raw[len(BOM_UTF8):].decode("utf-8", errors)
    if raw[:2] in BOMS_UTF16:
        try:
            return raw.decode("utf-16", errors)
        except UnicodeDecodeError:
            # An odd byte count, or a truncated surrogate: the BOM lied.
            # Fall through and let UTF-8 have its say (and its error).
            pass
    return raw.decode("utf-8", errors)
