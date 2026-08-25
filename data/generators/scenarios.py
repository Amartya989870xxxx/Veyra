"""Scenario builders for the synthetic benchmark.

Each builder returns one :class:`Episode` — a coherent slice of activity whose records
share a ``group_id``. The evaluation split is by group, so an episode is the atomic unit
that must never straddle train and test.

Design note on hard negatives
-----------------------------
Several legitimate scenarios here are written specifically to trip naive rules: the flash
sale is a burst on a single SKU with one coupon; the household shares a device across
accounts; the enterprise buyer fires dozens of payments a minute; the legitimate agent is
extremely fast. What actually separates them from abuse is not speed but:

===================  ==============================  ==============================
dimension            legitimate automation           coordinated abuse
===================  ==============================  ==============================
inter-action timing  jittered (high CoV)             scripted (near-constant gaps)
pre-payment actions  browsing/comparison present     payment-heavy, little browsing
accounts per device  ~1                              many
instrument diversity consistent per customer         many per customer, or one shared
delegation           within limits                   exceeded/expired/forbidden
retry behaviour      occasional, gateway-driven      sustained hammering
===================  ==============================  ==============================

If a detector learns "fast = fraud" it will fail on this dataset by construction.
"""

from __future__ import annotations

import math
from datetime import timedelta

from data.generators.catalog import PAYMENT_METHODS, Sku
from data.generators.records import Episode, EpisodeContext, GenAction, GenDelegation, GenSession, GenTransaction

HUMAN_BROWSE = ["SEARCH", "VIEW_PRODUCT", "VIEW_PRODUCT", "ADD_TO_CART", "CHECKOUT", "AUTHENTICATE"]
AGENT_ROUTINE = ["SEARCH", "COMPARE_PRICES", "VIEW_PRODUCT", "ADD_TO_CART", "CHECKOUT"]
AGENT_THOROUGH = ["SEARCH", "COMPARE_PRICES", "COMPARE_PRICES", "VIEW_PRODUCT", "VIEW_PRODUCT",
                  "COMPARE_PRICES", "TOOL_CALL", "ADD_TO_CART", "CHECKOUT"]
MINIMAL_PAYMENT = ["REQUEST_PAYMENT"]

TOOL_FOR_ACTION = {
    "SEARCH": "catalog.search",
    "VIEW_PRODUCT": "catalog.get_product",
    "COMPARE_PRICES": "catalog.compare",
    "ADD_TO_CART": "cart.add",
    "APPLY_COUPON": "cart.apply_coupon",
    "CHECKOUT": "checkout.create",
    "AUTHENTICATE": "auth.verify",
    "REQUEST_PAYMENT": "payment.create",
    "RETRY_PAYMENT": "payment.retry",
    "CANCEL": "order.cancel",
    "TOOL_CALL": "tool.invoke",
}


# --------------------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------------------


def _price(ctx: EpisodeContext, sku: Sku, spread: float = 0.12) -> float:
    return round(max(29.0, sku.base_price * (1.0 + ctx.rng.gauss(0, spread))), 2)


def _instrument(ctx: EpisodeContext, customer_id: str, variant: int = 0) -> str:
    """Synthetic, non-reversible payment-instrument token. Never a real card reference."""
    return f"pi_{abs(hash((customer_id, variant))) % 10**8:08d}"


def _session(
    ctx: EpisodeContext,
    customer_id: str,
    agent_id: str | None,
    device_id: str,
    network: str,
    started_at,
) -> GenSession:
    return GenSession(
        session_id=ctx.ids.next("sess"),
        customer_id=customer_id,
        agent_id=agent_id,
        actor_type="AGENT" if agent_id else "HUMAN",
        device_id=device_id,
        network_fingerprint=network,
        started_at=started_at,
    )


def _emit_actions(
    ctx: EpisodeContext,
    session: GenSession,
    template: list[str],
    start_at,
    mean_gap: float,
    gap_cv: float,
    merchant_id: str | None = None,
    sku_id: str | None = None,
    start_sequence: int = 0,
) -> tuple[list[GenAction], object]:
    """Emit an action trajectory.

    ``gap_cv`` is the coefficient of variation of inter-action gaps and is the main lever
    separating human/agent jitter from scripted regularity.
    """
    if session.agent_id is None:
        return [], start_at
    actions: list[GenAction] = []
    cursor = start_at
    for offset, action_type in enumerate(template):
        gap = max(0.01, ctx.rng.gauss(mean_gap, mean_gap * gap_cv))
        cursor = cursor + timedelta(seconds=gap)
        actions.append(
            GenAction(
                action_id=ctx.ids.next("act", 7),
                agent_id=session.agent_id,
                session_id=session.session_id,
                sequence_number=start_sequence + offset,
                action_type=action_type,
                tool_name=TOOL_FOR_ACTION.get(action_type),
                timestamp=cursor,
                merchant_id=merchant_id,
                sku_id=sku_id,
            )
        )
    return actions, cursor


def _maybe_coupon(ctx: EpisodeContext, probability: float = 0.28):
    """Draw an ordinary promotional coupon for legitimate traffic.

    Legitimate shoppers redeem coupons constantly. An earlier version gave coupons almost
    exclusively to abusive episodes, which turned `has_coupon` into a label proxy. What
    distinguishes coupon *abuse* is concentration — one private code across many accounts in
    seconds — not the presence of a coupon.
    """
    if ctx.rng.random() >= probability:
        return None, 0.0
    coupon = ctx.rng.choice(ctx.catalog.public_coupons() or ctx.catalog.coupons)
    return coupon.coupon_id, coupon.value


