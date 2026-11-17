"""A non-blocking process lock, released automatically when the file closes."""
import os

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


def acquire(lock):
    if os.name == 'nt':
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise BlockingIOError('Another Notes worker owns this lock') from error
    else:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
