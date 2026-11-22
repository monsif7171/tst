"""
OpenFDA Drug Database Service
Allows searching and fetching medication details (brand name, generic name,
strength, dosage form, manufacturer, UPC barcode, and prescription status)
from OpenFDA's open drug database.
"""
import os
import re
import logging
import requests

logger = logging.getLogger("pharmacy.drug_service")

OPENFDA_NDC_URL = "https://api.fda.gov/drug/ndc.json"
DEFAULT_TIMEOUT = 12



def get_api_key(conn=None):
    """Retrieve API key from DB settings table first, falling back to environment variable."""
    if conn:
        try:
            from ._common import q1
            db_key = q1(conn, "SELECT value FROM settings WHERE key = 'openfda_api_key'")
            if db_key and str(db_key).strip():
                return str(db_key).strip()
        except Exception as e:
            logger.debug(f"Could not load openfda_api_key from settings: {e}")

    return os.environ.get("OPENFDA_API_KEY", os.environ.get("DRUG_API_KEY", "")).strip()


def _format_openfda_result(item, requested_barcode=None):
    """Normalize an OpenFDA NDC item into our pharmacy product schema."""
    if not item or not isinstance(item, dict):
        return None

    brand_name = (item.get("brand_name") or item.get("brand_name_base") or "").strip()
    generic_name = (item.get("generic_name") or "").strip()
    dosage_form = (item.get("dosage_form") or "").strip()
    manufacturer = (item.get("labeler_name") or "").strip()

    # Extract active ingredients & strength
    active_ings = item.get("active_ingredients") or []
    strengths = []
    if isinstance(active_ings, list):
        for ai in active_ings:
            if isinstance(ai, dict):
                s = ai.get("strength")
                if s:
                    strengths.append(str(s).strip())
    strength_str = ", ".join(strengths) if strengths else ""

    # Determine barcode
    openfda = item.get("openfda") or {}
    upcs = openfda.get("upc") or []
    barcode = requested_barcode
    if not barcode and upcs and isinstance(upcs, list):
        barcode = upcs[0]
    if not barcode:
        # Fall back to package NDC or product NDC
        pkgs = item.get("packaging") or []
        if pkgs and isinstance(pkgs, list) and isinstance(pkgs[0], dict):
            barcode = pkgs[0].get("package_ndc")
        if not barcode:
            barcode = item.get("product_ndc")

    # Clean barcode if any
    if barcode:
        barcode = str(barcode).strip()

    # Determine prescription status
    product_type = (item.get("product_type") or "").upper()
    is_prescription = 1 if "PRESCRIPTION" in product_type else 0

    # Determine category
    pharm_class = item.get("pharm_class") or []
    category = ""
    if isinstance(pharm_class, list) and pharm_class:
        category = pharm_class[0]
        # Clean up tags like [EPC] or [MoA]
        category = re.sub(r"\s*\[.*?\]", "", category).strip()
    elif dosage_form:
        category = dosage_form.title()

    # Fallback name if brand_name is empty
    if not brand_name and generic_name:
        brand_name = generic_name.title()

    if not brand_name:
        return None

    return {
        "name": brand_name,
        "generic_name": generic_name,
        "strength": strength_str,
        "form": dosage_form,
        "manufacturer": manufacturer,
        "category": category,
        "barcode": barcode or "",
        "is_prescription": is_prescription,
        "source": "OpenFDA"
    }


