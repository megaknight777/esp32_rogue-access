"""Monte Carlo model: rogue-AP detection latency vs. dwell time of a channel-hopping sensor.
Run: python simulate.py   (outputs: simulation_summary.csv, stats.txt, fig_latency.pdf/png)

ASSUMPTIONS (not measurements):
  - rogue beacons every B = 102.4 ms (100 TU, 802.11 default) on one uniformly random channel of 13
  - sensor hops 1..13 sequentially; dwell D ms per channel; S = 3 ms dead time after each channel switch
  - a beacon arriving while the sensor listens on the right channel is received with probability Q
  - the rogue is switched on at a random moment relative to the hopping cycle (random beacon phase)
"""
import numpy as np, pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

B, S, NCH = 102.4, 3.0, 13
HORIZON, DEADLINE, N = 60_000.0, 5_000.0, 5000
DWELLS = [20, 50, 100, 120, 200, 300]
QS = [0.6, 0.85, 0.95]
rng = np.random.default_rng(42)


def one_trial(D, Q):
    c = rng.integers(0, NCH)
    start = rng.uniform(0, NCH * D)
    n = int(HORIZON // B) + 1
    tb = start + rng.uniform(0, B) + np.arange(n) * B
    i = np.floor(tb / D).astype(int)
    ok = ((tb - i * D) >= S) & ((i % NCH) == c) & (rng.random(n) < Q)
    if not ok.any():
        return np.nan
    lat = tb[np.argmax(ok)] - start
    return lat if lat <= HORIZON else np.nan


def analytic_mean_ms(D, Q):
    """Rough closed-form check: p = per-visit capture probability, geometric number of cycles."""
    w = D - S
    p = Q * w / B if w < B else 1 - (1 - Q) ** (w / B)
    cycle = NCH * D
    return cycle / 2 + cycle * (1 / p - 1)


def boot_ci(x, f=np.median, k=1000):
    bs = [f(rng.choice(x, len(x))) for _ in range(k)]
    return np.percentile(bs, [2.5, 97.5])


rows, store = [], {}
for Q in QS:
    for D in DWELLS:
        lat = np.array([one_trial(D, Q) for _ in range(N)])
        store[(Q, D)] = lat
        d = lat[~np.isnan(lat)]
        lo, hi = boot_ci(d)
        rows.append(dict(Q=Q, dwell_ms=D, n=N,
                         TPR_60s=len(d) / N,
                         TPR_5s=np.mean(d <= DEADLINE) * len(d) / N,
                         median_s=np.median(d) / 1000, med_ci_lo_s=lo / 1000, med_ci_hi_s=hi / 1000,
                         mean_s=d.mean() / 1000, p95_s=np.percentile(d, 95) / 1000,
                         analytic_mean_s=analytic_mean_ms(D, Q) / 1000))
df = pd.DataFrame(rows)
df.to_csv("simulation_summary.csv", index=False)
print(df.round(3).to_string(index=False))

out = []
for Q in QS:
    groups = [store[(Q, D)][~np.isnan(store[(Q, D)])] for D in DWELLS]
    h, p = stats.kruskal(*groups)
    out.append(f"Q={Q}: Kruskal-Wallis across dwell values H={h:.1f}, p={p:.3g}")
    for ref in (20, 300):
        a = store[(Q, 100)]; b = store[(Q, ref)]
        a, b = a[~np.isnan(a)], b[~np.isnan(b)]
        u, p = stats.mannwhitneyu(a, b, alternative="less")
        rbc = 1 - 2 * u / (len(a) * len(b))
        out.append(f"Q={Q}: latency(100 ms) < latency({ref} ms)? U={u:.0f}, p={p:.3g}, rank-biserial r={rbc:.2f}")
open("stats.txt", "w").write("\n".join(out))
print("\n" + "\n".join(out))

fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.9))
for Q in QS:
    g = df[df.Q == Q]
    ax[0].errorbar(g.dwell_ms, g.median_s, yerr=[g.median_s - g.med_ci_lo_s, g.med_ci_hi_s - g.median_s],
                   marker="o", capsize=2, label=f"Q={Q}")
    ax[1].plot(g.dwell_ms, g.TPR_5s, marker="o", label=f"Q={Q}")
ax[0].axvline(B, ls="--", c="gray", lw=0.8)
ax[0].set_xlabel("Dwell time (ms)"); ax[0].set_ylabel("Median detection latency (s)")
ax[0].legend(fontsize=7); ax[0].set_title("(a) latency", fontsize=9)
ax[1].set_xlabel("Dwell time (ms)"); ax[1].set_ylabel("Detected within 5 s"); ax[1].set_ylim(0.9, 1.005)
ax[1].set_title("(b) timely detection", fontsize=9)
plt.tight_layout()
plt.savefig("fig_latency.pdf"); plt.savefig("fig_latency.png", dpi=200)
