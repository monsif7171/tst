"""Cryptographic signing and verification for licenses.
Uses RSA-2048 with PSS padding and SHA-256 digest.
"""
import base64
import json
from typing import Tuple, Optional, Dict, Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key, load_pem_private_key

from .public_key import PUBLIC_KEY_PEM


def canonical_json(data: Dict[str, Any]) -> bytes:
    """Format JSON deterministically (sorted keys, no spaces) for cryptographic signing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_payload(payload: Dict[str, Any], private_key_pem: bytes) -> str:
    """Sign a license payload with the developer's private key.
    Returns: A compact token string: <base64_payload>.<base64_signature>
    """
    priv_key = load_pem_private_key(private_key_pem, password=None)
    payload_bytes = canonical_json(payload)

    signature = priv_key.sign(
        payload_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )

    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def _pad_b64(s: str) -> str:
    """Add back missing padding characters."""
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return s


def verify_token(token: str, public_key_pem: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Verify a license token using the embedded public key.
    Returns: (is_valid, payload_data, error_message)
    """
    if not token or "." not in token:
        return False, None, "صيغة مفتاح الترخيص غير صالحة"

    parts = token.strip().split(".")
    if len(parts) != 2:
        return False, None, "مفتاح الترخيص غير مكتمل أو مشوه"

    b64_payload, b64_sig = parts[0], parts[1]

    try:
        payload_bytes = base64.urlsafe_b64decode(_pad_b64(b64_payload))
        sig_bytes = base64.urlsafe_b64decode(_pad_b64(b64_sig))
    except Exception:
        return False, None, "فشل فك ترميز بيانات الترخيص"

    pem_str = public_key_pem or PUBLIC_KEY_PEM
    try:
        pub_key = load_pem_public_key(pem_str.encode("utf-8"))
        pub_key.verify(
            sig_bytes,
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
    except Exception:
        return False, None, "التوقيع الرقمي للترخيص غير صحيح (تم التعديل عليه أو صادر من جهة غير مخولة)"

    try:
        data = json.loads(payload_bytes.decode("utf-8"))
        return True, data, ""
    except Exception:
        return False, None, "بيانات الترخيص الداخلية تالفة"