def _txn(
    ctx: EpisodeContext,
    *,
    episode: Episode,
    customer_id: str,
    merchant_id: str,
    category: str,
    amount: float,
    device_id: str,
    network: str,
    timestamp,
    agent_id: str | None = None,
    session_id: str | None = None,
    delegation_id: str | None = None,
    sku_id: str | None = None,
    quantity: int = 1,
    coupon_id: str | None = None,
    coupon_value: float = 0.0,
    payment_method: str | None = None,
    instrument: str | None = None,
    retry_count: int = 0,
    status: str = "CAPTURED",
    actor_type: str = "HUMAN",
) -> GenTransaction:
    return GenTransaction(
        transaction_id=ctx.ids.next("txn"),
        merchant_id=merchant_id,
        customer_id=customer_id,
        agent_id=agent_id,
        session_id=session_id,
        delegation_id=delegation_id,
        amount=round(amount, 2),
        currency="INR",
        merchant_category=category,
        sku_id=sku_id,
        quantity=quantity,
        coupon_id=coupon_id,
        coupon_value=coupon_value,
        device_id=device_id,
        network_fingerprint=network,
        payment_method=payment_method or ctx.rng.choice(PAYMENT_METHODS),
        instrument_fingerprint=instrument or _instrument(ctx, customer_id),
        retry_count=retry_count,
        status=status,
        actor_type=actor_type,
        timestamp=timestamp,
        label_class=episode.label_class,
        is_abusive=episode.label_class in ("SUSPICIOUS_AUTOMATION", "COORDINATED_ABUSE"),
        scenario=episode.scenario,
        group_id=episode.group_id,
        campaign_id=episode.campaign_id,
        hard_negative=episode.hard_negative,
    )


def _delegation(
    ctx: EpisodeContext,
    customer_id: str,
    agent_id: str,
    issued_at,
    *,
    purpose: str,
    max_amount: float,
    allowed: list[str],
    forbidden: list[str] | None = None,
    merchant_policy: str = "known_or_approved",
    valid_days: int = 30,
    expired: bool = False,
) -> GenDelegation:
    expires = issued_at + timedelta(days=valid_days)
    if expired:
        # Issued and expired strictly before the activity it will be checked against.
        issued_at = issued_at - timedelta(days=45)
        expires = issued_at + timedelta(days=7)
    return GenDelegation(
        delegation_id=ctx.ids.next("del"),
        customer_id=customer_id,
        agent_id=agent_id,
        purpose=purpose,
        max_amount=round(max_amount, 2),
        currency="INR",
        allowed_categories=allowed,
        forbidden_categories=forbidden or ["alcohol"],
        allowed_merchants=[],
        merchant_policy=merchant_policy,
        approval_required_above=round(max_amount, 2),
        issued_at=issued_at,
        expires_at=expires,
    )


def _new_episode(ctx: EpisodeContext, scenario: str, label: str, hard_negative: bool = False,
                 campaign: bool = False) -> Episode:
    group_id = ctx.ids.next("grp", 5)
    return Episode(
        group_id=group_id,
        scenario=scenario,
        label_class=label,
        hard_negative=hard_negative,
        campaign_id=ctx.ids.next("camp", 5) if campaign else None,
    )


# --------------------------------------------------------------------------------------
# legitimate human scenarios
# --------------------------------------------------------------------------------------


def human_normal(ctx: EpisodeContext) -> Episode:
    """An ordinary shopper making a handful of purchases over the benchmark window."""
    ep = _new_episode(ctx, "human_normal", "LEGIT_HUMAN")
    customer = ctx.ids.next("cus", 5)
    device = ctx.ids.next("dev", 5)
    network = ctx.ids.next("nf", 5)
    ep.customers, ep.devices, ep.networks = [customer], [device], [network]

    for _ in range(ctx.rng.randint(1, 5)):
        when = ctx.business_hours(ctx.when())
        sku = ctx.rng.choice(ctx.catalog.skus)
        session = _session(ctx, customer, None, device, network, when)
        ep.sessions.append(session)
        coupon_id, coupon_value = _maybe_coupon(ctx)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku), device_id=device,
                network=network, timestamp=when, session_id=session.session_id,
                sku_id=sku.sku_id, quantity=ctx.rng.randint(1, 3),
                coupon_id=coupon_id, coupon_value=coupon_value,
                retry_count=1 if ctx.rng.random() < 0.10 else 0,
            )
        )
    return ep


