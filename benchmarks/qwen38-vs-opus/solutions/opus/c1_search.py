class Contacts:
    def __init__(self):
        self._c = []
    def add(self, name, email):
        self._c.append((name, email))
    def search(self, query: str) -> list:
        q = query.lower()
        return [(name, email) for (name, email) in self._c if q in name.lower()]
