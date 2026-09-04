#!/usr/bin/env python3
"""Check MT5000 payload layout; this does not certify U-Boot compatibility."""
import hashlib
import shutil
import tarfile
from pathlib import Path


def collect(source: Path, output: Path) -> None:
    target = source / "bin/targets/mediatek/filogic"
    images = {}
    for kind in ("factory", "sysupgrade"):
        matches = list(target.glob(f"*glinet_gl-mt5000-squashfs-{kind}.bin"))
        if len(matches) != 1:
            raise SystemExit(f"Expected one MT5000 {kind} image, found {matches}")
        images[kind] = matches[0]

    with tarfile.open(images["sysupgrade"], "r:*") as archive:
        def payload(name):
            matches = [m for m in archive.getmembers()
                       if m.isfile() and m.name.endswith("/" + name)]
            if len(matches) != 1:
                raise SystemExit(f"Invalid sysupgrade {name} payload")
            return archive.extractfile(matches[0]).read()

        kernel, root = payload("kernel"), payload("root")

    # Stock layout documented in the pinned device-support commit:
    # kernel 0xe80000..0x2e80000; rootfs 0x2e80000..0x12a80000.
    kernel_limit = 32 * 1024 * 1024
    root_limit = 252 * 1024 * 1024
    if not 0 < len(kernel) < kernel_limit:
        raise SystemExit("Kernel exceeds stock kernel slot")
    if not 0 < len(root) < root_limit:
        raise SystemExit("Rootfs exceeds stock rootfs slot")
    if kernel[:4] != bytes.fromhex("d00dfeed") or root[:4] != b"hsqs":
        raise SystemExit("Expected FIT kernel and SquashFS rootfs")
    factory = images["factory"].read_bytes()
    if len(factory) != kernel_limit + len(root):
        raise SystemExit("Unexpected factory image length")
    if factory[:len(kernel)] != kernel or factory[kernel_limit:] != root:
        raise SystemExit("Factory payloads do not match sysupgrade payloads")

    output.mkdir(parents=True, exist_ok=True)
    for path in images.values():
        shutil.copy2(path, output / path.name)
    for pattern in ("*glinet_gl-mt5000*.manifest", "profiles.json"):
        for path in target.glob(pattern):
            shutil.copy2(path, output / path.name)
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in sorted(output.glob("*.bin"))]
    (output / "SHA256SUMS").write_text("".join(sums))
    print(f"Layout OK: kernel={len(kernel)}, rootfs={len(root)} bytes")
    print("Hardware boot, networking and U-Boot acceptance remain unverified.")


if __name__ == "__main__":
    collect(Path.cwd(), Path.cwd().parent / "artifacts")
