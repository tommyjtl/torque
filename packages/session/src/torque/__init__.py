"""Public Torque device API. All MCU access goes through the local daemon."""
from pathlib import Path as _Path
import sys as _sys

# A long-lived client keeps importing its original release after current moves.
_physical = _Path(__file__).resolve().parent
_lexical = _Path(__file__).absolute().parent
__path__ = [str(_physical)]
_sys.path[:] = [str(_physical.parent) if p == str(_lexical.parent) else p for p in _sys.path]
from .sdk import Board
from unoq_control import Frame, ControllerError, FirmwareError, ResetError

__all__ = ['Board', 'Frame', 'ControllerError', 'FirmwareError', 'ResetError']
