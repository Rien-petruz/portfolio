class DecodeError(ValueError):
    """A frame that is not a well-formed, recognised market message."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
