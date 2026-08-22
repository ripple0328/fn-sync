# Inspecting and building the FN Sync controller

The controller source used by the bundled executables is included in this
directory. `entrypoint.py` dispatches to `fnsync.py` and to the adjacent
`scripts/fn_sync_discover.py` helper.

GitHub Actions builds each architecture on a native Ubuntu 24.04 runner with
Python 3.13 and PyInstaller 6.22.0:

```sh
python3 -m pip install -r controller/requirements-build.txt
./controller/build-runtime.sh amd64 ./dist
```

Use `arm64` on an AArch64 machine. `BUILD-PROVENANCE.json` records the exact
source commit, workflow run, source hashes, and binary hashes for every
published commit. GitHub also signs a SLSA build-provenance attestation for
each binary. Verify a downloaded plugin checkout with:

```sh
sha256sum -c runtime/SHA256SUMS
gh attestation verify runtime/bin/fn-sync-runtime-amd64 --repo ripple0328/fn-sync
```

The PyInstaller output is not claimed to be bit-for-bit reproducible across
different host toolchains. The signed attestation instead binds the exact
published bytes to the public source commit and GitHub Actions build.
