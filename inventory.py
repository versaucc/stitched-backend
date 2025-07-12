# square_inventory_service.py
import os, uuid, logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from square.client import Client

# ── env ────────────────────────────────────────────────────────────────────────
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")        # put in .env
USE_PROD              = os.getenv("SQUARE_USE_PROD", "false") # "true" to hit live data

client = Client(
    access_token=SQUARE_ACCESS_TOKEN,
    environment="production" if USE_PROD.lower() == "true" else "sandbox",
)

# ── FastAPI setup ─────────────────────────────────────────────────────────────
app = FastAPI(title="Stitched PDX inventory micro-service")
log = logging.getLogger("uvicorn")

# ── request model ─────────────────────────────────────────────────────────────
class InventoryPayload(BaseModel):
    size: str
    quantity: int          # absolute physical count
    comment: str | None = None  # optional note shown in Square dashboard

# ── helpers ───────────────────────────────────────────────────────────────────
def _get_location_id_by_name(target_name: str) -> str:
    """Return Square location_id that matches a seller-visible name."""
    res = client.locations.list_locations()
    for loc in res.body.get("locations", []):
        if loc["name"].strip().lower() == target_name.lower():
            return loc["id"]
    raise ValueError(f"Location '{target_name}' not found in Square account.")

def _find_variation_id(item_name: str, size: str) -> str:
    """Return catalog_object_id of the ITEM_VARIATION for given name/size."""
    body = {"text_filter": item_name}
    res  = client.catalog.search_catalog_items(body=body)
    items = res.body.get("items", [])
    for itm in items:
        if itm["item_data"]["name"].strip().lower() == item_name.lower():
            for var in itm["item_data"]["variations"]:
                v_data = var["item_variation_data"]
                if v_data.get("name", "").strip().lower() == size.lower():
                    return var["id"]
    raise ValueError(f"Variation '{size}' for '{item_name}' not found.")

# ── endpoint ──────────────────────────────────────────────────────────────────
@app.post("/inventory/add")
def set_inventory(payload: InventoryPayload):
    try:
        location_id     = _get_location_id_by_name("Stitched PDX LLC")
        variation_id    = _find_variation_id("Jeans 1", payload.size)

        body = {
            "idempotency_key": str(uuid.uuid4()),
            "changes": [
                {
                    "type": "PHYSICAL_COUNT",
                    "physical_count": {
                        "reference_id": str(uuid.uuid4()),
                        "catalog_object_id": variation_id,
                        "state": "IN_STOCK",
                        "location_id": location_id,
                        "quantity": str(payload.quantity),
                        "note": payload.comment or f"Manual set via API: {payload.quantity}",
                    },
                }
            ],
            "ignore_unchanged_counts": True,
        }

        client.inventory.batch_change_inventory(body)
        return {"ok": True, "message": "Inventory updated."}

    except Exception as exc:
        log.error(exc)
        raise HTTPException(status_code=400, detail=str(exc))
