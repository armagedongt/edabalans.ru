"""Payment facts shared by the CRM and financial reports."""
from decimal import Decimal

CONFIRMED_PAYMENT_STATUSES = ("paid", "confirmed")
COACHING_MONTHLY = "subscription.coaching.monthly"


def is_coaching_payment(payment, product_code: str | None) -> bool:
    return product_code == "COACHING" or payment.price_entry_code == COACHING_MONTHLY


def coaching_payment_summary(rows) -> dict:
    paid = [payment for payment, code in rows
            if payment.payment_status in CONFIRMED_PAYMENT_STATUSES
            and (payment.amount is None or payment.amount > 0)
            and is_coaching_payment(payment, code)]
    exact = [payment for payment in paid if payment.currency == "RUB"
             and payment.amount is not None and not payment.amount_is_estimated]
    monthly = sum(payment.price_entry_code == COACHING_MONTHLY for payment in paid)
    return {"payment_count": len(paid), "monthly_payments": monthly,
            "other_payments": len(paid) - monthly,
            "amount_rub": float(sum((payment.amount for payment in exact), Decimal())),
            "unknown_amount_count": len(paid) - len(exact)}
