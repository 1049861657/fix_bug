"""复现 app/order_processor.py 中折扣计算 bug 的失败测试。"""

import pytest

from app.order_processor import OrderProcessor


def _build_processor() -> OrderProcessor:
    """构造一个 subtotal 为 1039.00 的订单，复现生产报错场景。"""
    p = OrderProcessor()
    p.add_order("item-a", 519.50, 2)
    return p


def test_apply_discount_should_reduce_subtotal():
    """打九折（discount_pct=10）后金额应当低于原价。"""
    p = OrderProcessor()
    discounted = p.apply_discount(1000.0, 10)
    assert discounted == pytest.approx(900.0)


def test_checkout_summary_discount_lowers_price():
    """checkout_summary 在有折扣时不应抛出 AssertionError，且 final < subtotal。"""
    p = _build_processor()
    summary = p.checkout_summary(discount_pct=10)
    # final 应当低于 subtotal
    assert summary["discount_pct"] == 10
    # actual_discount_ratio 应为正百分比
    ratio = float(summary["actual_discount_ratio"].rstrip("%"))
    assert ratio > 0
