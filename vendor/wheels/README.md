# Vendored runtime wheel

`zxing_cpp-3.1.1-cp313-cp313-musllinux_1_2_x86_64.whl` is vendored because
upstream does not publish a CPython 3.13 musllinux wheel, while the LPK ships a
musl Python runtime and performs an offline install.

- Source: PyPI `zxing-cpp==3.1.1`
- Wheel SHA-256: `57cc31f6c91e3c7ebb77bb267a734ad0d2b01c6753c7341d6586886a80801077`
- Build image: `quay.io/pypa/musllinux_1_2_x86_64`
- Build: CPython 3.13 `pip wheel`, followed by `auditwheel repair --plat musllinux_1_2_x86_64`

The version remains declared in `requirements.txt`; `lzc-build.yml` includes
this directory as a local wheel source and hashes it into the wheel cache key.
