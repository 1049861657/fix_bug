from __future__ import annotations

from dataclasses import dataclass, field

from app.inventory import Inventory
from app.pricing import PricingEngine


@dataclass
class OrderItem:
    sku: str
    quantity: int


@dataclass
class Order:
    order_id: str
    items: list[OrderItem] = field(default_factory=list)
    total: float = 0.0
    status: str = "pending"


class OrderProcessor:
    def __init__(self, inventory: Inventory, pricing: PricingEngine):
        self.inventory = inventory
        self.pricing = pricing

    def create_order(self, order_id: str, items: list[dict]) -> Order:
        """
        items: [{"sku": "A001", "quantity": 3}, ...]
        """
        order = Order(order_id=order_id)

        for item in items:
            sku = item["sku"]
            qty = item["quantity"]

            if not self.inventory.is_available(sku, qty):
                raise AssertionError(
                    f"Order {order_id} rejected: SKU '{sku}' qty={qty} unavailable, "
                    f"but stock shows {self.inventory.get_stock(sku)} units"
                )

            line_total = self.pricing.calc_line_total(sku, qty)
            order.items.append(OrderItem(sku=sku, quantity=qty))
            order.total += line_total

        order.total = round(order.total, 2)
        order.status = "confirmed"

        for item in order.items:
            self.inventory.deduct(item.sku, item.quantity)

        return order
