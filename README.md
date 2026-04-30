# Tunnel auto tests

Python/uv tests for the nginx tunnel module. Each test starts a temporary nginx
instance, starts a local backend when CONNECT needs one, runs the client
workload, and cleans up child processes.

## Requirements

- `uv`
- Python 3.13, matching `.python-version`
- a tunnel-enabled nginx binary
- `openssl` for generating local TLS material

By default the tests generate TLS material under `test/auto/certs/`, which is
git-ignored. CI can override the paths explicitly:

```sh
export NGINX_TEST_REPO_ROOT=/path/to/repo
export NGINX_TEST_NGINX=/path/to/nginx/objs/nginx
export NGINX_TEST_CERT=/path/to/example.crt
export NGINX_TEST_KEY=/path/to/example.key
```

Sync dependencies:

```sh
uv sync
```

## Smoke tests

```sh
uv run python h1_basic.py
uv run python h2_basic.py
uv run python h3_basic.py
uv run python h2_padding_basic.py
```

## Load tests

Both load tests keep many CONNECT requests in flight instead of sending a
serialized loop.

```sh
uv run python h2_load.py --requests 1000 --concurrency 100
uv run python h3_load.py --requests 1000 --concurrency 100
```

`h2_load.py` multiplexes concurrent CONNECT streams on an HTTP/2 connection.
`h3_load.py` runs concurrent HTTP/3 CONNECT streams over QUIC.

`h2_padding_basic.py` enables `tunnel_padding on`, negotiates the HTTP/2
`padding` header, sends one `PaddedData` frame through the tunnel, and verifies
that echoed upstream data is returned as `PaddedData`.

## Memory tests

```sh
uv run python h2_memory_test.py --rounds 10 --requests 1000 --concurrency 100
uv run python h3_memory_test.py --rounds 10 --requests 1000 --concurrency 100
uv run python h2_padding_memory_test.py --rounds 10 --requests 1000 --concurrency 100
```

The memory tests sample nginx `VmRSS` before and after each round. With at least
two post-warmup rounds, the test fails with exit code `2` when RSS increases by
more than 1 MiB in every post-warmup round.

`h2_padding_memory_test.py` runs the RSS check while every CONNECT request
negotiates padding and relays one padded echo payload.

## Common options

Every test accepts:

```sh
--nginx "$NGINX_TEST_NGINX"
--listen-port 3128
--backend-port 18080
```
