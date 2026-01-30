"""
Formatting utilities for consistent number display with thousand separators
"""
from typing import Optional

def fmt_int(x: Optional[float], locale: str = "tr") -> str:
    """
    Format integer with thousand separator
    
    Args:
        x: Number to format
        locale: 'tr' for Turkish (.), 'en' for English (,)
    
    Returns:
        Formatted string: "1.000" or "1,000"
    """
    if x is None:
        return "-"
    
    sep = "." if locale == "tr" else ","
    
    # Round to integer
    num = int(round(x))
    
    # Format with separator
    return f"{num:,}".replace(",", sep)


def fmt_float(x: Optional[float], decimals: int = 2, locale: str = "tr") -> str:
    """
    Format float with thousand separator
    
    Args:
        x: Number to format
        decimals: Number of decimal places
        locale: 'tr' for Turkish (.), 'en' for English (,)
    
    Returns:
        Formatted string: "1.234,56" or "1,234.56"
    """
    if x is None:
        return "-"
    
    if locale == "tr":
        # Turkish: 1.234,56
        int_part = int(x)
        dec_part = abs(x - int_part)
        int_str = f"{int_part:,}".replace(",", ".")
        dec_str = f"{dec_part:.{decimals}f}".split(".")[1]
        return f"{int_str},{dec_str}"
    else:
        # English: 1,234.56
        return f"{x:,.{decimals}f}"


def fmt_usd(x: Optional[float], locale: str = "tr") -> str:
    """Format USD amount"""
    if x is None:
        return "-"
    return f"${fmt_int(x, locale='en')}"


def fmt_try(x: Optional[float], locale: str = "tr") -> str:
    """Format TRY amount"""
    if x is None:
        return "-"
    return f"₺{fmt_int(x, locale)}"


def fmt_pct(x: Optional[float], decimals: int = 1) -> str:
    """Format percentage"""
    if x is None:
        return "-"
    return f"%{x * 100:.{decimals}f}"


def fmt_m2(x: Optional[float], locale: str = "tr") -> str:
    """Format square meters"""
    if x is None:
        return "-"
    return f"{fmt_int(x, locale)} m²"


# Compact versions for tables
def fmt_usd_compact(x: Optional[float]) -> str:
    """Compact USD format for tables"""
    if x is None:
        return "-"
    
    if x >= 1_000_000:
        return f"${x/1_000_000:.1f}M"
    elif x >= 1_000:
        return f"${x/1_000:.0f}K"
    else:
        return f"${x:.0f}"


def fmt_try_compact(x: Optional[float]) -> str:
    """Compact TRY format for tables"""
    if x is None:
        return "-"
    
    if x >= 1_000_000:
        return f"₺{x/1_000_000:.1f}M"
    elif x >= 1_000:
        return f"₺{x/1_000:.0f}K"
    else:
        return f"₺{x:.0f}"

