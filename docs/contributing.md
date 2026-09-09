# Contributing & Development Guide

Guidelines for developing, testing, and building `photos_engine`.

---

## 1. Development Setup

Clone the repository and install in editable mode with development tools:

```bash
git clone https://github.com/masudranaxpert/photos-reverse-engine.git
cd photos-reverse-engine
pip install -e .
```

---

## 2. Rebuilding the Native Go Engine

To compile changes in the Go core (`core/`) into the native shared library:

### Prerequisites:
- **Go**: 1.26+ installed.
- **C Compiler**:
  - **Windows**: `llvm-mingw` (`x86_64-w64-windows-gnu-gcc`) or `mingw-w64`.
  - **Linux**: `gcc` (`build-essential`).
  - **macOS**: `clang` (`xcode-select --install`).

### One-Click Build Script:
```bash
python build_engine.py
```

This compiles `core/cshared/main.go` and outputs the shared library to:
`photos_engine/lib/libphotos_engine-<os>-<arch>.<ext>`

---

## 3. Running Self-Checks & Tests

```bash
# Verify CLI
photos-engine --help
photos-engine token

# Test Python API
python -c "import photos_engine; print(photos_engine.get_token()[:20])"
```

---

## 4. Code Guidelines

- **Go Core**: Zero external dependencies in `go.mod`. Use standard library (`crypto/sha1`, `encoding/base64`, `net/http`, `sync`, etc.).
- **Python Layer**: Pure Python wrappers using `ctypes` and standard library `dataclasses`.
- **Packaging**: Keep compiled binaries strictly inside `photos_engine/lib/`.
