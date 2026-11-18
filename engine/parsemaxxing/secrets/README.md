# secrets

The vault (design 7.5): secrets envelope-encrypted with AES-256-GCM, decrypted only at the moment of use inside the engine.

Status: built (Phase 12): `vault.py`, table `secrets` and `vault_kek` in migration 006, `parsemaxxing secrets rotate-kek`. Wired: `config.Secrets.use(name)` opens the LLM key and the Splunk tokens from the vault when the LLM client or a Splunk connection is built (`llm.api_key` at the platform, `splunk.search_token` / `splunk.deploy_token` at environment `lab`); while a field is unset the v1 variable (`LLM_API_KEY`, `SPLUNK_*_TOKEN`) is used as a transition, until `parsemaxxing settings import-env` moves it into the vault. Relay SSH key generation and expiry tracking are planned. Rules for changing this folder: [CLAUDE.md](CLAUDE.md).

## Interface

```python
from parsemaxxing.secrets import Kek, Vault, VaultError, kek_file, rotate_kek
from parsemaxxing.settings import Scope

kek = Kek.load(kek_file(os.environ))  # bootstrap only; refuses a group/world-readable file
vault = Vault(conn, kek)  # conn: ledger.store.connect(...)
sid = vault.put(Scope("lab"), "splunk.search_token", value, actor="admin")  # create or replace
with vault.use(sid, Scope("lab")) as p:  # the plaintext exists only inside this block
    headers = {"Authorization": f"Bearer {p.text()}"}
vault.info(sid, Scope("lab"))  # SecretInfo: id, name, version, updated_at/by; no value
vault.list(Scope("lab"))
rotate_kek(conn, old_kek, new_kek, actor="cli")  # one transaction
```

- `put` returns a stable id; store that id in a secret-typed setting (`SecretRef`), never the value.
- `use` and `info` take the scope explicitly. A secret of another environment or client is "no such secret in this scope".
- All failures raise `VaultError` with no value in the message: wrong KEK, altered or moved rows, missing secret.

## KEK file

- Path: bootstrap variable `PARSEMAXXING_KEK_FILE`, default `/run/secrets/pmx_kek` (a Docker secret, engine container only).
- Content: base64 of 32 random bytes on one line, e.g. `umask 077; openssl rand -base64 32 > secrets/pmx_kek; chmod 0400 secrets/pmx_kek`.
- Mode: no group or other bits (0400 or 0600); symlinks are refused. **Losing the KEK loses every secret: back it up outside the server.**

## Rotating the KEK

1. Stop the engine and workers (a running process keeps the old KEK and is refused afterwards).
2. Create the new file as above, then `parsemaxxing secrets rotate-kek --new-kek-file <new>` (reads the current KEK from `PARSEMAXXING_KEK_FILE`). Every data key is rewrapped in one transaction; values and nonces of the values are unchanged.
3. Replace the KEK file with the new one, keep the old one until the engine starts cleanly, then destroy it.
