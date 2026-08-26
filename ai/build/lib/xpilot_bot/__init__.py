"""xpilot_bot -- a headless Python client for XPilot NG.

Speaks the original wire protocol, so it plays against unmodified servers.
"""

from .client import Client, ProtocolError, Status
from . import protocol

__all__ = ["Client", "ProtocolError", "Status", "protocol"]
__version__ = "0.1.0"