def human_high_value(ctx: EpisodeContext) -> Episode:
    """A legitimate large purchase. Trips a naive `amount > threshold` rule."""
    ep = _new_episode(ctx, "human_high_value", "LEGIT_HUMAN", hard_negative=True)
    customer = ctx.ids.next("cus", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.devices, ep.networks = [customer], [device], [network]

    when = ctx.business_hours(ctx.when())
    expensive = [s for s in ctx.catalog.skus if s.category in ("electronics", "travel")]
    sku = ctx.rng.choice(expensive)
    session = _session(ctx, customer, None, device, network, when)
    ep.sessions.append(session)
    ep.transactions.append(
        _txn(
            ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
            category=sku.category, amount=_price(ctx, sku, 0.2) * ctx.rng.uniform(2.0, 5.0),
            device_id=device, network=network, timestamp=when, session_id=session.session_id,
            sku_id=sku.sku_id, payment_method="card_token",
        )
    )
    return ep


def human_repeat_buyer(ctx: EpisodeContext) -> Episode:
    """A loyal customer buying the same category repeatedly from the same merchant."""
    ep = _new_episode(ctx, "human_repeat_buyer", "LEGIT_HUMAN")
    customer = ctx.ids.next("cus", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.devices, ep.networks = [customer], [device], [network]

    merchant = ctx.rng.choice(ctx.catalog.merchants)
    skus = ctx.catalog.skus_of(merchant.merchant_id) or ctx.catalog.skus
    base = ctx.when()
    for i in range(ctx.rng.randint(4, 9)):
        when = ctx.business_hours(base + timedelta(days=i * ctx.rng.uniform(2, 5)))
        if when > ctx.start + ctx.horizon:
            break
        sku = ctx.rng.choice(skus)
        session = _session(ctx, customer, None, device, network, when)
        ep.sessions.append(session)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=_price(ctx, sku), device_id=device,
                network=network, timestamp=when, session_id=session.session_id,
                sku_id=sku.sku_id, quantity=ctx.rng.randint(1, 3),
                coupon_id=_maybe_coupon(ctx)[0], coupon_value=_maybe_coupon(ctx, 0.0)[1],
                retry_count=1 if ctx.rng.random() < 0.09 else 0,
            )
        )
    return ep


def household_shared_device(ctx: EpisodeContext) -> Episode:
    """HARD NEGATIVE: a family sharing one tablet and one home network.

    Trips `shared_device_count > 3`. Distinguished by low velocity, category diversity and
    day-scale spacing.
    """
    ep = _new_episode(ctx, "household_shared_device", "LEGIT_HUMAN", hard_negative=True)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    members = ctx.ids.next_many("cus", ctx.rng.randint(3, 6), 5)
    ep.customers, ep.devices, ep.networks = members, [device], [network]

    base = ctx.when()
    for member in members:
        for _ in range(ctx.rng.randint(1, 3)):
            when = ctx.business_hours(base + timedelta(days=ctx.rng.uniform(0, 20)))
            if when > ctx.start + ctx.horizon:
                continue
            sku = ctx.rng.choice(ctx.catalog.skus)
            session = _session(ctx, member, None, device, network, when)
            ep.sessions.append(session)
            ep.transactions.append(
                _txn(
                    ctx, episode=ep, customer_id=member, merchant_id=sku.merchant_id,
                    category=sku.category, amount=_price(ctx, sku), device_id=device,
                    network=network, timestamp=when, session_id=session.session_id,
                    sku_id=sku.sku_id, quantity=ctx.rng.randint(1, 3),
                    coupon_id=_maybe_coupon(ctx)[0],
                    retry_count=1 if ctx.rng.random() < 0.08 else 0,
                )
            )
    return ep


def flash_sale_burst(ctx: EpisodeContext) -> Episode:
    """HARD NEGATIVE: a genuine flash sale.

    Hundreds of unrelated buyers hit one hot SKU within minutes, most using the same
    *public* coupon. Trips burst-velocity, SKU-concentration and coupon-concentration rules
    simultaneously. Distinguished by one device per buyer, jittered arrivals and low retries.
    """
    ep = _new_episode(ctx, "flash_sale_burst", "LEGIT_HUMAN", hard_negative=True)
    hot = ctx.catalog.hot_skus() or ctx.catalog.skus
    sku = ctx.rng.choice(hot)
    coupon = ctx.rng.choice(ctx.catalog.public_coupons() or ctx.catalog.coupons)
    start = ctx.business_hours(ctx.when())
    buyers = ctx.rng.randint(60, 160)

    for _ in range(buyers):
        customer = ctx.ids.next("cus", 5)
        device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
        ep.customers.append(customer)
        ep.devices.append(device)
        ep.networks.append(network)
        # Real crowds arrive with heavy jitter, not on a metronome.
        when = start + timedelta(seconds=abs(ctx.rng.gauss(0, 90)))
        session = _session(ctx, customer, None, device, network, when)
        ep.sessions.append(session)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku, 0.05), device_id=device,
                network=network, timestamp=when, session_id=session.session_id,
                sku_id=sku.sku_id, coupon_id=coupon.coupon_id, coupon_value=coupon.value,
                retry_count=1 if ctx.rng.random() < 0.12 else 0,
                status="CAPTURED" if ctx.rng.random() > 0.05 else "FAILED",
            )
        )
    return ep


def retry_payment_failure(ctx: EpisodeContext) -> Episode:
    """HARD NEGATIVE: a legitimate purchase retried through a transient gateway outage."""
    ep = _new_episode(ctx, "retry_payment_failure", "LEGIT_HUMAN", hard_negative=True)
    customer = ctx.ids.next("cus", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.devices, ep.networks = [customer], [device], [network]

    sku = ctx.rng.choice(ctx.catalog.skus)
    when = ctx.business_hours(ctx.when())
    session = _session(ctx, customer, None, device, network, when)
    ep.sessions.append(session)
    attempts = ctx.rng.randint(2, 8)
    instrument = _instrument(ctx, customer)
    for attempt in range(attempts):
        # Human-paced retries: the person waits, sighs, tries again.
        ts = when + timedelta(seconds=sum(ctx.rng.uniform(20, 90) for _ in range(attempt)))
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku, 0.0), device_id=device,
                network=network, timestamp=ts, session_id=session.session_id, sku_id=sku.sku_id,
                retry_count=attempt, instrument=instrument,
                status="CAPTURED" if attempt == attempts - 1 else "FAILED",
            )
        )
    return ep


