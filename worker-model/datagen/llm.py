"""Model calls for the data generator: the Gate, which keeps the models that can't share the Studio's memory apart
while seeds run in threads, and LLM, which sends each call the way Chimera does and caches it by its full input.

Why a gate: gpt-oss:120b needs about 65 GB, so it can't be loaded beside qwen3.8:27b, and every reload costs about a
minute. Seeds run in parallel threads (DESIGN.md, "Concurrency") and each asks for whatever model its step needs, so
the gate lets one group of models run at a time and batches the others' calls into phases: it stays on the active
group while anyone waits for it, moves on when the group has been idle for a while or someone else has waited too
long, and only switches once the calls in flight have ended.

Why a cache: a run is resumable and deterministic (DESIGN.md, "Rules that hold everywhere"). Every finished call is
kept in cache/calls.jsonl under a hash of what was sent, so a resumed run replays the same replies, and a seed's
work is a function of the cache. The seed sent to Ollama comes from that hash, so samples differ and replay the
same. Errors aren't kept, so a resumed run asks again.

The body is Chimera's (runner.common.chat_body's shape without its names hook), and the client is the runners':
runner.common.Ollama with the 16,384-token runaway guard, and the 6,144-token content cap on a worker's reply.
"""
from __future__ import annotations

import contextlib
import dataclasses
import threading
import time

from datagen.common import append_jsonl, key_of, msgs_tokens, now_iso, stable_int
from runner import common as rc

# Models that can be loaded together; a model in no group is a group of its own.
DEFAULT_GROUPS = [{"gpt-oss:120b", "hydra:1.0"}, {"qwen3.8:27b"}, {"qwen3:8b"}]
# One num_ctx per big model, so it never reloads for a bigger bucket (a changed num_ctx reloads a model in Ollama).
FIXED_CTX = {"gpt-oss:120b": 32768, "qwen3.8:27b": 32768, "qwen3:8b": 32768}
ROOM = rc.STEP_ROOM  # what a call is sized for beyond its prompt when nothing else says (runStep's room)
WAIT_LOG_S = 60.0  # a wait at least this long goes to gate.jsonl
PS_EVERY_S = 60.0  # how often, at most, a call looks at Ollama's /api/ps for models someone else loaded


def group_label(group) -> str:
    """A group's name in logs and stats: its models, sorted, joined by "+"."""
    return "+".join(sorted(group))


def ctx_for(model, messages, num_ctx=None) -> int:
    """The num_ctx a call gets: the one given; else FIXED_CTX[model], unless the prompt plus ROOM needs a bigger
    bucket (a reload beats a prompt cut short); else Chimera's bucket for the prompt plus ROOM."""
    if num_ctx:
        return int(num_ctx)
    bucket = rc.ctx_bucket(msgs_tokens(messages) + ROOM)
    fixed = FIXED_CTX.get(model)
    return max(fixed, bucket) if fixed else bucket


class _Ticket:
    """One request for a slot: who asked, when, and (once granted) how long it waited."""

    __slots__ = ("model", "purpose", "group", "t0", "granted", "waited_s")

    def __init__(self, model, purpose, group, t0):
        self.model, self.purpose, self.group, self.t0 = model, purpose, group, t0
        self.granted, self.waited_s = None, 0.0