def lookup_drug_by_barcode(barcode: str, conn=None):
    """
    Search OpenFDA by UPC or NDC barcode.
    Handles 12-digit UPC, 13-digit EAN, and package NDC formats.
    """
    if not barcode:
        return None

    cleaned = str(barcode).strip()
    if not cleaned:
        return None

    api_key = get_api_key(conn)
    headers = {"User-Agent": "PharmacySystem/1.0 (HealthCare POS)"}

    # Generate candidate barcode formats (raw, with leading 0, without leading 0)
    candidates = [cleaned]
    if cleaned.startswith("0") and len(cleaned) == 13:
        candidates.append(cleaned[1:])
    elif len(cleaned) == 12:
        candidates.append("0" + cleaned)

    for cand in candidates:
        # 1. Search by openfda.upc
        params = {
            "search": f'openfda.upc:"{cand}"',
            "limit": 1
        }
        if api_key:
            params["api_key"] = api_key

        try:
            resp = requests.get(OPENFDA_NDC_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []
                if results:
                    prod = _format_openfda_result(results[0], requested_barcode=cleaned)
                    if prod:
                        return prod
            elif resp.status_code == 404:
                pass  # Try next candidate
            else:
                logger.warning(f"OpenFDA UPC query returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error querying OpenFDA for UPC {cand}: {e}")

        # 2. Search by packaging.package_ndc or product_ndc
        params_ndc = {
            "search": f'packaging.package_ndc:"{cand}" OR product_ndc:"{cand}"',
            "limit": 1
        }
        if api_key:
            params_ndc["api_key"] = api_key

        try:
            resp = requests.get(OPENFDA_NDC_URL, params=params_ndc, headers=headers, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []
                if results:
                    prod = _format_openfda_result(results[0], requested_barcode=cleaned)
                    if prod:
                        return prod
        except Exception as e:
            logger.error(f"Error querying OpenFDA for NDC {cand}: {e}")

    return None


_ARABIC_TO_ENGLISH_DRUGS = {
    "بانادول": "panadol",
    "بنادول": "panadol",
    "باراسيتامول": "paracetamol",
    "اسبرين": "aspirin",
    "أسبرين": "aspirin",
    "بروفين": "brufen",
    "ايبوبروفين": "ibuprofen",
    "إيبوبروفين": "ibuprofen",
    "فولتارين": "voltaren",
    "ديكلوفيناك": "diclofenac",
    "اوميبرازول": "omeprazole",
    "أوميبرازول": "omeprazole",
    "اموكسيسيلين": "amoxicillin",
    "أموكسيسيلين": "amoxicillin",
    "اموكسيل": "amoxil",
    "اوجمنتين": "augmentin",
    "أوجمنتين": "augmentin",
    "كونكور": "concor",
    "ليبيتور": "lipitor",
    "ميتفورمين": "metformin",
    "جلوكوفاج": "glucophage",
    "كتافلام": "cataflam",
    "سيتريزين": "cetirizine",
    "زيرتك": "zyrtec",
    "كلاريتين": "claritin",
    "لوراتادين": "loratadine",
    "بانتوبرازول": "pantoprazole",
    "ازيثرومايسين": "azithromycin",
    "أزيثروميسين": "azithromycin",
    "زيثروماكس": "zithromax",
    "فيتامين": "vitamin",
    "كالسيوم": "calcium",
    "أنسولين": "insulin",
    "انسولين": "insulin",
    "أتورفاستاتين": "atorvastatin",
    "اتورفاستاتين": "atorvastatin",
    "اميلوديبين": "amlodipine",
    "فلاجيل": "flagyl",
    "مترونيدازول": "metronidazole",
}

_AR_CHAR_MAP = {
    'ا': 'a', 'أ': 'a', 'إ': 'e', 'آ': 'a',
    'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'g',
    'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'th',
    'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z',
    'ع': 'a', 'غ': 'gh', 'ف': 'f', 'ق': 'k',
    'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
    'ه': 'h', 'و': 'o', 'ي': 'y', 'ى': 'a',
    'ئ': 'e', 'ء': 'a', 'ؤ': 'o', 'ة': 'a',
}


def _normalize_search_term(term: str) -> str:
    """Convert search term to English if Arabic, or clean safe ASCII."""
    t = term.strip().lower()
    for ar_k, en_v in _ARABIC_TO_ENGLISH_DRUGS.items():
        if ar_k in t:
            return en_v

    # If term contains non-ascii characters (Arabic), transliterate
    if any(ord(ch) > 127 for ch in t):
        converted = "".join(_AR_CHAR_MAP.get(ch, "") for ch in t)
        if len(converted) >= 2:
            return converted

    return re.sub(r'["\':*+?~^|()\[\]{}]', '', t).strip()


def search_drugs_online(query: str, limit: int = 10, conn=None):
    """
    Search OpenFDA by brand name or generic name with prefix/wildcard search.
    Supports both English drug names and Arabic drug names (with automatic mapping).
    """
    if not query or len(query.strip()) < 2:
        return []

    q_safe = _normalize_search_term(query)
    if not q_safe or len(q_safe) < 2:
        return []

    api_key = get_api_key(conn)
    headers = {"User-Agent": "PharmacySystem/1.0 (HealthCare POS)"}

    # OpenFDA wildcard query
    search_expr = f'brand_name:*{q_safe}* OR generic_name:*{q_safe}*'
    params = {
        "search": search_expr,
        "limit": min(limit, 25)
    }
    if api_key:
        params["api_key"] = api_key

    try:
        resp = requests.get(OPENFDA_NDC_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results") or []
            out = []
            seen = set()
            for r in results:
                p = _format_openfda_result(r)
                if p and p["name"]:
                    key = (p["name"].lower(), p.get("strength", "").lower(), p.get("form", "").lower())
                    if key not in seen:
                        seen.add(key)
                        out.append(p)
            return out
        elif resp.status_code in (404, 400):
            return []
        else:
            logger.warning(f"OpenFDA search query returned {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error searching OpenFDA for '{query}': {e}")
        return []



def test_openfda_connection(api_key: str = None):
    """Quick test to verify connectivity to OpenFDA."""
    params = {
        "search": "brand_name:aspirin",
        "limit": 1
    }
    if api_key:
        params["api_key"] = api_key.strip()
    headers = {"User-Agent": "PharmacySystem/1.0 (HealthCare POS)"}
    try:
        resp = requests.get(OPENFDA_NDC_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            return True, "تم الاتصال بنجاح بمستودع الأدوية الدولي"
        elif resp.status_code in (401, 403):
            return False, f"مفتاح الـ API غير صالح أو تم رفض الوصول (رمز الاستجابة: {resp.status_code})"
        else:
            return False, f"فشل الاتصال: كود الاستجابة {resp.status_code}"
    except Exception as e:
        return False, f"تعذر الاتصال بمستودع الأدوية: {str(e)}"