# --------------------------------------------------------------------------------------
# legitimate agent scenarios
# --------------------------------------------------------------------------------------


def agent_routine_purchase(ctx: EpisodeContext) -> Episode:
    """An agent doing exactly what it was delegated to do, within its limits."""
    ep = _new_episode(ctx, "agent_routine_purchase", "LEGIT_AGENT")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    category = ctx.rng.choice(["grocery", "food", "pharmacy"])
    merchants = ctx.catalog.merchants_in(category) or ctx.catalog.merchants
    issued = ctx.start
    delegation = _delegation(
        ctx, customer, agent, issued, purpose=f"{category}_purchase",
        max_amount=ctx.rng.uniform(2500, 6000), allowed=[category, "grocery", "food"],
    )
    ep.delegations.append(delegation)

    for _ in range(ctx.rng.randint(1, 4)):
        merchant = ctx.rng.choice(merchants)
        skus = ctx.catalog.skus_of(merchant.merchant_id) or ctx.catalog.skus
        sku = ctx.rng.choice(skus)
        amount = min(_price(ctx, sku), delegation.max_amount * 0.9)
        when = ctx.business_hours(ctx.when())
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        actions, cursor = _emit_actions(
            ctx, session, AGENT_ROUTINE, when, mean_gap=0.9, gap_cv=0.5,
            merchant_id=merchant.merchant_id, sku_id=sku.sku_id,
        )
        pay, cursor = _emit_actions(
            ctx, session, ["REQUEST_PAYMENT"], cursor, mean_gap=0.6, gap_cv=0.5,
            merchant_id=merchant.merchant_id, sku_id=sku.sku_id, start_sequence=len(actions),
        )
        ep.actions.extend(actions + pay)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=amount, device_id=device, network=network,
                timestamp=cursor, agent_id=agent, session_id=session.session_id,
                delegation_id=delegation.delegation_id, sku_id=sku.sku_id,
                quantity=ctx.rng.randint(1, 3), coupon_id=_maybe_coupon(ctx)[0],
                retry_count=1 if ctx.rng.random() < 0.09 else 0,
                actor_type="AGENT", payment_method="upi_reserve_pay",
            )
        )
    return ep


def agent_fast_comparison(ctx: EpisodeContext) -> Episode:
    """HARD NEGATIVE: a legitimate agent that is genuinely very fast.

    Dozens of tool calls per minute, sub-second gaps. Trips every actions-per-minute rule.
    Distinguished by heavy *browsing* before a single compliant payment, jittered gaps and
    one account on one device.
    """
    ep = _new_episode(ctx, "agent_fast_comparison", "LEGIT_AGENT", hard_negative=True)
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    delegation = _delegation(
        ctx, customer, agent, ctx.start, purpose="best_price_purchase",
        max_amount=ctx.rng.uniform(8000, 25000), allowed=["electronics", "fashion", "gaming"],
    )
    ep.delegations.append(delegation)

    when = ctx.business_hours(ctx.when())
    session = _session(ctx, customer, agent, device, network, when)
    ep.sessions.append(session)

    # A long comparison trajectory across several merchants: legitimate, and fast.
    template: list[str] = []
    for _ in range(ctx.rng.randint(4, 9)):
        template.extend(AGENT_THOROUGH)
    actions, cursor = _emit_actions(
        ctx, session, template, when, mean_gap=0.28, gap_cv=0.6,
    )
    sku = ctx.rng.choice([s for s in ctx.catalog.skus if s.category in
                          ("electronics", "fashion", "gaming")])
    pay, cursor = _emit_actions(
        ctx, session, ["CHECKOUT", "REQUEST_PAYMENT"], cursor, mean_gap=0.5, gap_cv=0.5,
        merchant_id=sku.merchant_id, sku_id=sku.sku_id, start_sequence=len(actions),
    )
    ep.actions.extend(actions + pay)
    ep.transactions.append(
        _txn(
            ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
            category=sku.category, amount=min(_price(ctx, sku), delegation.max_amount * 0.85),
            device_id=device, network=network, timestamp=cursor, agent_id=agent,
            session_id=session.session_id, delegation_id=delegation.delegation_id,
            sku_id=sku.sku_id, actor_type="AGENT",
        )
    )
    return ep


def agent_enterprise_bulk(ctx: EpisodeContext) -> Episode:
    """HARD NEGATIVE: a procurement agent placing a large legitimate bulk order.

    Dozens of high-value payments within minutes under an explicitly high delegation limit.
    Trips velocity and amount rules. Distinguished by a single account, a single device, a
    delegation that actually authorises the amounts, and near-zero retries.
    """
    ep = _new_episode(ctx, "agent_enterprise_bulk", "LEGIT_AGENT", hard_negative=True)
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    delegation = _delegation(
        ctx, customer, agent, ctx.start, purpose="procurement",
        max_amount=ctx.rng.uniform(60000, 200000),
        allowed=["electronics", "utilities", "fashion", "grocery"], merchant_policy="any",
    )
    ep.delegations.append(delegation)

    merchant = ctx.rng.choice(ctx.catalog.merchants_in("electronics") or ctx.catalog.merchants)
    skus = ctx.catalog.skus_of(merchant.merchant_id) or ctx.catalog.skus
    when = ctx.business_hours(ctx.when())
    session = _session(ctx, customer, agent, device, network, when)
    ep.sessions.append(session)
    cursor = when
    seq = 0
    for _ in range(ctx.rng.randint(15, 45)):
        sku = ctx.rng.choice(skus)
        pre, cursor = _emit_actions(
            ctx, session, ["SEARCH", "ADD_TO_CART", "CHECKOUT", "REQUEST_PAYMENT"], cursor,
            mean_gap=1.4, gap_cv=0.45, merchant_id=merchant.merchant_id, sku_id=sku.sku_id,
            start_sequence=seq,
        )
        seq += len(pre)
        ep.actions.extend(pre)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=min(_price(ctx, sku) * ctx.rng.randint(2, 8),
                                                       delegation.max_amount * 0.8),
                device_id=device, network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, delegation_id=delegation.delegation_id,
                sku_id=sku.sku_id, quantity=ctx.rng.randint(1, 4), actor_type="AGENT",
                payment_method="netbanking",
            )
        )
    return ep


