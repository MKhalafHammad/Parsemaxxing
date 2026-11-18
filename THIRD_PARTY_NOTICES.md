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

The Docker images are built on `python:3.12-slim` and `node:24-slim`. Their packages keep their own licences. The Splunk Enterprise image (`splunk/splunk`) and the Splunk CIM add-on are not part of this repository; you accept Splunk's licence when you set the terms in `.env`.
