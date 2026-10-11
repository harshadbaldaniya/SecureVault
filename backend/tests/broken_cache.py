"""A cache backend that behaves like a Redis that cannot be reached: every operation raises ConnectionError."""

import redis
from django.core.cache.backends.base import BaseCache


class BrokenCache(BaseCache):
    def __init__(self, location, params):
        super().__init__(params)

    def _down(self, *args, **kwargs):
        raise redis.exceptions.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")

    add = get = set = touch = delete = has_key = incr = decr = clear = _down
