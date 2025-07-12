# api/square_webhook.py
"""
Square → Webhook → Supabase
───────────────────────────
FastAPI endpoint that receives Square Webhooks, verifies the signature,
and up-/down-dates Supabase rows.

Required ENV
────────────
SQUARE_WEBHOOK_SIGNATURE_KEY   The signature key from Square dashboard
SUPABASE_URL                   Your Supabase project URL
SUPABASE_ANON_KEY              Service role or anon key
"""

import base64
import hmac
import hashlib
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from supabase import create_client, Client as SupaClient

# ------------------------------------------------------------------ #
# 1 ▸  Globals / singletons                                          #
# ------------------------------------------------------------------ #

app = FastAPI()

supabase: SupaClient = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_ANON_KEY"],
)

_SQUARE_SIG_KEY = os.environ["SQUARE_WEBHOOK_SIGNATURE_KEY"].encode("utf-8")


# ------------------------------------------------------------------ #
# 2 ▸  Helpers                                                       #
# ------------------------------------------------------------------ #
def _verify_square_sig(
    raw_body: bytes,
    received_sig: str | None,
) -> None:
    """
    Square signs the **raw** request body (bytes) with the webhook key:

        X-Square-Signature: base64(HMAC_SHA1(key, body))

    Raise 401 if signatures don't match.
    """
    if received_sig is None:
        raise HTTPException(status_code=400, detail="Missing signature header")

    expected_hmac = hmac.new(_SQUARE_SIG_KEY, raw_body, hashlib.sha1).digest()
    expected_sig = base64.b64encode(expected_hmac).decode()

    if not hmac.compare_digest(expected_sig, received_sig):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _upsert_inventory_from_square(data: dict) -> None:
    """
    Example handler for `catalog.version.updated` or `inventory.count.updated`
    webhooks.  Adjust to match the event types you enabled.
    """
    event_type = data.get("event_type")
    obj = data.get("data", {}).get("object")

    if event_type == "inventory.count.updated":
        # Example payload path: object => inventory_count
        inv = obj.get("inventory_count", {})
        item_id = inv.get("catalog_object_id")
        loc_id = inv.get("location_id")
        qty = int(inv.get("quantity", 0))

        # Supabase table: inventory, columns: square_item_id, location_id, quantity
        supabase.table("inventory").upsert(
            {
                "square_item_id": item_id,
                "location_id": loc_id,
                "quantity": qty,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="square_item_id,location_id",
        ).execute()

    # Add more `elif` blocks for other Square events (e.g., payment.updated)


# ------------------------------------------------------------------ #
# 3 ▸  FastAPI route                                                 #
# ------------------------------------------------------------------ #
@app.post("/square/webhook")
async def square_webhook(
    request: Request,
    x_square_signature: str | None = Header(default=None, alias="x-square-signature"),
):
    """
    One unified POST endpoint for ALL Square webhook events.
    """
    raw_body: bytes = await request.body()  # must be BYTES for sig check
    _verify_square_sig(raw_body, x_square_signature)

    payload: dict = await request.json()

    try:
        _upsert_inventory_from_square(payload)
    except Exception as exc:  # noqa: BLE001
        # Log, swallow or re-raise as needed
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse({"ok": True})
