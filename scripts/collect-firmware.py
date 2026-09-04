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
        raise SystemExit(
            f"Kernel exceeds stock kernel slot: {len(kernel)} bytes, limit {kernel_limit}")
    if not 0 < len(root) < root_limit:
        raise SystemExit(
            f"Rootfs exceeds stock rootfs slot: {len(root)} bytes, limit {root_limit}")
    if kernel[:4] != bytes.fromhex("d00dfeed") or root[:4] != b"hsqs":
        raise SystemExit(
            "Expected FIT kernel and SquashFS rootfs, got magics "
            f"{kernel[:4].hex()} / {root[:4].hex()}")
    factory = images["factory"].read_bytes()
    if factory[:len(kernel)] != kernel:
        raise SystemExit(
            f"Factory kernel differs from sysupgrade kernel ({len(kernel)} bytes)")
    # sysupgrade-tar.sh pads members to a 1 KiB multiple (dd conv=sync) while the
    # factory image appends the raw -nopad squashfs, so factory rootfs may be shorter.
    froot = factory[kernel_limit:]
    pad = len(root) - len(froot)
    if not 0 < len(froot) <= len(root):
        raise SystemExit(
            f"Unexpected factory image length: {len(factory)} bytes, "
            f"rootfs region {len(froot)} bytes, sysupgrade rootfs {len(root)} bytes")
    if froot[:4] != b"hsqs":
        raise SystemExit(
            f"Factory rootfs at {kernel_limit} lacks SquashFS magic, got {froot[:4].hex()}")
    # -nopad output ends exactly at the superblock's bytes_used (u64 LE at offset 40),
    # which pins the factory rootfs length that the zero padding above cannot.
    used = int.from_bytes(root[40:48], "little")
    if len(froot) != used:
        raise SystemExit(
            f"Factory rootfs region is {len(froot)} bytes, SquashFS bytes_used is {used}")
    if root[:len(froot)] != froot:
        raise SystemExit(
            f"Factory payloads do not match sysupgrade payloads over {len(froot)} rootfs bytes")
    if pad >= 1024 or root[len(froot):] != bytes(pad):
        raise SystemExit(
            f"Sysupgrade rootfs tail is not zero padding: {pad} extra bytes "
            f"(factory rootfs {len(froot)}, sysupgrade rootfs {len(root)})")

    output.mkdir(parents=True, exist_ok=True)
    for path in images.values():
        shutil.copy2(path, output / path.name)
    for pattern in ("*glinet_gl-mt5000*.manifest", "profiles.json"):
        for path in target.glob(pattern):
            shutil.copy2(path, output / path.name)
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in sorted(output.glob("*.bin"))]
    (output / "SHA256SUMS").write_text("".join(sums))
    print(f"Layout OK: kernel={len(kernel)}, rootfs={len(root)} bytes "
          f"(factory rootfs {len(froot)} bytes + {pad} bytes tar zero padding)")
    print("Hardware boot, networking and U-Boot acceptance remain unverified.")


if __name__ == "__main__":
    collect(Path.cwd(), Path.cwd().parent / "artifacts")