class Gate:
    """Lets one group of models run at a time, with at most `parallel` calls in flight.

    `with gate.slot(model, purpose):` blocks until the model's group is the active one and a slot is free. Waiters
    of the active group are served first, in the order they came. The gate stays on the active group while anyone
    waits for it, and switches when
    - nobody has asked for the active group for idle_switch_s (counted from the last slot it was given or gave
      back, since a thread often runs a Blender check for a few seconds between two calls), to the group with the
      most waiters (ties: the one that has waited longest); or
    - someone has waited for another group for starve_s, to that group (the one that has waited longest), even
      while the active group has waiters. Such a switch stops new slots for the active group at once and waits for
      its calls in flight to end. A wait counts from when the waiter's group stopped being active (a thread that
      asked during the drain hasn't waited for another group yet), and the group just switched to is served at
      least once before a starvation switch can leave it, so two busy groups take turns of starve_s instead of
      bouncing the gate back and forth.
    Every switch, and every wait of WAIT_LOG_S or more, is appended to log_path (gate.jsonl). `stop` is a callable
    that raises to abandon a wait (lambda: common.check_stop(data_dir)): it runs when a slot is asked for and about
    every poll_s while waiting, so a STOP file ends the waits and lets only the calls in flight finish.

    Slots don't nest: a thread holding a slot that asks for another one can wait forever."""

    poll_s = 0.5  # how often a waiter runs `stop`
    wait_log_s = WAIT_LOG_S

    def __init__(self, groups=None, parallel=1, idle_switch_s=15.0, starve_s=1200.0, log_path=None, stop=None):
        if parallel < 1:
            raise ValueError("parallel must be at least 1")
        self.parallel, self.idle_switch_s, self.starve_s = int(parallel), float(idle_switch_s), float(starve_s)
        self.log_path, self._stop = log_path, stop
        self._groups, self._index = [], {}
        for g in (DEFAULT_GROUPS if groups is None else groups):
            g = frozenset(g)
            twice = sorted(m for m in g if m in self._index)
            if twice:
                raise ValueError(f"in two groups: {', '.join(twice)}")
            self._index.update((m, len(self._groups)) for m in g)
            self._groups.append(g)
        self._cond = threading.Condition()
        self._queues = {}  # group index -> tickets waiting, oldest first
        self._active = None  # the group that may run
        self._target = None  # a starvation switch waiting for the calls in flight to end
        self._target_t = 0.0
        self._left = {}  # group index -> when it last stopped being active
        self._served = 0  # slots given since the last switch
        self._inflight = 0
        self._last_use = time.monotonic()
        self._active_since = time.monotonic()
        self._switches = {"start": 0, "idle": 0, "starve": 0}
        self._long_waits = 0
        self._gstats = {}
        self._mstats = {}

    # ---- public

    def group_of(self, model) -> str:
        """The label of the model's group."""
        with self._cond:
            return group_label(self._groups[self._gi(model)])

    @contextlib.contextmanager
    def slot(self, model, purpose=""):
        """Hold one slot for a call of model; yields the ticket (its waited_s says how long it waited)."""
        t = self._acquire(model, purpose)
        try:
            yield t
        finally:
            self._release(t)

    def stats(self) -> dict:
        """Counts and seconds: switches (by why), waits of WAIT_LOG_S or more, and per group and per model the calls,
        the seconds in calls (busy_s, summed over parallel calls) and waiting; per group also the seconds it was
        active. Plus what is happening now (active, pending, in_flight, waiting)."""
        with self._cond:
            now = time.monotonic()
            groups = {}
            for gi, s in self._gstats.items():
                s = dict(s)
                if gi == self._active:
                    s["active_s"] += now - self._active_since
                groups[self._label(gi)] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}
            models = {m: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}
                      for m, s in self._mstats.items()}
            return {"parallel": self.parallel, "active": self._label(self._active), "pending": self._label(self._target),
                    "in_flight": self._inflight,
                    "waiting": {self._label(gi): len(q) for gi, q in self._queues.items() if q},
                    "switches": sum(self._switches.values()), "switches_by_why": dict(self._switches),
                    "waits_over_60": self._long_waits, "groups": groups, "models": models}

    # ---- the rest runs under self._cond

    def _gi(self, model):
        gi = self._index.get(model)
        if gi is None:
            gi = self._index[model] = len(self._groups)
            self._groups.append(frozenset([model]))
        return gi

    def _label(self, gi):
        return None if gi is None else group_label(self._groups[gi])

    def _gs(self, gi):
        return self._gstats.setdefault(gi, {"calls": 0, "busy_s": 0.0, "wait_s": 0.0, "max_wait_s": 0.0,
                                            "active_s": 0.0})

    def _ms(self, model):
        return self._mstats.setdefault(model, {"calls": 0, "busy_s": 0.0, "wait_s": 0.0})

    def _acquire(self, model, purpose):
        with self._cond:
            if self._stop:
                self._stop()
            gi = self._gi(model)
            t = _Ticket(model, purpose, gi, time.monotonic())
            q = self._queues.setdefault(gi, [])
            q.append(t)
            try:
                while True:
                    now = time.monotonic()
                    self._advance(now)
                    if self._can_go(t):
                        break
                    self._cond.wait(self._wait_for(now))
                    if self._stop:
                        self._stop()
            except BaseException:
                q.remove(t)
                self._advance(time.monotonic())
                self._cond.notify_all()
                raise
            q.remove(t)
            self._inflight += 1
            self._served += 1
            t.granted, t.waited_s = now, now - t.t0
            self._last_use = now
            gs, ms = self._gs(gi), self._ms(model)
            gs["calls"] += 1
            gs["wait_s"] += t.waited_s
            gs["max_wait_s"] = max(gs["max_wait_s"], t.waited_s)
            ms["calls"] += 1
            ms["wait_s"] += t.waited_s
            if t.waited_s >= self.wait_log_s:
                self._long_waits += 1
                self._log({"event": "wait", "from": None, "to": self._label(gi), "waiters": self._waiters(),
                           "waited_s": round(t.waited_s, 3), "model": model, "purpose": purpose})
            self._cond.notify_all()  # the next in line may fit too (parallel > 1)
            return t

    def _release(self, t):
        with self._cond:
            now = time.monotonic()
            self._inflight -= 1
            busy = now - t.granted
            self._gs(t.group)["busy_s"] += busy
            self._ms(t.model)["busy_s"] += busy
            self._last_use = now
            self._advance(now)
            self._cond.notify_all()

    def _can_go(self, t):
        if self._target is not None or self._active != t.group:
            return False
        free = self.parallel - self._inflight
        return free > 0 and self._queues[t.group].index(t) < free

    def _advance(self, now):
        """Start, finish or decide a switch, as the policy says."""
        if self._target is not None:
            if not self._queues.get(self._target):  # its waiters have gone (stopped): carry on as before
                self._target = None
                self._cond.notify_all()
            elif self._inflight == 0:
                self._switch(self._target, now, "starve")
            return
        if self._active is None:
            g = self._busiest(list(self._queues))
            if g is not None:
                self._switch(g, now, "start")
            return
        others = [g for g, q in self._queues.items() if q and g != self._active]
        if not others:
            return
        since = {g: self._since(g) for g in others}
        starved = [g for g in others if now - since[g] >= self.starve_s] if self._may_starve() else []
        if starved:
            g, why = min(starved, key=lambda x: since[x]), "starve"
        elif (not self._queues.get(self._active) and self._inflight == 0
              and now - self._last_use >= self.idle_switch_s):
            g, why = self._busiest(others), "idle"
        else:
            return
        if self._inflight == 0:
            self._switch(g, now, why)
        else:
            self._target, self._target_t = g, now

    def _since(self, gi):
        """When the first waiter of group gi started waiting for another group."""
        return max(self._queues[gi][0].t0, self._left.get(gi, 0.0))

    def _may_starve(self):
        """A starvation switch may leave the active group once it has been served, or when nobody waits for it."""
        return self._served > 0 or not self._queues.get(self._active)

    def _busiest(self, gis):
        """The group with the most waiters; ties: the one whose first waiter has waited longest."""
        gis = [g for g in gis if self._queues.get(g)]
        if not gis:
            return None
        return min(gis, key=lambda g: (-len(self._queues[g]), self._queues[g][0].t0))

    def _switch(self, gi, now, why):
        old = self._active
        if old is not None:
            self._gs(old)["active_s"] += now - self._active_since
            self._left[old] = now
        self._served = 0
        drain = now - self._target_t if self._target is not None else 0.0
        q = self._queues.get(gi) or []
        waited = now - q[0].t0 if q else 0.0
        self._active, self._target = gi, None
        self._active_since = self._last_use = now
        self._gs(gi)
        self._switches[why] += 1
        self._cond.notify_all()  # the new group's waiters may be asleep on a long timeout
        self._log({"event": "switch", "why": why, "from": self._label(old), "to": self._label(gi),
                   "waiters": self._waiters(), "waited_s": round(waited, 3), "drain_s": round(drain, 3)})

    def _waiters(self):
        return {self._label(g): len(q) for g, q in self._queues.items() if q}

    def _wait_for(self, now):
        """How long a waiter may sleep before something can change without a notify: the next idle or starvation
        deadline, the stop poll, and 5 s at most."""
        t = 5.0
        if self._stop:
            t = min(t, self.poll_s)
        if self._active is not None and self._target is None:
            others = [g for g, q in self._queues.items() if q and g != self._active]
            if others:
                if self._may_starve():  # else the active group's next grant notifies
                    t = min(t, min(self._since(g) for g in others) + self.starve_s - now)
                if not self._queues.get(self._active) and self._inflight == 0:
                    t = min(t, self._last_use + self.idle_switch_s - now)
        return max(t, 0.001)

    def _log(self, rec):
        if not self.log_path:
            return
        try:
            append_jsonl(self.log_path, dict({"t": round(time.time(), 3)}, **rec))
        except OSError:  # a full disk mustn't leave a slot taken or a switch half made
            pass


