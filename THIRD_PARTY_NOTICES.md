# Third-party notices

Parsemaxxing's own code is under the PolyForm Shield License 1.0.0 (see `LICENSE` and `NOTICE`). The components below keep their own licences. This list covers the direct runtime dependencies. Each one's full licence text ships inside the installed package.

## Engine (Python)

| Package | Licence |
| --- | --- |
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic | MIT |
| psycopg, psycopg-binary | LGPL-3.0-only (used unmodified as a separate library) |
| splunk-sdk | Apache-2.0 |
| openai | Apache-2.0 |
| regex | Apache-2.0 AND CNRI-Python |
| python-multipart | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| argon2-cffi (with argon2-cffi-bindings) | MIT |
| pyotp | MIT |
| hatchling (build backend, in the image) | MIT |

The common-password list in `engine/parsemaxxing/auth/common_passwords.txt` is not a third-party file: it was compiled for this project from widely published common-password patterns (keyboard walks, digit runs, common words with years and digits), no published list was copied, and it is under the project's own licence.

## Web UI (JavaScript)

| Package | Licence |
| --- | --- |
| next | MIT |
| react, react-dom | MIT |
| @radix-ui/react-slot | MIT |
| class-variance-authority | Apache-2.0 |
| clsx | MIT |
| lucide-react | ISC |
| tailwind-merge | MIT |

## Container images

The Docker images are built on `python:3.12-slim` and `node:24-slim`, pinned by digest. Their packages keep their own licences. The engine image adds two Debian packages for encrypted backups: `age` (BSD-3-Clause) and `postgresql-client-17` (PostgreSQL Licence). The database runs the unmodified `postgres:17.11-alpine` image (PostgreSQL Licence). The optional `https` profile runs the unmodified `caddy` image (Apache-2.0). The Splunk Enterprise image (`splunk/splunk`) and the Splunk CIM add-on are not part of this repository; you accept Splunk's licence when you set the terms in `.env`.

## Build and CI tools (not shipped)

| Tool | Licence | Use |
| --- | --- | --- |
| syft (`ghcr.io/anchore/syft`) | Apache-2.0 | CycloneDX SBOM per image (`make sbom`) |
| trivy (`ghcr.io/aquasecurity/trivy`) | Apache-2.0 | Image vulnerability scan (`make scan`) |
| uv | Apache-2.0 OR MIT | Generates `engine/requirements.lock` (`make lock`) |
