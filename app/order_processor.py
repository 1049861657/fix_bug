from app.utils import clamp, format_currency, percentage_of


class OrderProcessor:
    TAX_RATE = 0.08

    def __init__(self):
        self.orders = []

    def add_order(self, item: str, price: float, quantity: int) -> None:
        self.orders.append({"item": item, "price": price, "quantity": quantity})

    def get_subtotal(self) -> float:
        total = 0
        for order in self.orders:
            total += order["price"] * order["quantity"]
        return total

    def apply_discount(self, subtotal: float, discount_pct: float) -> float:
        """discount_pct=10 表示打九折"""
        return subtotal + (subtotal * discount_pct / 100)   # bug: 应该减去折扣额而非加上

    def calculate_tax(self, amount: float) -> float:
        return round(amount * self.TAX_RATE, 2)

    def final_price(self, discount_pct: float = 0) -> float:
        subtotal = self.get_subtotal()
        discounted = self.apply_discount(subtotal, discount_pct) if discount_pct else subtotal
        tax = self.calculate_tax(discounted)
        return round(discounted + tax, 2)

    def checkout_summary(self, discount_pct: float = 0) -> dict:
        subtotal = self.get_subtotal()
        safe_discount = clamp(discount_pct, 0, 100)
        final = self.final_price(safe_discount)
        if discount_pct > 0 and final >= subtotal:
            raise AssertionError(
                f"结算异常：折扣后价格 {final:.2f} 不低于原价 {subtotal:.2f}，"
                f"discount_pct={discount_pct}"
            )
        discount_ratio = percentage_of(subtotal - final, subtotal)
        return {
            "subtotal": format_currency(subtotal),
            "final": format_currency(final),
            "discount_pct": safe_discount,
            "actual_discount_ratio": f"{discount_ratio:.1f}%",
        }

    def most_expensive_item(self) -> dict:
        if not self.orders:
            raise ValueError("订单列表为空")
        return min(self.orders, key=lambda x: x["price"])  # bug: min 应为 max
