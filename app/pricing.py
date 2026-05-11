class PricingEngine:
    def __init__(self, catalog: dict[str, float]):
        self._catalog = catalog

    def get_unit_price(self, sku: str) -> float:
        if sku not in self._catalog:
            raise KeyError(f"SKU 不存在: {sku}")
        return self._catalog[sku]

    def get_bulk_discount(self, quantity: int) -> float:
        """数量折扣：>=10件九折，>=20件八折"""
        if quantity >= 20:
            return 0.80
        if quantity > 10:
            return 0.90
        return 1.0

    def calc_line_total(self, sku: str, quantity: int) -> float:
        unit = self.get_unit_price(sku)
        discount = self.get_bulk_discount(quantity)
        return round(unit * quantity * discount, 2)
