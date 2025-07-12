# square_inventory_service.py
import os, uuid, logging, requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")
USE_PROD = os.getenv("SQUARE_USE_PROD", "false")

BASE_URL = (
    "https://connect.squareup.com" if USE_PROD.lower() == "true"
    else "https://connect.squareupsandbox.com"
)

HEADERS = {
    "Authorization": f"Bearer {SQUARE_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

app = FastAPI(title="Stitched Inventory Service")
log = logging.getLogger("uvicorn")

class InventoryPayload(BaseModel):
    size: str
    quantity: int
    comment: str | None = None

def get_location_id(name: str) -> str:
    res = requests.get(f"{BASE_URL}/v2/locations", headers=HEADERS)
    res.raise_for_status()
    for loc in res.json().get("locations", []):
        if loc["name"].strip().lower() == name.lower():
            return loc["id"]
    raise ValueError(f"Location '{name}' not found.")

def get_variation_id(item_name: str, size: str) -> str:
    res = requests.post(
        f"{BASE_URL}/v2/catalog/search-catalog-items",
        headers=HEADERS,
        json={"text_filter": item_name}
    )
    res.raise_for_status()
    for item in res.json().get("items", []):
        if item["item_data"]["name"].strip().lower() == item_name.lower():
            for var in item["item_data"]["variations"]:
                if var["item_variation_data"]["name"].strip().lower() == size.lower():
                    return var["id"]
    raise ValueError(f"Variation '{size}' not found.")

@app.post("/inventory/add")
def set_inventory(payload: InventoryPayload):
    try:
        location_id = get_location_id("Stitched PDX LLC")
        variation_id = get_variation_id("Jeans 1", payload.size)

        body = {
            "idempotency_key": str(uuid.uuid4()),
            "changes": [{
                "type": "PHYSICAL_COUNT",
                "physical_count": {
                    "reference_id": str(uuid.uuid4()),
                    "catalog_object_id": variation_id,
                    "state": "IN_STOCK",
                    "location_id": location_id,
                    "quantity": str(payload.quantity),
                    "note": payload.comment or f"Manual update: {payload.quantity}"
                }
            }],
            "ignore_unchanged_counts": True
        }

        res = requests.post(f"{BASE_URL}/v2/inventory/batch-change-inventory", headers=HEADERS, json=body)
        res.raise_for_status()
        return {"ok": True, "square_result": res.json()}

    except Exception as e:
        log.error(e)
        raise HTTPException(status_code=400, detail=str(e))
