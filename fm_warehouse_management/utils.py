"""Pure Python helpers for the FamilyMart thesis prototype (no Odoo import)."""
import re
import unicodedata


def normalize_name(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def normalize_column(value):
    text = unicodedata.normalize('NFKD', (value or '').strip().lower())
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', '', text.replace('đ', 'd'))


def replenish_quantity(capacity, on_shelf, available_at_source):
    return min(max(0.0, capacity - on_shelf), max(0.0, available_at_source))