def agent_subscription_runs(ctx: EpisodeContext) -> Episode:
    """A recurring agent-driven subscription charge. Regular timing, but low volume."""
    ep = _new_episode(ctx, "agent_subscription_runs", "LEGIT_AGENT")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    merchant = ctx.rng.choice(ctx.catalog.merchants_in("utilities") or ctx.catalog.merchants)
    delegation = _delegation(
        ctx, customer, agent, ctx.start, purpose="recurring_bill",
        max_amount=ctx.rng.uniform(2000, 5000), allowed=[merchant.category, "utilities"],
    )
    ep.delegations.append(delegation)
    base = ctx.when()
    for i in range(ctx.rng.randint(2, 4)):
        when = base + timedelta(days=7 * i, seconds=ctx.rng.uniform(-1800, 1800))
        if when > ctx.start + ctx.horizon:
            break
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        acts, cursor = _emit_actions(
            ctx, session, ["CHECKOUT", "REQUEST_PAYMENT"], when, mean_gap=1.0, gap_cv=0.4,
            merchant_id=merchant.merchant_id,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=delegation.max_amount * 0.4,
                device_id=device, network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, delegation_id=delegation.delegation_id,
                actor_type="AGENT", payment_method="upi_reserve_pay",
            )
        )
    return ep


# --------------------------------------------------------------------------------------
# suspicious single-actor automation
# --------------------------------------------------------------------------------------


def agent_velocity_abuse(ctx: EpisodeContext) -> Episode:
    """One agent firing scripted payments far faster than its trajectory justifies."""
    ep = _new_episode(ctx, "agent_velocity_abuse", "SUSPICIOUS_AUTOMATION")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    delegation = _delegation(
        ctx, customer, agent, ctx.start, purpose="grocery_purchase",
        max_amount=ctx.rng.uniform(1500, 3000), allowed=["grocery", "food"],
    )
    ep.delegations.append(delegation)

    when = ctx.diurnal()
    session = _session(ctx, customer, agent, device, network, when)
    ep.sessions.append(session)
    cursor, seq = when, 0
    for i in range(ctx.rng.randint(20, 55)):
        merchant = ctx.rng.choice(ctx.catalog.merchants)  # merchant-hopping every attempt
        # Scripted cadence: gap_cv is tiny, so inter-arrival times are near-identical.
        acts, cursor = _emit_actions(
            ctx, session, MINIMAL_PAYMENT, cursor, mean_gap=0.4, gap_cv=0.04,
            merchant_id=merchant.merchant_id, start_sequence=seq,
        )
        seq += len(acts)
        ep.actions.extend(acts)
        over_limit = delegation.max_amount * ctx.rng.uniform(1.1, 2.5)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=over_limit, device_id=device,
                network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, delegation_id=delegation.delegation_id,
                actor_type="AGENT", retry_count=1 if ctx.rng.random() < 0.12 else 0,
                status="FAILED" if ctx.rng.random() < 0.12 else "CAPTURED",
            )
        )
    return ep


def agent_authorization_mismatch(ctx: EpisodeContext) -> Episode:
    """An agent transacting outside its delegated scope: forbidden category, or expired grant."""
    expired = ctx.rng.random() < 0.4
    ep = _new_episode(ctx, "agent_authorization_mismatch", "SUSPICIOUS_AUTOMATION")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    delegation = _delegation(
        ctx, customer, agent, ctx.start, purpose="grocery_purchase",
        max_amount=ctx.rng.uniform(2000, 3500), allowed=["grocery", "food"],
        forbidden=["alcohol", "gift_cards"], expired=expired,
    )
    ep.delegations.append(delegation)

    violating = ctx.rng.choice(["alcohol", "gift_cards"])
    merchants = ctx.catalog.merchants_in(violating) or ctx.catalog.merchants
    for _ in range(ctx.rng.randint(2, 6)):
        merchant = ctx.rng.choice(merchants)
        when = ctx.diurnal()
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        acts, cursor = _emit_actions(
            ctx, session, ["SEARCH", "REQUEST_PAYMENT"], when, mean_gap=0.5, gap_cv=0.08,
            merchant_id=merchant.merchant_id,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category if expired else violating,
                amount=delegation.max_amount * ctx.rng.uniform(0.6, 1.8), device_id=device,
                network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, delegation_id=delegation.delegation_id,
                actor_type="AGENT",
            )
        )
    return ep


