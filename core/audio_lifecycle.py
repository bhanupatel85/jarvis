"""Playback-drain checks independent of model turn-completion events."""

def enqueue_microphone(queue, item):
    """Run on the event loop; discard stale backlog after a network stall."""
    import asyncio
    if queue.full():
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        pass  # A live microphone must never flood the loop with callback errors.


def playback_drained(last_write, now, latency, queue_empty):
    if last_write is None or not queue_empty:
        return False
    # stream.write returns after consuming its batch; allow the device buffer
    # and a generous inter-chunk gap before reopening the echo-guarded mic.
    return now - last_write >= max(.8, min(float(latency), 1.0) + .4)
