from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = Path(os.getenv("PRODUCTS_FILE", ROOT_DIR / "products.csv"))
CSV_FIELDS = ["id", "name", "quantity", "unit"]
CSV_LOCK = Lock()


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, description="Product name")
    quantity: int = Field(ge=0, description="Initial quantity")
    unit: str = Field(min_length=1, description="Unit of measure")


class StockAdjustment(BaseModel):
    delta: int = Field(description="Signed quantity adjustment")


class Product(BaseModel):
    id: int
    name: str
    quantity: int
    unit: str


app = FastAPI(title="Inventory API")


def _ensure_csv() -> None:
    if PRODUCTS_FILE.exists() and PRODUCTS_FILE.stat().st_size > 0:
        return
    PRODUCTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PRODUCTS_FILE.open("w", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=CSV_FIELDS).writeheader()


def _read_products() -> list[dict[str, int | str]]:
    _ensure_csv()
    products: list[dict[str, int | str]] = []
    try:
        with PRODUCTS_FILE.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != CSV_FIELDS:
                raise ValueError("CSV header must be: id,name,quantity,unit")
            for row in reader:
                if not all(row.get(field) for field in CSV_FIELDS):
                    raise ValueError("CSV contains an incomplete product row")
                products.append(
                    {
                        "id": int(row["id"]),
                        "name": row["name"],
                        "quantity": int(row["quantity"]),
                        "unit": row["unit"],
                    }
                )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Invalid inventory data: {exc}") from exc
    return products


def _write_products(products: list[dict[str, int | str]]) -> None:
    PRODUCTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=PRODUCTS_FILE.parent, delete=False
    ) as temporary:
        writer = csv.DictWriter(temporary, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(products)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, PRODUCTS_FILE)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


@app.get("/inventory", response_model=list[Product])
def list_inventory() -> list[dict[str, int | str]]:
    with CSV_LOCK:
        return _read_products()


@app.post("/inventory", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate) -> dict[str, int | str]:
    name = product.name.strip()
    unit = product.unit.strip()
    if not name or not unit:
        raise HTTPException(status_code=422, detail="name and unit cannot be blank")
    with CSV_LOCK:
        products = _read_products()
        next_id = max((int(item["id"]) for item in products), default=0) + 1
        created = {"id": next_id, "name": name, "quantity": product.quantity, "unit": unit}
        products.append(created)
        _write_products(products)
        return created


@app.patch("/inventory/{product_id}", response_model=Product)
def adjust_stock(product_id: int, adjustment: StockAdjustment) -> dict[str, int | str]:
    with CSV_LOCK:
        products = _read_products()
        for product in products:
            if product["id"] == product_id:
                new_quantity = int(product["quantity"]) + adjustment.delta
                if new_quantity < 0:
                    raise HTTPException(status_code=422, detail="quantity cannot become negative")
                product["quantity"] = new_quantity
                _write_products(products)
                return product
    raise HTTPException(status_code=404, detail=f"Product {product_id} not found")


@app.get("/inventory/alerts", response_model=list[Product])
def inventory_alerts(
    threshold: Annotated[int, Query(ge=0, description="Alert below this quantity")] = 10,
) -> list[dict[str, int | str]]:
    with CSV_LOCK:
        return [product for product in _read_products() if int(product["quantity"]) < threshold]