def agent_retry_hammer(ctx: EpisodeContext) -> Episode:
    """Sustained machine-paced retries against a single merchant after repeated failures."""
    ep = _new_episode(ctx, "agent_retry_hammer", "SUSPICIOUS_AUTOMATION")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    merchant = ctx.rng.choice(ctx.catalog.merchants)
    skus = ctx.catalog.skus_of(merchant.merchant_id) or ctx.catalog.skus
    sku = ctx.rng.choice(skus)
    when = ctx.diurnal()
    session = _session(ctx, customer, agent, device, network, when)
    ep.sessions.append(session)
    cursor, seq = when, 0
    # Overlaps the legitimate retry range (2-8) on purpose: a high retry count must not be
    # separable on its own, or the benchmark rewards a rule the PRD calls a hard negative.
    attempts = ctx.rng.randint(6, 16)
    for attempt in range(attempts):
        acts, cursor = _emit_actions(
            ctx, session, ["RETRY_PAYMENT"], cursor, mean_gap=0.25, gap_cv=0.03,
            merchant_id=merchant.merchant_id, sku_id=sku.sku_id, start_sequence=seq,
        )
        seq += len(acts)
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=_price(ctx, sku, 0.0), device_id=device,
                network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, sku_id=sku.sku_id,
                retry_count=min(attempt, 3),
                actor_type="AGENT",
                status="FAILED" if attempt < attempts - 1 else "CAPTURED",
                instrument=_instrument(ctx, customer, attempt // 4),
            )
        )
    return ep


def agent_sequence_anomaly(ctx: EpisodeContext) -> Episode:
    """An agent that skips the entire discovery trajectory and jumps straight to payment."""
    ep = _new_episode(ctx, "agent_sequence_anomaly", "SUSPICIOUS_AUTOMATION")
    customer, agent = ctx.ids.next("cus", 5), ctx.ids.next("agent", 5)
    device, network = ctx.ids.next("dev", 5), ctx.ids.next("nf", 5)
    ep.customers, ep.agents, ep.devices, ep.networks = [customer], [agent], [device], [network]

    when = ctx.diurnal()
    session = _session(ctx, customer, agent, device, network, when)
    ep.sessions.append(session)
    cursor, seq = when, 0
    for _ in range(ctx.rng.randint(6, 16)):
        merchant = ctx.rng.choice(ctx.catalog.merchants)
        acts, cursor = _emit_actions(
            ctx, session, ["APPLY_COUPON", "REQUEST_PAYMENT"], cursor, mean_gap=0.3, gap_cv=0.05,
            merchant_id=merchant.merchant_id, start_sequence=seq,
        )
        seq += len(acts)
        ep.actions.extend(acts)
        coupon = ctx.rng.choice(ctx.catalog.private_coupons() or ctx.catalog.coupons)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=ctx.rng.uniform(200, 1200), device_id=device,
                network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, coupon_id=coupon.coupon_id,
                coupon_value=coupon.value, actor_type="AGENT",
                instrument=_instrument(ctx, customer, ctx.rng.randint(0, 9)),
            )
        )
    return ep


# --------------------------------------------------------------------------------------
# coordinated abuse campaigns
# --------------------------------------------------------------------------------------



def _headless(ctx: EpisodeContext, probability: float = 0.4) -> bool:
    """Should this campaign run without declaring an agent identity?

    Real abuse does not politely announce itself as automation. A scripted client that
    presents as an ordinary browser session produces no agent telemetry at all, which forces
    detection onto the graph and temporal layers. Without these episodes the benchmark makes
    ``actor_type == AGENT`` nearly separating, and a detector that learned "automation =
    fraud" would score almost perfectly while being exactly the product we refuse to build
    (PRD Principle 3).
    """
    return ctx.rng.random() < probability


def _campaign_actors(ctx: EpisodeContext, ep: Episode, n_customers: int, n_devices: int,
                     n_networks: int, n_agents: int):
    customers = ctx.ids.next_many("cus", n_customers, 5)
    devices = ctx.ids.next_many("dev", n_devices, 5)
    networks = ctx.ids.next_many("nf", n_networks, 5)
    agents = ctx.ids.next_many("agent", n_agents, 5)
    ep.customers, ep.devices, ep.networks, ep.agents = customers, devices, networks, agents
    return customers, devices, networks, agents


def campaign_device_farm(ctx: EpisodeContext) -> Episode:
    """Many synthetic accounts driven from a handful of devices by one scripted workflow.

    The individual transaction is unremarkable. The cluster is not: dozens of accounts,
    a couple of devices, one SKU, one agent workflow, metronome timing.
    """
    ep = _new_episode(ctx, "campaign_device_farm", "COORDINATED_ABUSE", campaign=True)
    customers, devices, networks, agents = _campaign_actors(
        ctx, ep, ctx.rng.randint(8, 22), ctx.rng.randint(2, 4), 1,
        ctx.rng.randint(1, 2)
    )
    sku = ctx.rng.choice(ctx.catalog.skus)
    coupon = ctx.rng.choice(ctx.catalog.private_coupons() or ctx.catalog.coupons)
    start = ctx.diurnal()
    tick = ctx.rng.uniform(0.8, 2.5)  # a single scripted cadence for the whole cluster
    headless = _headless(ctx)
    if headless:
        ep.agents = []

    for i, customer in enumerate(customers):
        agent = None if headless else agents[i % len(agents)]
        device = devices[i % len(devices)]
        network = networks[i % len(networks)]
        when = start + timedelta(seconds=i * tick + ctx.rng.gauss(0, tick * 0.05))
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        acts, cursor = _emit_actions(
            ctx, session, ["APPLY_COUPON", "CHECKOUT", "REQUEST_PAYMENT"], when,
            mean_gap=0.3, gap_cv=0.03, merchant_id=sku.merchant_id, sku_id=sku.sku_id,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku, 0.02), device_id=device,
                network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, sku_id=sku.sku_id, coupon_id=coupon.coupon_id,
                coupon_value=coupon.value, actor_type="AGENT",
                retry_count=1 if ctx.rng.random() < 0.06 else 0,
                status="CAPTURED" if ctx.rng.random() > 0.07 else "FAILED",
                instrument=_instrument(ctx, devices[i % len(devices)], 0),
            )
        )
    return ep


