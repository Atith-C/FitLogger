"""Caps on the endpoints that send email.

Every one of these hands an attacker a way to put messages in someone else's
inbox: signup, resend-verification and password recovery all mail an address
chosen by whoever submitted the form. Uncapped, they are a spam cannon pointed
at a stranger and a way to burn the daily sending quota, after which no real
user can verify or recover anything.

Counters live in the database cache rather than local memory: on serverless
each request may land in a different instance, so an in-memory counter would
reset constantly and cap nothing.
"""

from django.core.cache import cache

HOUR = 60 * 60


def client_ip(request):
    """The caller's address.

    Vercel terminates the connection and puts the real client first in
    X-Forwarded-For, so REMOTE_ADDR alone would see one proxy address for
    every visitor and rate-limit the whole site as a single user.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def over_limit(key, limit, window=HOUR):
    """Record one use of `key` and report whether it has gone over `limit`.

    A fixed window: the count expires `window` seconds after the first use.

    ponytail: a fixed window lets a burst straddle the boundary and get up to
    twice the limit in quick succession. That is fine for slowing down mail
    floods; swap in a sliding window only if the caps stop holding.
    """
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        # The entry expired between the add and the incr.
        cache.set(key, 1, window)
        count = 1

    return count > limit
