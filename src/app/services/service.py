from datetime import datetime
import json
import logging

from redis import asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.app.exceptions import AccountNotFoundError, DatabaseError
from src.app.models.model import Account, Transaction
from src.app.observability.metrics import TRANSACTIONS_CREATED, TRANSACTION_AMOUNT_PAISE
from src.app.schemas.schema import CreateAccount, CreateTransaction

log = logging.getLogger(__name__)

# TTL (seconds) on every cached value. This is the *correctness* backstop: even if
# an invalidation is ever missed (a code path we forgot, or a crash between the DB
# commit and the cache DELETE), a stale value can only live this long. It is NOT a
# substitute for maxmemory-lru — LRU bounds *memory* and never evicts a hot key,
# which is exactly the key most likely to go stale. Keep both.
CACHE_TTL_SECONDS = 60

# --- Single-flight (cache-stampede prevention) --------------------------------
# When a hot key goes cold and many requests miss at the same instant, we do NOT
# want all of them to hit Postgres: that herd of identical queries would fill
# PgBouncer's server pool (default_pool_size=90) and starve every other endpoint.
# Instead the FIRST misser takes a short distributed lock and does the single DB
# read; the rest wait briefly and then read the value it cached. The lock lives in
# Redis (not in-process) so it coalesces across ALL app replicas onto one query.
_LOCK_TIMEOUT = 5   # lock auto-expires after 5s so a crashed holder can't wedge the key forever
_LOCK_WAIT = 2      # a waiter blocks up to 2s trying to acquire, then falls back to a direct DB read
_MISS = object()    # sentinel: distinguishes "key absent / cache unavailable" from a cached None/[]


async def _cached_single_flight(redis, key, loader, serialize, deserialize):
    """Cache-aside read guarded by a distributed single-flight lock.

    - loader():    async callable that reads the source of truth (Postgres) and
                   returns the domain object. Raises domain/DatabaseError as usual.
    - serialize(obj) -> str | None : JSON to cache; None means "do not cache".
    - deserialize(str) -> value    : rebuild the return value from cached JSON.

    A cache/lock failure never breaks the request — it degrades to a direct DB read.
    """
    async def _try_cache():
        try:
            raw = await redis.get(key)
        except RedisError as e:
            log.warning("redis GET %s failed, falling back to DB: %s", key, e)
            return _MISS
        return deserialize(raw) if raw is not None else _MISS

    # 1. Fast path — value already cached (this is the common case; unchanged cost).
    hit = await _try_cache()
    if hit is not _MISS:
        return hit

    # 2. Cold key: try to become the single flight that rebuilds it.
    lock = redis.lock(f"lock:{key}", timeout=_LOCK_TIMEOUT, blocking=True, blocking_timeout=_LOCK_WAIT)
    try:
        acquired = await lock.acquire()
    except RedisError as e:
        log.warning("redis LOCK %s failed: %s", key, e)
        acquired = False

    if acquired:
        try:
            # Double-check: if we queued behind the winner, the value is warm now,
            # so we skip the DB entirely. Only the true winner sees a miss here.
            hit = await _try_cache()
            if hit is not _MISS:
                return hit
            obj = await loader()                       # the ONE database read
            payload = serialize(obj)
            if payload is not None:
                try:
                    await redis.set(key, payload, ex=CACHE_TTL_SECONDS)
                except RedisError as e:
                    log.warning("redis SET %s failed: %s", key, e)
            return obj
        finally:
            try:
                await lock.release()
            except Exception:
                pass  # lock may have already expired mid-flight; harmless

    # 3. Couldn't acquire within _LOCK_WAIT (or Redis is down): bounded fallback to
    #    the DB. Worst case a handful of requests reach Postgres — still capped by
    #    PgBouncer — instead of blocking forever on a dead lock holder.
    return await loader()


