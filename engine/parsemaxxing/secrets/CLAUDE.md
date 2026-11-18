# secrets/ (the vault)

Root rules in [../../../CLAUDE.md](../../../CLAUDE.md) and [../../CLAUDE.md](../../CLAUDE.md) apply.
Design: [7.5 Vault](../../../docs/design.md). Baseline rows A04-1, SEC-1 to SEC-4.

## What it does
- Stores secrets envelope-encrypted in the `secrets` table (migration 006): AES-256-GCM from
  `cryptography`, a random 256-bit data key (DEK) per secret and per version, the DEK wrapped by
  the KEK, random 96-bit nonces for both.
- Decrypts only inside `with vault.use(secret_id, scope) as p:` (sync, like the rest of the
  engine); `p.text()` / `p.reveal()` fail after the block and the buffer is overwritten.
- Loads the KEK from the file named by bootstrap `PARSEMAXXING_KEK_FILE`
  (default `/run/secrets/pmx_kek`); rewraps every DEK with `rotate_kek` /
  `parsemaxxing secrets rotate-kek --new-kek-file`.

## Invariants (do not weaken)
- No custom crypto: only `AESGCM` from `cryptography`. Nonces only from `os.urandom(12)`; a new
  DEK and nonce on every `put`. Never reuse a nonce with a key.
- AAD = `parsemaxxing-vault/1`, the kind (`data` or `dek`), and the JSON list
  `[id, environment, client, name, version]`. Anything that changes a row's identity must be in
  the AAD; changing the AAD format needs a migration that rewraps everything.
- A secret belongs to exactly one scope. Every read passes the scope; a secret of another scope
  is reported exactly like a missing one.
- KEK file: regular file, no symlink, no group or other permission bits, one line of base64 of
  exactly 32 bytes. Never read the KEK from `.env`, the database, an argument or a log.
- `vault_kek.kek_id` (HMAC fingerprint) must match before any decrypt or write; rotation
  updates it in the same transaction as the rewrap, under `LOCK TABLE secrets`.
- Nothing returns a value except `Plaintext` inside `use`. `Kek`, `Plaintext`, `Vault` redact in
  `repr`/`str` and refuse pickling. Exceptions are `VaultError` raised `from None`, with ids and
  names only, never values or key bytes.
- History: every write adds a `settings_history` row with `grp='vault'`, `redacted=true` and no
  value (enforced by a CHECK).
- The app role has no DELETE on `secrets` and cannot UPDATE `id`, scope or `name`.
- This module never reads `os.environ`; callers pass the mapping to `kek_file()`.

## Changes that need an adversarial test (tests/secrets/test_vault.py)
- Any change to sealing, opening or the AAD: tampered ciphertext, nonce, wrapped DEK, DEK nonce;
  changed version, name or scope; ciphertext and wrapped DEK moved from another row.
- KEK loading: readable modes, symlink, bad base64, wrong length, extra lines.
- Wrong KEK, with and without the `kek_id` check.
- Rotation: round trip, all-or-nothing on a failing row, refused with a non-current KEK.
- Any new path that touches a value: scan errors, logs, stdout, history and reprs for it.
