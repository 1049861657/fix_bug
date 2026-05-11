class Inventory:
    def __init__(self):
        self._stock: dict[str, int] = {}

    def restock(self, sku: str, quantity: int) -> None:
        self._stock[sku] = self._stock.get(sku, 0) + quantity

    def get_stock(self, sku: str) -> int:
        return self._stock.get(sku, 0)

    def is_available(self, sku: str, quantity: int) -> bool:
        """检查库存是否足够"""
        return self._stock.get(sku, 0) > quantity

    def deduct(self, sku: str, quantity: int) -> None:
        current = self._stock.get(sku, 0)
        if current < quantity:
            raise ValueError(f"库存不足: {sku} 当前 {current}，需要 {quantity}")
        self._stock[sku] = current - quantity
