"""Traspaso de fotos del ensayo compartido: las pasadas frecuentes no repiten pedidos a Drive."""
import sharing


class FakeDB:
    def __init__(self):
        self.s = {"share_folder": "F", "share_owner": "yo@x.cl"}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def set_setting(self, k, v):
        self.s[k] = v


class FakeDrive:
    account = "yo@x.cl"

    def __init__(self):
        self.db = FakeDB()
        self.calls = []
        self.pending = {"f2"}
        self.files = ["f1", "f2"]

    def _call(self, method, url, body=None, ctype=None):
        self.calls.append((method, url))
        if "/F/permissions" in url:
            return {"permissions": [{"type": "user", "emailAddress": "otra@x.cl"},
                                    {"type": "user", "emailAddress": "yo@x.cl"}]}
        if method == "PATCH":
            fid = url.split("/files/")[1].split("/")[0]
            self.pending.discard(fid)
            self.files.remove(fid)          # ya es mío: deja de aparecer como de la otra persona
            return {}
        if "/permissions" in url:
            fid = url.split("/files/")[1].split("/")[0]
            return {"permissions": [{"id": "p", "emailAddress": "yo@x.cl", "pendingOwner": fid in self.pending}]}
        return {"files": [{"id": f} for f in self.files]}


def test_quick_pass_skips_seen_files():
    d = FakeDrive()
    assert sharing.accept_transfers(d, full=True) == 1
    first = len(d.calls)
    d.calls.clear()
    assert sharing.accept_transfers(d, full=False) == 0
    # pasada rápida: sin integrantes ni permisos de archivos ya vistos, solo la lista
    assert len(d.calls) == 1 and first > 3
    d.pending.add("f3")
    d.files.append("f3")
    assert sharing.accept_transfers(d, full=False) == 1      # el archivo nuevo sí se revisa