@dataclasses.dataclass
class Reply:
    """One model call's outcome. wall_s is the call's own time, also when it comes from the cache (cached=True: no
    model ran in this process); waited_s is the time spent waiting for the gate."""

    content: str
    thinking_chars: int = 0
    stats: dict = dataclasses.field(default_factory=dict)
    done_reason: str | None = None
    error: str | None = None
    wall_s: float = 0.0
    cached: bool = False
    key: str = ""
    model: str = ""
    purpose: str = ""
    sample: int = 0
    seed: int | None = None
    num_ctx: int | None = None
    waited_s: float = 0.0
    attempts: int = 1

    @property
    def runaway(self) -> bool:
        """The reply cap or the runaway guard stopped reading it (done_reason "runner_cut")."""
        return self.done_reason == rc.RUNNER_CUT

    @property
    def ok(self) -> bool:
        """No error (a runaway has one)."""
        return self.error is None

    def record(self) -> dict:
        return dataclasses.asdict(self)


_STAT_KEYS = ("calls", "cached", "errors", "runaways", "wall_s", "cached_wall_s", "eval_tokens", "prompt_tokens")


class LLM:
    """Calls Ollama through the gate, with every finished call cached (common.Cache, cache/calls.jsonl).

    unload: before the first call of a group, unload the models of other groups that this LLM has called itself
    (never a model it didn't load, such as one the person's Chimera is lending), so two groups aren't left loaded
    side by side when Ollama's own eviction would be late.

    Before a call, at most once every PS_EVERY_S, it asks Ollama's /api/ps what is loaded, and a model this LLM never
    called (pool work while Chimera lends, say) goes to the gate's log as {"event": "foreign", "models"}, so the
    report can flag timings it may have slowed. That look never fails a call."""

    def __init__(self, host, gate, cache, timeout=900.0, unload=True):
        self.client = rc.Ollama(host, timeout)
        self.gate, self.cache, self.timeout, self.unload = gate, cache, float(timeout), unload
        self._lock = threading.Lock()  # stats
        self._keys_lock = threading.Lock()
        self._key_locks = {}  # key -> [lock, users]: one call per key at a time
        self._unload_lock = threading.Lock()
        self._used = set()
        self._stats = {}
        self._ps_lock = threading.Lock()
        self._called = set()  # every model this LLM has sent a call to (_used forgets the unloaded ones)
        self._ps_t = None  # when /api/ps was last asked (monotonic)

    def request(self, model, messages, *, options=None, fmt=None, think=None, worker=False, sample=0,
                num_ctx=None):
        """(key, body) for a call, without making it. The body is Chimera's: stream true, keep_alive "15m", role
        and content per message, options with num_ctx (see ctx_for; options["num_ctx"] counts as given) and the
        seed, format and think only when given. The key covers everything sent but the derived seed, plus worker
        and sample; the seed is stable_int(key) unless options has one, which is sent as it is and counts in the
        key."""
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        given = dict(options or {})
        seed = given.pop("seed", None)
        n = ctx_for(model, msgs, num_ctx or given.pop("num_ctx", None))
        given.pop("num_ctx", None)
        opts = dict({"num_ctx": n}, **given)
        key_opts = opts if seed is None else dict(opts, seed=seed)
        key = key_of(model, msgs, key_opts, fmt, think, bool(worker), sample)
        opts["seed"] = stable_int(key) if seed is None else seed
        body = {"model": model, "messages": msgs, "stream": True, "keep_alive": rc.KEEP_ALIVE, "options": opts}
        if fmt is not None:
            body["format"] = fmt
        if think is not None:
            body["think"] = think
        return key, body

    def call(self, model, messages, *, purpose, options=None, fmt=None, think=None, worker=False, sample=0,
             num_ctx=None) -> Reply:
        """One call. A cached reply returns at once (cached=True) without a gate slot. Otherwise it waits for a slot
        (the gate's stop check may raise common.StopRequested) and asks Ollama, up to two tries when the call
        itself fails (runner.common.ask); worker=True holds the reply's content to the 6,144-token cap. A finished
        reply (no error, or a runaway) is cached; a failed one isn't."""
        key, body = self.request(model, messages, options=options, fmt=fmt, think=think, worker=worker,
                                 sample=sample, num_ctx=num_ctx)
        hit = self.cache.get(key)
        if hit is not None:
            return self._from_cache(hit, key, model, purpose, sample)
        with self._one_at_a_time(key):
            hit = self.cache.get(key)  # an identical call in another thread may have just finished
            if hit is not None:
                return self._from_cache(hit, key, model, purpose, sample)
            with self.gate.slot(model, purpose) as ticket:
                self._note_foreign(model)
                self._unload_others(model)
                t0 = time.monotonic()
                got = rc.ask(self.client, body, self.timeout, attempts=2, worker=worker)
                wall = time.monotonic() - t0
            st = got.get("stats") or {}
            value = {"model": model, "purpose": purpose, "sample": sample, "seed": body["options"]["seed"],
                     "num_ctx": body["options"]["num_ctx"], "content": got.get("content") or "",
                     "thinking_chars": len(got.get("thinking") or ""), "stats": st,
                     "done_reason": st.get("done_reason"), "error": got.get("error"), "wall_s": round(wall, 3),
                     "attempts": got.get("attempts", 1), "errors": got.get("errors") or [],
                     "first_token_s": got.get("first_token_s"), "first_content_s": got.get("first_content_s"),
                     "t": now_iso()}
            reply = self._reply(value, key, model, purpose, sample, cached=False, waited=ticket.waited_s)
            if reply.error is None or reply.runaway:
                self.cache.put(key, value)
        self._count(model, purpose, calls=1, errors=int(reply.error is not None and not reply.runaway),
                    runaways=int(reply.runaway), wall_s=wall, eval_tokens=st.get("eval_count") or 0,
                    prompt_tokens=st.get("prompt_eval_count") or 0)
        return reply

    def stats(self) -> dict:
        """{model: {purpose: {calls, cached, errors, runaways, wall_s, cached_wall_s, eval_tokens, prompt_tokens}}}
        for this process: calls are the ones sent to Ollama (wall_s, tokens and errors are theirs); cached counts
        cache hits, cached_wall_s the time those calls took when they were made."""
        with self._lock:
            return {m: {p: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}
                        for p, s in by.items()}
                    for m, by in self._stats.items()}

    def close(self):
        """Unload every model this LLM called (when unload is on)."""
        if not self.unload:
            return
        with self._unload_lock:
            for m in sorted(self._used):
                self.client.unload(m)
            self._used.clear()

    # ---- helpers

    def _reply(self, value, key, model, purpose, sample, cached, waited=0.0):
        return Reply(content=value.get("content") or "", thinking_chars=value.get("thinking_chars") or 0,
                     stats=value.get("stats") or {}, done_reason=value.get("done_reason"), error=value.get("error"),
                     wall_s=value.get("wall_s") or 0.0, cached=cached, key=key, model=model, purpose=purpose,
                     sample=sample, seed=value.get("seed"), num_ctx=value.get("num_ctx"), waited_s=round(waited, 3),
                     attempts=value.get("attempts", 1))

    def _from_cache(self, value, key, model, purpose, sample):
        self._count(model, purpose, cached=1, cached_wall_s=float(value.get("wall_s") or 0.0))
        return self._reply(value, key, model, purpose, sample, cached=True)

    def _count(self, model, purpose, **adds):
        with self._lock:
            s = self._stats.setdefault(model, {}).setdefault(purpose, {k: 0 for k in _STAT_KEYS})
            for k, v in adds.items():
                s[k] += v

    @contextlib.contextmanager
    def _one_at_a_time(self, key):
        """Identical calls from two threads run once: the second waits, then finds the first's reply cached (if it
        failed, the second asks itself). Without this the two could get different replies, and a resumed run,
        replaying one of them for both, would not repeat the run."""
        with self._keys_lock:
            ent = self._key_locks.setdefault(key, [threading.Lock(), 0])
            ent[1] += 1
        try:
            with ent[0]:
                yield
        finally:
            with self._keys_lock:
                ent[1] -= 1
                if ent[1] == 0:
                    del self._key_locks[key]

    def _note_foreign(self, model):
        """Log the models /api/ps shows loaded that this LLM never called (model, about to be called, counts as
        called), at most once every PS_EVERY_S. Any failure is ignored: it's only a note for the report."""
        with self._ps_lock:
            self._called.add(model)
            now = time.monotonic()
            if self._ps_t is not None and now - self._ps_t < PS_EVERY_S:
                return
            self._ps_t = now
            called = set(self._called)
        try:
            ps = self.client._json("GET", "/api/ps", timeout=5.0).get("models") or []
            loaded = {m.get("name") or m.get("model") for m in ps if isinstance(m, dict)}
            foreign = sorted(m for m in loaded if isinstance(m, str) and m and m not in called)
            if foreign:
                self.gate._log({"event": "foreign", "models": foreign})
        except Exception:  # noqa: BLE001 - Ollama's answer, or the log, mustn't fail the call
            pass

    def _unload_others(self, model):
        """Runs inside a slot of model's group, so no call of another group is in flight (the gate's switch waited
        for them)."""
        if not self.unload:
            return
        with self._unload_lock:
            mine = self.gate.group_of(model)
            stale = sorted(m for m in self._used if self.gate.group_of(m) != mine)
            for m in stale:
                self.client.unload(m)
            self._used.difference_update(stale)
            self._used.add(model)
