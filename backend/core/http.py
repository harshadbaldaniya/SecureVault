from rest_framework.response import Response


def no_store(response: Response) -> Response:
    """For responses carrying one-time or decrypted secrets: forbid any caching."""
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response
