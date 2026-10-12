from lector import muestras, parsear

assert parsear(b"5,51234,60876\r\n") == (5, 51234, 60876)
assert parsear(b"# Pulxo-UES fs=100\r\n") is None
assert parsear(b"# n,rojo,ir\r\n") is None
assert parsear(b"12,345\r\n") is None
assert parsear(b"\xff\xfe1,2,3\r\n") is None
assert parsear(b"") is None

lineas = [b"# n,rojo,ir\r\n", b"0,10,20\r\n", b"1,11,21\r\n", b"basura\r\n", b"3,13,23\r\n"]
assert list(muestras(lineas)) == [(0, 10, 20), (1, 11, 21), (3, 13, 23)]

print("OK")
