"""Anti-Tampering & Clock Rollback Detection module."""
import os
import time
from datetime import datetime, timedelta

def check_and_update_clock(data_dir: str) -> tuple[bool, str]:
    """Check if the system clock has been rolled back into the past.
    Returns: (is_safe, error_message)
    """
    marker_file = os.path.join(data_dir, ".tstamp")
    now_ts = int(time.time())
    
    if os.path.exists(marker_file):
        try:
            with open(marker_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                last_ts = int(content)
                # Allow up to 2 hours of clock drift / daylight saving tolerance
                if now_ts < (last_ts - 7200):
                    last_date_str = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M")
                    return False, f"تم اكتشاف تلاعب في ساعة وتاريخ الجهاز! (آخر تاريخ تشغيل مسجل: {last_date_str})"
        except Exception:
            pass

    # Save current timestamp
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(marker_file, "w", encoding="utf-8") as f:
            f.write(str(now_ts))
    except Exception:
        pass

    return True, ""
