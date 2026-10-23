"""Ordered, bounded read concurrency; cancel and drain siblings on failure."""
import asyncio


async def ordered_map(function, items, limit):
    if limit < 1:
        raise ValueError('read concurrency must be positive')
    semaphore = asyncio.Semaphore(limit)

    async def run(item):
        async with semaphore:
            return await function(item)

    tasks = [asyncio.create_task(run(item)) for item in items]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
