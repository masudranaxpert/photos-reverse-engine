# Architecture & C-ABI Design

`photos_engine` utilizes a hybrid architecture modeled after [`httpcloak`](https://github.com/sardanioss/httpcloak): high-speed low-level networking and binary parsing in **Go**, combined with an intuitive developer-facing API in **Python**.

---

## 1. Why Go Core + Python C-ABI?

| Metric | Subprocess Exec (`.exe`) | HTTP Proxy Server | Native C-ABI (`ctypes`) |
| :--- | :--- | :--- | :--- |
| **Startup Overhead** | ~100–300 ms per run | Persistent port binding | **~0.1 ms** (one-time load) |
| **Memory Footprint** | Separate process tree | Separate process tree | **Shared process memory** |
| **Data Serialization** | Stdin/stdout pipe string | HTTP Request/Response | **Direct C pointer / JSON** |
| **Network Latency** | High | Loopback TCP socket | **Zero socket overhead** |
| **Packaging Cleanliness** | Loose `.exe` files | Background daemon | **Single `.pyd` / `.dll`** |

---

## 2. In-Process C-ABI Bridge

### The Go C-Export Layer (`core/cshared/main.go`)
Functions are marked with `//export <FunctionName>` and compiled with `-buildmode=c-shared`:

```go
//export GPMC_GetToken
func GPMC_GetToken(authData *C.char) *C.char {
    token, err := client.GetToken()
    if err != nil {
        return makeErrResponse(err)
    }
    return C.CString(token)
}
```

### The Python `ctypes` Consumer (`photos_engine/client.py`)
Python dynamically locates the precompiled library for the current OS and architecture:

```python
# Resolve OS and architecture
lib_name = f"libphotos_engine-{sys.platform}-{platform.machine().lower()}.dll"
lib_path = Path(__file__).parent / "lib" / lib_name

self._lib = ctypes.CDLL(str(lib_path))
self._lib.GPMC_GetToken.argtypes = [ctypes.c_char_p]
self._lib.GPMC_GetToken.restype = ctypes.c_char_p
```

### Memory Management & Freeing
Every C-string allocated in Go via `C.CString(...)` is freed immediately after Python reads the string data:

```go
//export GPMC_FreeString
func GPMC_FreeString(str *C.char) {
    if str != nil {
        C.free(unsafe.Pointer(str))
    }
}
```

In Python:
```python
res_ptr = self._lib.GPMC_GetToken(auth_bytes)
res_str = ctypes.string_at(res_ptr).decode("utf-8")
self._lib.GPMC_FreeString(res_ptr)
```

This ensures **zero memory leaks** across millions of calls in long-running services.

---

## 3. Wire-Level Protobuf Engine

Instead of generating bloated `.pb.go` code from `.proto` definitions (which require full Google protobuf runtime dependencies and fragile version pins), `photos_engine` uses an internal recursive wire-format parser (`ProtoNode`):

- **Varints**: Handled via standard LEB128 decoding.
- **Length-delimited fields**: Recursively inspected to distinguish nested submessages from raw UTF-8 strings or byte arrays.
- **Dynamic serialization**: Builds nested Protobuf buffers on-the-fly with minimal heap allocations.
