import re
import urllib.parse

PINTEREST_PATTERN = re.compile(
    r'(https?://(?:[a-zA-Z0-9_-]+\.)?pinterest\.[a-z.]+/pin/[0-9a-zA-Z_-]+/?|https?://pin\.it/[a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

def extract_pinterest_url(text: str) -> str | None:
    if not text:
        return None
    match = PINTEREST_PATTERN.search(text)
    if match:
        return match.group(1)
    return None

def test_extraction():
    samples = [
        "https://pin.it/5v9j1A2",
        "Mana bu videoni yukla: https://www.pinterest.com/pin/123456789012345/ rahmat",
        "https://in.pinterest.com/pin/87654321/",
        "https://pin.it/xyz123?utm_source=share&utm_medium=android",
        "Oddiy xabar havola yo'q"
    ]
    for sample in samples:
        url = extract_pinterest_url(sample)
        print(f"Input: {sample[:35]}... -> Extracted: {url}")

if __name__ == "__main__":
    test_extraction()
