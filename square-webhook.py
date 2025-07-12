# square_webhook.py
import base64, hmac, hashlib, os, requests
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_TABLE = "inventory"

SQUARE_SIG_KEY = os.environ["SQUARE_WEBHOOK_SIGNATURE_KEY"].encode("utf-8")

def verify_signature(raw_body: bytes, received_sig: str | None):
    if received_sig is None:
        raise HTTPException(status_code=400, detail="Missing Square signature header")

    expected = base64.b64encode(hmac.new(SQUARE_SIG_KEY, raw_body, hashlib.sha1).digest()).decode()
    if not hmac.compare_digest(expected, received_sig):
        raise HTTPException(status_code=401, detail="Invalid Square signature")

def upsert_inventory(inv: dict):
    row = {
        "square_item_id": inv.get("catalog_object_id"),
        "location_id": inv.get("location_id"),
        "quantity": int(inv.get("quantity", 0)),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        },
        json=[row]
    )
    res.raise_for_status()

@app.post("/square/webhook")
async def webhook(
    request: Request,
    x_square_signature: str | None = Header(default=None, alias="x-square-signature"),
):
    raw_body = await request.body()
    verify_signature(raw_body, x_square_signature)

    data = await request.json()
    if data.get("event_type") == "inventory.count.updated":
        inv = data.get("data", {}).get("object", {}).get("inventory_count", {})
        try:
            upsert_inventory(inv)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({"ok": True})
