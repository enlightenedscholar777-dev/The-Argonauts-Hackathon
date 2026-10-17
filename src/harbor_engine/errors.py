class DomainError(Exception):
    def __init__(self, code, message, status=409, retryable=False, **details):
        self.code, self.message = code, message
        self.status, self.retryable, self.details = status, retryable, details
        super().__init__(message)