class TransactionService:

    def __init__(self, session: AsyncSession, redis: aioredis.Redis):
        self.session = session
        self.redis = redis

    async def create_transaction(self, transaction: CreateTransaction):
        try:
            delta = transaction.amount if transaction.type == "credit" else -transaction.amount

            # Atomic, in-DB balance update instead of read-modify-write. The
            # database evaluates `balance_paise + delta` at execution time while
            # holding the row lock, so two concurrent writers to the same account
            # can't read the same stale balance and clobber each other (no lost
            # update), and the row is locked for a far shorter window than when we
            # loaded the Account object and mutated it in Python.
            result = await self.session.execute(
                update(Account)
                .where(Account.id == transaction.account_id)
                .values(balance_paise=Account.balance_paise + delta)
            )

            # A blind UPDATE that matched no row => the account doesn't exist.
            # Bail out here (before INSERTing the transaction) to preserve the 404
            # and avoid a foreign-key violation.
            if result.rowcount == 0:
                log.warning("create_transaction: account %s not found", transaction.account_id)
                raise AccountNotFoundError(f"Account {transaction.account_id} not found")

            new_transaction = Transaction(
                account_id=transaction.account_id,
                type=transaction.type,
                amount_paise=transaction.amount,
                description=transaction.description,
                created_at=datetime.now(),
                occured_at=transaction.occured_at
            )

            self.session.add(new_transaction)
            await self.session.commit()
            await self.session.refresh(new_transaction)
        except AccountNotFoundError:
            # Domain error — already logged; let it propagate to the handler.
            raise
        except (SQLAlchemyError, OSError) as e:
            # OSError (e.g. socket.gaierror when the DB host can't be resolved,
            # or ConnectionError) is raised on a *fresh* connect when the DB is
            # down — it is NOT a SQLAlchemyError, so we must catch it too.
            # Rollback itself can fail while the DB is unreachable; don't let
            # that mask the real error.
            try:
                await self.session.rollback()
            except Exception:
                pass
            log.exception("create_transaction: database error for account %s", transaction.account_id)
            raise DatabaseError("Failed to create transaction") from e

        # Invalidate the caches this write just made stale: the account's balance
        # changed, and its transaction list grew. Best-effort — a cache outage must
        # not fail a write that already committed to the source of truth.
        await self._invalidate(transaction.account_id)

        # Record business metrics only after a successful commit.
        TRANSACTIONS_CREATED.labels(type=transaction.type).inc()
        TRANSACTION_AMOUNT_PAISE.labels(type=transaction.type).inc(transaction.amount)
        log.info(
            "transaction created: id=%s account=%s type=%s amount=%s",
            new_transaction.id, transaction.account_id, transaction.type, transaction.amount,
        )

        return new_transaction

    async def _invalidate(self, account_id: int):
        try:
            await self.redis.delete(f"account:{account_id}", f"transactions:{account_id}")
        except RedisError as e:
            log.warning("redis DEL for account %s failed (cache may be briefly stale): %s", account_id, e)

    async def get_transaction_by_account_id(self, account_id: int):
        async def loader():
            try:
                account = await self.session.get(Account, account_id)
                if not account:
                    log.warning("get_transaction: account %s not found", account_id)
                    raise AccountNotFoundError(f"Account {account_id} not found")

                statement = select(Transaction).where(Transaction.account_id == account_id)
                result = await self.session.exec(statement)
                return result.all()
            except AccountNotFoundError:
                raise
            except (SQLAlchemyError, OSError) as e:
                try:
                    await self.session.rollback()
                except Exception:
                    pass
                log.exception("get_transaction: database error for account %s", account_id)
                raise DatabaseError("Failed to fetch transactions") from e

        # model_dump(mode="json") turns UUIDs and datetimes into JSON-safe strings.
        # On a hit we return the list of dicts directly; FastAPI serializes it the
        # same as the list of Transaction objects the loader returns on a miss.
        return await _cached_single_flight(
            self.redis,
            f"transactions:{account_id}",
            loader,
            lambda txns: json.dumps([t.model_dump(mode="json") for t in txns]),
            lambda raw: json.loads(raw),
        )


class AccountService:
    def __init__(self, session: AsyncSession, redis: aioredis.Redis):
        self.session = session
        self.redis = redis

    async def get_account_by_id(self, account_id: int):
        async def loader():
            try:
                return await self.session.get(Account, account_id)
            except (SQLAlchemyError, OSError) as e:
                # OSError (e.g. socket.gaierror when the DB host can't be resolved,
                # or ConnectionError) is raised on a *fresh* connect when the DB is
                # down — it is NOT a SQLAlchemyError, so we must catch it too.
                try:
                    await self.session.rollback()
                except Exception:
                    pass
                log.exception("get_account: database error for account %s", account_id)
                raise DatabaseError("Failed to fetch account") from e

        # Only cache a real account; a missing account serializes to None (not
        # cached) so it can't poison the cache with a negative.
        return await _cached_single_flight(
            self.redis,
            f"account:{account_id}",
            loader,
            lambda acc: acc.model_dump_json() if acc is not None else None,
            lambda raw: Account(**json.loads(raw)),
        )

    async def create_account(self, data: CreateAccount):
        try:
            account = Account(balance_paise=data.balance_paise)
            self.session.add(account)
            await self.session.commit()
            await self.session.refresh(account)
        except (SQLAlchemyError, OSError) as e:
            # OSError (e.g. socket.gaierror when the DB host can't be resolved,
            # or ConnectionError) is raised on a *fresh* connect when the DB is
            # down — it is NOT a SQLAlchemyError, so we must catch it too.
            # Rollback itself can fail while the DB is unreachable; don't let
            # that mask the real error.
            try:
                await self.session.rollback()
            except Exception:
                pass
            log.exception("create_account: database error")
            raise DatabaseError("Failed to create account") from e

        log.info("account created: id=%s balance=%s", account.id, account.balance_paise)
        return account
