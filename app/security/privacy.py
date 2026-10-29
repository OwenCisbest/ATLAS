"""Minimize accidentally returned contact details; never persist raw provider payloads."""
import re


def minimize(text: str) -> str:
    text = re.sub(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[email omitted]', str(text), flags=re.I)
    def redact_number(match):
        value = match.group()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or sum(c.isdigit() for c in value) < 10:
            return value
        return '[number omitted]'
    text = re.sub(r'(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)', redact_number, text)
    text = re.sub(r'\b\d{1,6}\s+[\w .-]{1,60}\s(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd)\b',
                  '[address omitted]', text, flags=re.I)
    return text
