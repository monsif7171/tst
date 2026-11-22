"""Teryaq Licensing & Hardware Protection Package."""
from .manager import verify_current_license, activate_license, get_machine_id

__all__ = ["verify_current_license", "activate_license", "get_machine_id"]
