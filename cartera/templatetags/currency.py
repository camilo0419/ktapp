# cartera/templatetags/currency.py
from django import template
register = template.Library()

@register.filter
def cop(value):
    try:
        value = float(value)
        return f"${value:,.0f}".replace(",", ".")
    except Exception:
        return value
