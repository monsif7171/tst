"""Hardware Identification (HWID) extraction module.
Generates a stable, unique, and tamper-resistant fingerprint for Windows machines.
"""
import hashlib
import os
import platform
import subprocess
import uuid
from functools import lru_cache

try:
    import winreg
except ImportError:
    winreg = None

try:
    from config import BASE_DIR
except ImportError:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HWID_CACHE_FILE = os.path.join(BASE_DIR, "data", ".hwid")


def _get_registry_value(path: str, name: str) -> str:
    """Read a registry value instantaneously on Windows."""
    if not winreg:
        return ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            path,
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ) as key:
            val, _ = winreg.QueryValueEx(key, name)
            return str(val).strip()
    except Exception:
        return ""


def _query_wmi_hwid() -> tuple[str, str]:
    """Execute PowerShell / WMI command to retrieve UUID and ProcessorId with fast fallback on Windows."""
    if platform.system() != "Windows":
        return "", ""
    sys_uuid = ""
    cpu_id = ""

    # Try fast WMIC first if available
    try:
        out = subprocess.check_output(
            ["wmic", "csproduct", "get", "UUID"],
            timeout=3,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line.strip() for line in out.decode("utf-8", errors="ignore").splitlines() if line.strip()]
        for l in lines:
            if l.lower() != "uuid" and len(l) > 10:
                sys_uuid = l
                break
    except Exception:
        pass

    # Fallback to PowerShell Get-CimInstance only if sys_uuid wasn't found
    if not sys_uuid:
        cmd = "Write-Output (Get-CimInstance Win32_ComputerSystemProduct).UUID; Write-Output (Get-CimInstance Win32_Processor).ProcessorId"
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                timeout=4,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = [line.strip() for line in out.decode("utf-8", errors="ignore").splitlines() if line.strip()]
            if len(lines) >= 1:
                sys_uuid = lines[0]
            if len(lines) >= 2:
                cpu_id = lines[1]
        except Exception:
            pass

    return sys_uuid, cpu_id


@lru_cache(maxsize=1)
def get_machine_id() -> str:
    """Generate a clean, formatted Machine ID (e.g. TRYQ-4962-6D17-CFB3-FA60).
    Caches in memory and on disk for zero-latency lookups.
    """
    # 1. Check disk cache first for fast 0ms startup
    if os.path.exists(HWID_CACHE_FILE):
        try:
            with open(HWID_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = f.read().strip()
                if cached.startswith("TRYQ-") and len(cached) == 24:
                    return cached
        except Exception:
            pass

    # 2. Extract hardware identifiers
    reg_guid = _get_registry_value(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid")
    cpu_ident = _get_registry_value(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Identifier")
    sys_uuid, cpu_id = _query_wmi_hwid()

    # If running on Linux / cloud, check /etc/machine-id
    linux_mid = ""
    if platform.system() == "Linux":
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        linux_mid = f.read().strip()
                        if linux_mid:
                            break
                except Exception:
                    pass

    # Combine primary anchors
    components = [sys_uuid or "NO_UUID", reg_guid or "NO_GUID", cpu_id or cpu_ident or "NO_CPU"]
    if linux_mid:
        components.append(linux_mid)
    combined = "|".join(components)

    # Fallback if all else fails
    if combined == "NO_UUID|NO_GUID|NO_CPU":
        combined = f"{uuid.getnode()}|{platform.node()}"

    # SHA-256 hash
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest().upper()
    hwid = f"TRYQ-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"

    # Save to disk cache
    try:
        os.makedirs(os.path.dirname(HWID_CACHE_FILE), exist_ok=True)
        with open(HWID_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(hwid)
    except Exception:
        pass

    return hwid


if __name__ == "__main__":
    print("Machine ID:", get_machine_id())
