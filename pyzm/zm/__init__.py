"""pyzm.zm -- ZoneMinder API layer (v2).

Re-exports the public surface so callers can do::

    from pyzm.zm import ZMAPI, AuthManager, SharedMemory, FrameExtractor
"""

from pyzm.zm.auth import AuthManager, ZMLoginError
from pyzm.zm.api import ZMAPI
from pyzm.zm.media import FrameExtractor
from pyzm.zm.shm import SharedMemory

__all__ = [
    "AuthManager",
    "ZMLoginError",
    "ZMAPI",
    "FrameExtractor",
    "SharedMemory",
]
