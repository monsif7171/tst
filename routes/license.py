"""License routes: check status, view HWID, and activate license."""
from flask import Blueprint, request, jsonify
from licensing.manager import verify_current_license, activate_license, get_machine_id

bp = Blueprint("license", __name__)


@bp.route("/api/license/status", methods=["GET"])
def license_status():
    """Return current license status and Machine ID."""
    force = request.args.get("refresh", "").lower() == "true"
    status = verify_current_license(force=force)
    return jsonify(status)


@bp.route("/api/license/hwid", methods=["GET"])
def machine_hwid():
    """Quick endpoint to get current Machine ID."""
    return jsonify({"machine_id": get_machine_id()})


@bp.route("/api/license/activate", methods=["POST"])
def activate():
    """Activate license by pasting key or uploading license file."""
    token = ""

    # Check multipart file upload
    if "license_file" in request.files:
        f = request.files["license_file"]
        if f and f.filename:
            token = f.read().decode("utf-8", errors="ignore").strip()

    # Check JSON body
    if not token and request.is_json:
        data = request.get_json(silent=True) or {}
        token = (data.get("license_key") or data.get("key") or "").strip()

    # Check form data
    if not token:
        token = (request.form.get("license_key") or "").strip()

    if not token:
        return jsonify({"ok": False, "error": "يرجى إدخال مفتاح الترخيص أو رفع ملف license.lic"}), 400

    success, message, status_dict = activate_license(token)
    if not success:
        return jsonify({"ok": False, "error": message}), 400

    return jsonify({"ok": True, "message": message, "status": status_dict})
