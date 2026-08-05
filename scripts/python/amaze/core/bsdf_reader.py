"""Reader for the `tensor_file` container measured BSDFs ship in.

EPFL RGL publishes its measurements (CC0) as Mitsuba tensor files: a
12-byte magic, a version pair, a field count, then one descriptor per
field (name, dimensions, dtype, offset, shape) followed by the raw
arrays. Parsing it here means a measurement can be turned into
shading numbers without their C++/Python reference API.

Layout, verified against a real file:

    char[12] "tensor_file\0"
    uint8    version major, minor
    uint32   field count
    per field:
        uint16 name length, char[] name
        uint16 ndim, uint8 dtype
        uint64 offset, uint64 shape[ndim]

An RGB measurement carries: version, description, phi_i, theta_i,
sigma, ndf, vndf, luminance, rgb, jacobian, valid.
"""
import struct, sys

DTYPES = {1: ('B', 1), 2: ('b', 1), 3: ('H', 2), 4: ('h', 2), 5: ('I', 4),
          6: ('i', 4), 7: ('Q', 8), 8: ('q', 8), 9: ('e', 2), 10: ('f', 4),
          11: ('d', 8)}

def read(path):
    data = open(path, 'rb').read()
    assert data[:12] == b'tensor_file\0', data[:12]
    off = 12
    vmaj, vmin = data[off], data[off+1]; off += 2
    n_fields, = struct.unpack_from('<I', data, off); off += 4
    fields = {}
    for _ in range(n_fields):
        nlen, = struct.unpack_from('<H', data, off); off += 2
        name = data[off:off+nlen].decode(); off += nlen
        ndim, = struct.unpack_from('<H', data, off); off += 2
        dtype = data[off]; off += 1
        offset, = struct.unpack_from('<Q', data, off); off += 8
        shape = struct.unpack_from('<%dQ' % ndim, data, off); off += 8*ndim
        fields[name] = (dtype, offset, shape)
    return data, (vmaj, vmin), fields

def values(data, field):
    dtype, offset, shape = field
    fmt, size = DTYPES[dtype]
    count = 1
    for s in shape: count *= s
    return struct.unpack_from('<%d%s' % (count, fmt), data, offset), shape
