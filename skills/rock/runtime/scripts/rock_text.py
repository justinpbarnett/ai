def plural(count, noun, nouns=None):
    return f"{count} {noun if count == 1 else nouns or noun + 's'}"
