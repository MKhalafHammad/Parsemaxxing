"""Forward one TCP port to one fixed target, nothing else (docker-compose network relays).

Used so a container can reach exactly one port of another without sharing a network with it:
  splunk-api  engine -> Splunk management port 8089; Splunk cannot reach the engine (DK-5)
  postgres-cli  the host CLI -> PostgreSQL, only with `--profile cli` (data network is internal)
Bytes are copied as they are (TLS passes through untouched); nothing is logged but errors.

Usage: python3 tcp_forward.py LISTEN_PORT TARGET_HOST TARGET_PORT
"""

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def main(listen_port: int, host: str, port: int) -> None:
    async def handle(
        c_reader: asyncio.StreamReader, c_writer: asyncio.StreamWriter
    ) -> None:
        try:
            t_reader, t_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), 10
            )
        except (OSError, TimeoutError) as e:
            print(
                f"cannot reach {host}:{port}: {type(e).__name__}",
                file=sys.stderr,
                flush=True,
            )
            c_writer.close()
            return
        await asyncio.gather(pipe(c_reader, t_writer), pipe(t_reader, c_writer))

    server = await asyncio.start_server(handle, "0.0.0.0", listen_port)  # nosec B104
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
