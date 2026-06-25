"""Standalone Paystack webhook signature verification test.

Requires PAYSTACK_SECRET_KEY=sk_test_lvtestkey in /app/backend/.env and a
backend restart. Run AFTER restart. The test driver script
/app/test_reports/run_paystack_sig.sh handles env mutation + restart + revert.
"""
import hmac
import hashlib
import json
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
WEBHOOK = f"{BASE_URL}/api/webhook/paystack"
SECRET = "sk_test_lvtestkey"

# These tests only run when the env mutation has been applied. The fixture skips
# them otherwise so CI is green without the manual env switch.
pytestmark = pytest.mark.skipif(
    os.environ.get("PAYSTACK_SECRET_KEY", "") != SECRET,
    reason="set PAYSTACK_SECRET_KEY=sk_test_lvtestkey + restart backend to run these tests",
)


def test_paystack_valid_signature():
    body = json.dumps({"event": "charge.success", "data": {"reference": "unknown"}}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    r = requests.post(WEBHOOK, data=body,
                      headers={"Content-Type": "application/json",
                               "x-paystack-signature": sig}, timeout=15)
    assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    d = r.json()
    assert d.get("received") is True
    assert d.get("verified") is True


def test_paystack_invalid_signature():
    body = json.dumps({"event": "charge.success", "data": {"reference": "unknown"}}).encode()
    r = requests.post(WEBHOOK, data=body,
                      headers={"Content-Type": "application/json",
                               "x-paystack-signature": "deadbeef"}, timeout=15)
    assert r.status_code == 401, f"got {r.status_code}: {r.text}"
