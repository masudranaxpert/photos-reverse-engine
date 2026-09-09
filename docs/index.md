# Photos Engine Documentation

[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://python.org)
[![Go Core](https://img.shields.io/badge/go-1.22%2B-00ADD8.svg)](https://golang.org)
[![Architecture](https://img.shields.io/badge/ABI-C--Shared%20via%20ctypes-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Photos Engine** is a high-performance Google Photos mobile client library and CLI tool. It combines a compiled **native Go core engine** with **direct in-process Python C-ABI bindings (`ctypes`)**, following the packaging and performance design of [`httpcloak`](https://github.com/sardanioss/httpcloak).

---

## Key Highlights

- ⚡ **Zero-Overhead In-Process Execution**: The Go core compiles into a native C-shared library (`.dll` / `.so` / `.dylib`) loaded directly into Python memory via `ctypes`. No IPC, no subprocess spawn overhead, no local HTTP proxy latency.
- 🔗 **Instant Public Sharing**: Generates official `https://photos.app.goo.gl/...` public share links for single or batched media items using Google Photos' internal envelope endpoint.
- 📱 **Unlimited Pixel XL Backup Spoofing**: Implements Google Photos mobile device spoofing (Pixel XL hardware model & headers) to save and backup shared media without storage quota consumption.
- 📥 **Direct Stream Downloads**: Resolves direct original-quality download URLs, filenames, exact byte sizes, SHA-1 checksums, and deduplication keys.
- 🔍 **Fast Library Deduplication**: Pre-flight SHA-1 hash lookups against your Google Photos library to prevent duplicate uploads.
- 🗑️ **Permanent Deletion**: Two-step deletion protocol (Move-to-Trash followed by permanent erase) using raw deduplication keys.
- 🛠️ **Unified CLI & Python API**: Use either the command-line utility (`photos-engine`) or idiomatic Python code with type hints.

---

## Architecture Overview

```mermaid
graph TD
    subgraph Python Application Layer
        CLI["CLI Tool (photos-engine)"]
        PyApp["Python Code (photos_engine)"]
        Client["Client / Top-Level Functions"]
    end

    subgraph Native Bridge
        Ctypes["ctypes Foreign Function Interface (FFI)"]
    end

    subgraph Native Go Engine
        CShared["CGo Shared Interface (cshared/main.go)"]
        TokenMgr["TokenManager (Proactive Auto-Refresh)"]
        Protobuf["Zero-Dependency Wire Protobuf Parser"]
        NetClient["HTTP Client (Cronet User-Agent + Gzip)"]
    end

    subgraph Google Photos Endpoints
        OAuth["Google OAuth2 Token Service"]
        PaAPI["photosdata-pa.googleapis.com"]
        ShareUI["photos.app.goo.gl"]
    end

    CLI --> Client
    PyApp --> Client
    Client --> Ctypes
    Ctypes --> CShared
    CShared --> TokenMgr
    CShared --> Protobuf
    CShared --> NetClient
    TokenMgr --> OAuth
    NetClient --> PaAPI
    Client -. Scraping .-> ShareUI
```

---

## Navigation

- [Quickstart Guide](quickstart.md): Get up and running in under 3 minutes.
- [Python API Reference](api-reference.md): Detailed classes, methods, and types.
- [CLI Reference](cli-reference.md): Command-line tool commands and options.
- [Reverse Engineering Deep Dive](reverse-engineering.md): Google Photos mobile protobuf protocols, read masks, and device spoofing.
- [Architecture & C-ABI](architecture.md): How Go and Python communicate with zero overhead.
