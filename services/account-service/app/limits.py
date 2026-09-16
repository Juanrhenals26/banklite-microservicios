"""Limites regulatorios por pais de residencia del usuario.

Account Service aplica estos limites al abrir la cuenta, tal como exige el
documento de BankLite (restricciones regulatorias especificas por pais).
"""

from decimal import Decimal

COUNTRY_LIMITS: dict[str, dict] = {
    "CO": {"currency": "COP", "daily_limit": Decimal("5000000.00"), "monthly_limit": Decimal("50000000.00")},
    "MX": {"currency": "MXN", "daily_limit": Decimal("20000.00"), "monthly_limit": Decimal("200000.00")},
    "US": {"currency": "USD", "daily_limit": Decimal("2500.00"), "monthly_limit": Decimal("25000.00")},
    "ES": {"currency": "EUR", "daily_limit": Decimal("2000.00"), "monthly_limit": Decimal("20000.00")},
    "PE": {"currency": "PEN", "daily_limit": Decimal("8000.00"), "monthly_limit": Decimal("80000.00")},
}

SUPPORTED_COUNTRIES = tuple(COUNTRY_LIMITS.keys())


def limits_for(country: str) -> dict | None:
    return COUNTRY_LIMITS.get(country.upper())
