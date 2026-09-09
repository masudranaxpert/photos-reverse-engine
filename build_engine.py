"""
Build script to compile Go core engine into C-shared library inside photos_engine/lib.
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path


def build():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine

    if system == "darwin":
        ext = ".dylib"
        os_name = "darwin"
    elif system == "windows":
        ext = ".dll"
        os_name = "windows"
    else:
        ext = ".so"
        os_name = "linux"

    lib_name = f"libphotos_engine-{os_name}-{arch}{ext}"
    root_dir = Path(__file__).resolve().parent
    core_dir = root_dir / "core"
    out_dir = root_dir / "photos_engine" / "lib"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / lib_name

    print(f"Building {lib_name}...")

    env = os.environ.copy()

    # Look for LLVM-MinGW if on Windows and standard GCC fails with bigobj
    if system == "windows":
        winget_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        for p in winget_path.glob("**/llvm-mingw*/bin/gcc.exe"):
            if p.is_file():
                env["CC"] = str(p)
                env["PATH"] = f"{p.parent};{env['PATH']}"
                break

    cmd = ["go", "build", "-buildmode=c-shared", "-ldflags=-s -w", "-o", str(out_path), "./core/cshared"]
    res = subprocess.run(cmd, cwd=str(root_dir), env=env)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to build Go core: exit code {res.returncode}")

    # Remove temporary header file if created
    header_path = out_path.with_suffix(".h")
    if header_path.is_file():
        header_path.unlink()

    print(f"Successfully built: {out_path} ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    build()
