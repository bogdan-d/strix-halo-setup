class Contacts:
    def __init__(self):
        self._c = []
    def add(self, name, email):
        self._c.append((name, email))
    def search(self, query: str) -> list:
        q = query.lower()
        return [(n, e) for n, e in self._c if q in n.lower()]
