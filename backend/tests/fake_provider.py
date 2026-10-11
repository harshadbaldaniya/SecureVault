from apps.vault.keys import EnvKeyProvider


class CountingProvider(EnvKeyProvider):
    """Stands in for a KMS-backed provider: proves vault code only talks to the KeyProvider interface."""

    calls: list[str] = []

    def wrap(self, key, aad):
        self.calls.append("wrap")
        return super().wrap(key, aad)

    def unwrap(self, token, aad):
        self.calls.append("unwrap")
        return super().unwrap(token, aad)

    def blind_index(self, data, *, version=None):
        self.calls.append("blind_index")
        return super().blind_index(data, version=version)
