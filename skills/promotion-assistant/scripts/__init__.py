"""promotion-assistant engine package (stdlib-only, product-agnostic).

The skill is a thin orchestrator. All product copy, audiences, channel policy and
secrets live in a SEPARATE per-product config repo located via PROMO_CONFIG_DIR.
Nothing here contains product data or credentials.
"""
__version__ = "0.1.0"
