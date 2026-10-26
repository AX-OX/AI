"""Bounded local demo traffic. Never sends requests to the AX Agent or external hosts."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def send(base, path, body):
    request = Request(base + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError):
        return 0


def run(base, scenario, requests, concurrency, interval):
    url = urlparse(base)
    if url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1'} or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment:
        raise ValueError('Only a localhost HTTP demo server is allowed')
    if not 1 <= requests <= 1000 or not 1 <= concurrency <= 16 or not 0 <= interval <= 1:
        raise ValueError('Limits: requests 1..1000, concurrency 1..16, interval 0..1s')
    control = {'delay_ms': 500 if scenario == 'slow' else 0, 'error_every': 2 if scenario == 'failure' else 0}
    configured = scenario in {'slow', 'failure'}
    if configured and send(base, '/demo/control', control) != 200:
        raise RuntimeError('Enable demo controls on the local Iris server first')

    def predict(i):
        sleep(interval)
        invalid = scenario == 'invalid' or (scenario == 'mixed' and i % 5 == 0)
        started = perf_counter()
        status = send(base, '/predict', {'features': [1, 2] if invalid else [5.1, 3.5, 1.4, .2]})
        return status, perf_counter() - started

    started = perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(predict, range(requests)))
    finally:
        if configured and send(base, '/demo/control', {'delay_ms': 0, 'error_every': 0}) != 200:
            print('WARNING: demo controls could not be reset; restart model service')
    latencies = sorted(duration for _, duration in results)
    return {'scenario': scenario, 'requests': requests, 'concurrency': concurrency,
            'seconds': round(perf_counter() - started, 3),
            'statuses': dict(Counter(str(status) for status, _ in results)),
            'p95_ms': round(latencies[max(0, int(len(latencies) * .95) - 1)] * 1000, 2)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8001')
    parser.add_argument('--scenario', choices=['normal', 'invalid', 'mixed', 'load', 'slow', 'failure'], default='normal')
    parser.add_argument('--requests', type=int)
    parser.add_argument('--concurrency', type=int)
    parser.add_argument('--interval', type=float, default=.1)
    args = parser.parse_args()
    defaults = {'normal': (100, 2), 'invalid': (100, 2), 'mixed': (100, 4),
                'load': (500, 16), 'slow': (200, 8), 'failure': (300, 4)}
    requests, concurrency = defaults[args.scenario]
    print(json.dumps(run(args.url.rstrip('/'), args.scenario,
                         args.requests if args.requests is not None else requests,
                         args.concurrency if args.concurrency is not None else concurrency, args.interval), indent=2))
