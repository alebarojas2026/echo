"""The board's operator key for the tools here that send commands (CONTRACTS.md section 5).

When the board has OPERATOR_KEY in its .env, a cmd without the key is ignored. Set the same
value in the shell that runs a proof tool. It is read from the environment only: never a flag,
never prompted for, never printed or written to a file.
"""
import os


def with_key(msg: dict) -> dict:
    """The cmd with "key" added when OPERATOR_KEY is set; unchanged when it isn't."""
    key = os.environ.get("OPERATOR_KEY")
    return dict(msg, key=key) if key else msg
