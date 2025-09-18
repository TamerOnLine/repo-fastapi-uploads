# scripts/generate_jwt_keys.py
from __future__ import annotations

import os
from pathlib import Path
import secrets
import argparse
import sys

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
except Exception as e:
    print("This script needs 'cryptography' package. Install it with:\n  pip install cryptography")
    sys.exit(1)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def save(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def gen_hs256(secret_len: int = 64) -> str:
    # URL-safe random secret
    return secrets.token_urlsafe(secret_len)


def gen_rs256(private_path: Path, public_path: Path, key_size: int = 2048) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size, backend=default_backend())
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    save(private_path, priv_pem)
    save(public_path, pub_pem)


def gen_es256(private_path: Path, public_path: Path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1(), backend=default_backend())  # P-256
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    save(private_path, priv_pem)
    save(public_path, pub_pem)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JWT keys/secrets for HS256 / RS256 / ES256.")
    parser.add_argument("--dir", default="secrets", help="Directory to store generated keys (default: secrets)")
    parser.add_argument("--hs", action="store_true", help="Generate HS256 random secret")
    parser.add_argument("--rs", action="store_true", help="Generate RS256 keypair")
    parser.add_argument("--es", action="store_true", help="Generate ES256 (P-256) keypair")
    parser.add_argument("--all", action="store_true", help="Generate all types")
    args = parser.parse_args()

    out_dir = Path(args.dir)
    ensure_dir(out_dir)

    if not (args.hs or args.rs or args.es or args.all):
        parser.print_help()
        print("\nNo option provided. Use --hs, --rs, --es or --all.")
        sys.exit(1)

    print(f"Output directory: {out_dir.resolve()}")

    if args.hs or args.all:
        secret = gen_hs256()
        hs_env = [
            "APP_JWT_ALGORITHM=HS256",
            f"APP_JWT_SECRET={secret}",
            "APP_JWT_EXPIRE_MINUTES=1440",
        ]
        print("\n# Add to .env (HS256):")
        print("\n".join(hs_env))

    if args.rs or args.all:
        priv = out_dir / "jwt_rsa_private.pem"
        pub = out_dir / "jwt_rsa_public.pem"
        gen_rs256(priv, pub)
        rs_env = [
            "APP_JWT_ALGORITHM=RS256",
            f"APP_JWT_PRIVATE_KEY_PATH={priv.as_posix()}",
            f"APP_JWT_PUBLIC_KEY_PATH={pub.as_posix()}",
            "APP_JWT_EXPIRE_MINUTES=1440",
        ]
        print("\n# Add to .env (RS256):")
        print("\n".join(rs_env))

    if args.es or args.all:
        priv = out_dir / "jwt_ec_private.pem"
        pub = out_dir / "jwt_ec_public.pem"
        gen_es256(priv, pub)
        es_env = [
            "APP_JWT_ALGORITHM=ES256",
            f"APP_JWT_PRIVATE_KEY_PATH={priv.as_posix()}",
            f"APP_JWT_PUBLIC_KEY_PATH={pub.as_posix()}",
            "APP_JWT_EXPIRE_MINUTES=1440",
        ]
        print("\n# Add to .env (ES256):")
        print("\n".join(es_env))

    print("\nDone. Keep your private keys secret (do NOT commit them).")


if __name__ == "__main__":
    main()