def campaign_coupon_abuse(ctx: EpisodeContext) -> Episode:
    """One private coupon redeemed across a large fan of accounts within minutes."""
    ep = _new_episode(ctx, "campaign_coupon_abuse", "COORDINATED_ABUSE", campaign=True)
    customers, devices, networks, agents = _campaign_actors(
        ctx, ep, ctx.rng.randint(10, 26), ctx.rng.randint(2, 5), ctx.rng.randint(1, 2),
        ctx.rng.randint(1, 2)
    )
    coupon = ctx.rng.choice(ctx.catalog.private_coupons() or ctx.catalog.coupons)
    merchant = ctx.rng.choice(ctx.catalog.merchants)
    skus = ctx.catalog.skus_of(merchant.merchant_id) or ctx.catalog.skus
    start = ctx.diurnal()
    tick = ctx.rng.uniform(1.5, 5.0)
    headless = _headless(ctx)
    if headless:
        ep.agents = []

    for i, customer in enumerate(customers):
        agent = None if headless else agents[i % len(agents)]
        device, network = devices[i % len(devices)], networks[i % len(networks)]
        when = start + timedelta(seconds=i * tick + ctx.rng.gauss(0, tick * 0.06))
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        acts, cursor = _emit_actions(
            ctx, session, ["APPLY_COUPON", "REQUEST_PAYMENT"], when, mean_gap=0.35, gap_cv=0.04,
            merchant_id=merchant.merchant_id,
        )
        ep.actions.extend(acts)
        sku = ctx.rng.choice(skus)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category,
                # Drawn from the ordinary price distribution. An earlier version pinned
                # amounts just above the coupon threshold, which made the amount alone a
                # giveaway; a real campaign buys real-looking baskets.
                amount=_price(ctx, sku),
                device_id=device, network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, sku_id=sku.sku_id, coupon_id=coupon.coupon_id,
                coupon_value=coupon.value, actor_type="HUMAN" if headless else "AGENT",
                instrument=_instrument(ctx, device, i % 3),
            )
        )
    return ep


def campaign_sku_targeting(ctx: EpisodeContext) -> Episode:
    """Synchronised inventory sniping: many accounts hit one scarce SKU on one signal."""
    ep = _new_episode(ctx, "campaign_sku_targeting", "COORDINATED_ABUSE", campaign=True)
    customers, devices, networks, agents = _campaign_actors(
        ctx, ep, ctx.rng.randint(9, 24), ctx.rng.randint(3, 7), ctx.rng.randint(1, 3),
        ctx.rng.randint(1, 2)
    )
    sku = ctx.rng.choice(ctx.catalog.hot_skus() or ctx.catalog.skus)
    start = ctx.diurnal()
    headless = _headless(ctx)
    if headless:
        ep.agents = []

    for i, customer in enumerate(customers):
        agent = None if headless else agents[i % len(agents)]
        device, network = devices[i % len(devices)], networks[i % len(networks)]
        # Fired on a shared trigger: everything lands inside a couple of seconds.
        when = start + timedelta(seconds=abs(ctx.rng.gauss(0, 1.2)))
        session = _session(ctx, customer, agent, device, network, when)
        ep.sessions.append(session)
        acts, cursor = _emit_actions(
            ctx, session, ["ADD_TO_CART", "CHECKOUT", "REQUEST_PAYMENT"], when,
            mean_gap=0.2, gap_cv=0.03, merchant_id=sku.merchant_id, sku_id=sku.sku_id,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku, 0.01),
                device_id=device, network=network, timestamp=cursor, agent_id=agent,
                session_id=session.session_id, sku_id=sku.sku_id,
                quantity=ctx.rng.randint(1, 3), actor_type="HUMAN" if headless else "AGENT",
                retry_count=1 if ctx.rng.random() < 0.08 else 0,
                status="CAPTURED" if ctx.rng.random() > 0.08 else "FAILED",
                instrument=_instrument(ctx, device, 0),
            )
        )
    return ep


def campaign_instrument_probing(ctx: EpisodeContext) -> Episode:
    """Low-value probing across many instrument fingerprints with a high failure rate.

    Detection-side only: the generator emits the *observable footprint* of this abuse
    pattern so a defender can be evaluated against it. Nothing here describes how to
    conduct it.
    """
    ep = _new_episode(ctx, "campaign_instrument_probing", "COORDINATED_ABUSE", campaign=True)
    customers, devices, networks, agents = _campaign_actors(
        ctx, ep, ctx.rng.randint(3, 7), ctx.rng.randint(1, 3), 1, 1
    )
    merchant = ctx.rng.choice(ctx.catalog.merchants)
    start = ctx.diurnal()
    tick = ctx.rng.uniform(0.5, 1.5)
    headless = _headless(ctx)
    if headless:
        ep.agents = []
    driver = None if headless else agents[0]
    session_by_customer = {}
    for customer in customers:
        s = _session(ctx, customer, driver, devices[0], networks[0], start)
        session_by_customer[customer] = s
        ep.sessions.append(s)

    n = ctx.rng.randint(12, 32)
    for i in range(n):
        customer = customers[i % len(customers)]
        session = session_by_customer[customer]
        device = devices[i % len(devices)]
        when = start + timedelta(seconds=i * tick + ctx.rng.gauss(0, tick * 0.04))
        acts, cursor = _emit_actions(
            ctx, session, ["REQUEST_PAYMENT"], when, mean_gap=0.15, gap_cv=0.02,
            merchant_id=merchant.merchant_id, start_sequence=i,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=merchant.merchant_id,
                category=merchant.category, amount=round(ctx.rng.uniform(19, 99), 2),
                device_id=device, network=networks[0], timestamp=cursor, agent_id=driver,
                session_id=session.session_id, actor_type="HUMAN" if headless else "AGENT",
                payment_method="card_token",
                status="FAILED" if ctx.rng.random() < 0.75 else "CAPTURED",
                # A fresh instrument fingerprint almost every attempt is the tell.
                instrument=_instrument(ctx, f"{ep.group_id}:{i}", i),
            )
        )
    return ep


