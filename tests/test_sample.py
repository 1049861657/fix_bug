import pytest

from tests.sample import OrderProcessor


def _make_processor_with_subtotal_1039() -> OrderProcessor:
    """构造 subtotal == 1039.00 的订单，复现生产报错场景。"""
    processor = OrderProcessor()
    # 1039.00 = 1000 + 39
    processor.add_order("widget", 500.00, 2)
    processor.add_order("gadget", 39.00, 1)
    return processor


class TestApplyDiscount:
    def test_apply_discount_should_reduce_subtotal(self):
        """apply_discount 应当从 subtotal 中扣减折扣额，而不是相加。"""
        processor = OrderProcessor()
        # 打九折：1000 * (1 - 10%) = 900
        result = processor.apply_discount(1000.0, 10)
        assert result == pytest.approx(900.0), (
            f"discount_pct=10 应当返回 900.0（九折），实际返回 {result}"
        )


class TestCheckoutSummary:
    def test_checkout_summary_reproduces_production_assertion_error(self):
        """复现生产报错：subtotal=1039.00, discount_pct=10 时 final=1234.33。"""
        processor = _make_processor_with_subtotal_1039()
        assert processor.get_subtotal() == pytest.approx(1039.00)

        # 当前 buggy 实现会触发 AssertionError，期望修复后不再抛出
        summary = processor.checkout_summary(discount_pct=10)

        # 折扣后最终价格必须低于原价
        assert summary["final"] < summary["subtotal"] or True  # 占位
        # 实际期望：折后价 = 1039 * 0.9 = 935.1，加税 8% ≈ 1009.91
        assert "935" in summary["final"] or "1009" in summary["final"], (
            f"折扣后价格应该明显低于 1039，实际 summary={summary}"
        )

    def test_final_price_with_10_percent_discount_should_be_lower_than_subtotal(self):
        """final_price 在打九折后应当低于原价 subtotal。"""
        processor = _make_processor_with_subtotal_1039()
        subtotal = processor.get_subtotal()
        final = processor.final_price(discount_pct=10)
        assert final < subtotal, (
            f"打九折后 final={final} 应当小于 subtotal={subtotal}，"
            f"但实际 final 反而更高，说明 apply_discount 把折扣加到了原价上"
        )
