/** Turns backend feature values into plain-language evidence.
 *
 * Every card this produces is derived from a value the backend actually
 * returned in `features_summary` / `top_feature_deviations`. If a feature is
 * absent from the response, no card is emitted for it — the UI never asserts
 * something the detection did not measure.
 *
 * Each item answers three questions in order: what happened, why it is unusual,
 * and why a merchant should care.
 */

import { formatCount, formatPercent, toNumber } from './format';

export interface EvidenceItem {
  id: string;
  /** What happened, with the real number in it. */
  headline: string;
  /** Why that is unusual. */
  why: string;
  /** Why it matters commercially. */
  impact: string;
  /** How strongly this points at coordinated abuse, for ordering. */
  weight: number;
  tone: 'risk' | 'benign' | 'neutral';
}

type Features = Record<string, number> | undefined;

function f(features: Features, key: string): number | null {
  if (!features) return null;
  return toNumber(features[key]);
}

export function deriveEvidence(features: Features, totalTransactions: number): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  if (!features) return items;

  // --- decline behaviour -------------------------------------------------
  const failureRate = f(features, 'C.failure_rate');
  if (failureRate !== null) {
    if (failureRate >= 0.4) {
      items.push({
        id: 'failure_rate',
        headline: `${formatPercent(failureRate)} of payment attempts failed`,
        why: 'Genuine shoppers mostly succeed. A failure rate this high usually means the payment credentials being tried are not valid.',
        impact: 'Each failed authorisation still costs the merchant a gateway fee and counts against their processor standing.',
        weight: failureRate * 100,
        tone: 'risk',
      });
    } else if (failureRate <= 0.15) {
      items.push({
        id: 'failure_rate_ok',
        headline: `Failure rate is normal at ${formatPercent(failureRate)}`,
        why: 'Attempts are mostly succeeding, which is what legitimate customer traffic looks like.',
        impact: 'Adding friction here would block paying customers for no benefit.',
        weight: 12,
        tone: 'benign',
      });
    }
  }

  // --- instrument novelty -------------------------------------------------
  const novelty = f(features, 'C.instrument_novelty');
  if (novelty !== null && novelty >= 0.7) {
    items.push({
      id: 'novelty',
      headline: `${formatPercent(novelty)} of payment instruments are new to this merchant`,
      why: 'Most merchants see a mix of returning and new cards. Almost everything being unseen suggests the cards come from an external list rather than from this merchant’s customers.',
      impact: 'Unrecognised instruments at volume are the signature of credential testing, which turns into chargebacks later.',
      weight: novelty * 80,
      tone: 'risk',
    });
  }

  // --- entity concentration ----------------------------------------------
  const clusterShare = f(features, 'J.largest_cluster_vol_share');
  if (clusterShare !== null && clusterShare >= 0.3) {
    items.push({
      id: 'cluster',
      headline: `${formatPercent(clusterShare)} of activity sits in one connected group`,
      why: 'Independent shoppers do not share devices, cards and network addresses with each other. A single connected group this large means the accounts are not independent.',
      impact: 'This is the clearest separator between a real traffic surge and a coordinated one.',
      weight: clusterShare * 110,
      tone: 'risk',
    });
  }

  const accountsPerDevice = f(features, 'F.accounts_per_device_max');
  if (accountsPerDevice !== null && accountsPerDevice >= 3) {
    items.push({
      id: 'device_sharing',
      headline: `Up to ${formatCount(accountsPerDevice)} accounts share a single device`,
      why: 'Households and offices share a device occasionally. This many distinct accounts on one device is not ordinary shared use.',
      impact: 'Device concentration is expensive for an attacker to avoid, which makes it a reliable signal.',
      weight: Math.min(accountsPerDevice * 8, 90),
      tone: 'risk',
    });
  }

  const instrumentsPerDevice = f(features, 'F.instruments_per_device_max');
  if (instrumentsPerDevice !== null && instrumentsPerDevice >= 5) {
    items.push({
      id: 'cards_per_device',
      headline: `One device presented ${formatCount(instrumentsPerDevice)} different payment instruments`,
      why: 'A real customer has a handful of cards. Dozens from one device is characteristic of testing a stolen list.',
      impact: 'Instrument velocity caps target exactly this behaviour without touching normal shoppers.',
      weight: Math.min(instrumentsPerDevice * 6, 95),
      tone: 'risk',
    });
  }

  // --- velocity -----------------------------------------------------------
  const txnRate = f(features, 'A.txn_rate');
  if (txnRate !== null && txnRate > 0) {
    items.push({
      id: 'velocity',
      headline: `Traffic is running at ${formatCount(Math.round(txnRate))} attempts per minute`,
      why: 'Velocity alone does not decide anything — a flash sale looks the same on this axis. It sets the scale of whatever is happening.',
      impact: 'Used together with the signals above, not on its own.',
      weight: 20,
      tone: 'neutral',
    });
  }

  // --- amount structure ---------------------------------------------------
  const lowValue = f(features, 'D.low_value_ratio');
  if (lowValue !== null && lowValue >= 0.6) {
    items.push({
      id: 'micro_amounts',
      headline: `${formatPercent(lowValue)} of attempts are very low value`,
      why: 'Testing a card costs the attacker the amount charged, so probes are kept small. Real baskets vary much more.',
      impact: 'Small amounts still generate authorisation fees and confirm live cards for later, larger fraud.',
      weight: lowValue * 60,
      tone: 'risk',
    });
  }

  // --- account age --------------------------------------------------------
  const newAccounts = f(features, 'G.new_account_rate');
  if (newAccounts !== null && newAccounts >= 0.7) {
    items.push({
      id: 'new_accounts',
      headline: `${formatPercent(newAccounts)} of accounts were created recently`,
      why: 'A surge of brand-new accounts is normal during a campaign, but combined with entity sharing it points at automated signups.',
      impact: 'Matters most for promotional abuse, where each fresh account is a discount claimed.',
      weight: newAccounts * 45,
      tone: 'risk',
    });
  }

  // --- decline code spread -----------------------------------------------
  const declineEntropy = f(features, 'I.decline_code_entropy');
  if (declineEntropy !== null && failureRate !== null && failureRate > 0.3 && declineEntropy < 0.6) {
    items.push({
      id: 'decline_concentration',
      headline: 'Declines are concentrated in a narrow set of reasons',
      why: 'A gateway outage spreads declines across many codes. A tight cluster of issuer refusals looks more like invalid credentials than infrastructure trouble.',
      impact: 'This is what separates a retry storm from card testing — the two have similar failure rates.',
      weight: 55,
      tone: 'risk',
    });
  }

  if (totalTransactions > 0 && items.length === 0) {
    items.push({
      id: 'nothing_notable',
      headline: 'No individual signal stands out',
      why: 'The measured features sit within the range this merchant normally produces.',
      impact: 'Veyra records the window for context and recommends no action.',
      weight: 1,
      tone: 'benign',
    });
  }

  return items.sort((a, b) => b.weight - a.weight);
}