def campaign_new_account_rush(ctx: EpisodeContext) -> Episode:
    """Freshly minted accounts on one network transacting at high value immediately."""
    ep = _new_episode(ctx, "campaign_new_account_rush", "COORDINATED_ABUSE", campaign=True)
    customers, devices, networks, agents = _campaign_actors(
        ctx, ep, ctx.rng.randint(7, 18), ctx.rng.randint(2, 5), 1, ctx.rng.randint(1, 2)
    )
    start = ctx.diurnal()
    tick = ctx.rng.uniform(2.0, 6.0)
    expensive = list(ctx.catalog.skus)
    headless = _headless(ctx)
    if headless:
        ep.agents = []

    for i, customer in enumerate(customers):
        agent = None if headless else agents[i % len(agents)]
        device = devices[i % len(devices)]
        when = start + timedelta(seconds=i * tick + ctx.rng.gauss(0, tick * 0.05))
        session = _session(ctx, customer, agent, device, networks[0], when)
        ep.sessions.append(session)
        sku = ctx.rng.choice(expensive or ctx.catalog.skus)
        acts, cursor = _emit_actions(
            ctx, session, ["CHECKOUT", "REQUEST_PAYMENT"], when, mean_gap=0.4, gap_cv=0.04,
            merchant_id=sku.merchant_id, sku_id=sku.sku_id,
        )
        ep.actions.extend(acts)
        ep.transactions.append(
            _txn(
                ctx, episode=ep, customer_id=customer, merchant_id=sku.merchant_id,
                category=sku.category, amount=_price(ctx, sku),
                device_id=device, network=networks[0], timestamp=cursor, agent_id=agent,
                session_id=session.session_id, sku_id=sku.sku_id,
                actor_type="HUMAN" if headless else "AGENT",
                payment_method=ctx.rng.choice(PAYMENT_METHODS),
                retry_count=1 if ctx.rng.random() < 0.07 else 0,
                status="CAPTURED" if ctx.rng.random() > 0.09 else "FAILED",
                instrument=_instrument(ctx, device, i % 2),
            )
        )
    return ep


# --------------------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------------------

# Registry entries are ``(builder, target_transaction_share, mean_transactions_per_episode)``.
# Episode sizes differ by two orders of magnitude between, say, ``human_normal`` (~3) and
# ``flash_sale_burst`` (~110), so the selector must weight by share/mean_size. Weighting by
# episode alone would let one burst scenario swallow the whole class.

LEGIT_HUMAN_SCENARIOS = [
    (human_normal, 0.50, 3.0),
    (human_repeat_buyer, 0.22, 5.0),
    (human_high_value, 0.03, 1.0),
    (household_shared_device, 0.06, 8.0),
    (flash_sale_burst, 0.12, 110.0),
    (retry_payment_failure, 0.07, 4.5),
]

LEGIT_AGENT_SCENARIOS = [
    (agent_routine_purchase, 0.45, 2.5),
    (agent_fast_comparison, 0.15, 1.0),
    (agent_enterprise_bulk, 0.22, 30.0),
    (agent_subscription_runs, 0.18, 2.5),
]

SUSPICIOUS_SCENARIOS = [
    (agent_velocity_abuse, 0.32, 37.0),
    (agent_authorization_mismatch, 0.24, 4.0),
    (agent_retry_hammer, 0.22, 21.0),
    (agent_sequence_anomaly, 0.22, 11.0),
]

CAMPAIGN_SCENARIOS = [
    (campaign_device_farm, 0.28, 15.0),
    (campaign_coupon_abuse, 0.24, 18.0),
    (campaign_sku_targeting, 0.20, 16.0),
    (campaign_instrument_probing, 0.16, 22.0),
    (campaign_new_account_rush, 0.12, 12.0),
]

SCENARIO_FAMILIES = {
    "LEGIT_HUMAN": LEGIT_HUMAN_SCENARIOS,
    "LEGIT_AGENT": LEGIT_AGENT_SCENARIOS,
    "SUSPICIOUS_AUTOMATION": SUSPICIOUS_SCENARIOS,
    "COORDINATED_ABUSE": CAMPAIGN_SCENARIOS,
}

ALL_SCENARIO_NAMES = sorted(
    fn.__name__ for family in SCENARIO_FAMILIES.values() for fn, *_ in family
)

HARD_NEGATIVE_SCENARIOS = {
    "human_high_value",
    "household_shared_device",
    "flash_sale_burst",
    "retry_payment_failure",
    "agent_fast_comparison",
    "agent_enterprise_bulk",
}
