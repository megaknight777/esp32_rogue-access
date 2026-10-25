"""Analyze serial logs from rogue_ap_sensor.ino.
Usage: python analyze.py trials.log
Computes per-dwell TPR (with Wilson 95% CI), FPR, detection latency, and
statistical tests (Fisher exact for TPR, Mann-Whitney U for latency).
All numbers come from the log file only.
"""
import sys, math
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats


def parse(path):
    trials, cur = [], None
    for line in open(path, encoding="utf-8", errors="ignore"):
        p = line.strip().split(",")
        if not p:
            continue
        if p[0] == "START":
            cur = dict(trial=int(p[1]), dwell=int(p[2]), kind=p[3],
                       t_start=int(p[4]), mark=None, hits=[])
        elif p[0] == "MARK" and cur:
            cur["mark"] = int(p[1])
        elif p[0] == "HIT" and cur:
            cur["hits"].append(int(p[1]))
        elif p[0] == "END" and cur:
            trials.append(cur)
            cur = None
    rows = []
    for t in trials:
        if t["kind"] == "rogue" and t["mark"] is not None:
            after = [h for h in t["hits"] if h >= t["mark"]]
            before = [h for h in t["hits"] if h < t["mark"]]
            rows.append(dict(trial=t["trial"], dwell=t["dwell"], kind="rogue",
                             detected=bool(after),
                             latency_s=(after[0] - t["mark"]) / 1000 if after else None,
                             false_alarm=bool(before)))
        elif t["kind"] == "clean":
            rows.append(dict(trial=t["trial"], dwell=t["dwell"], kind="clean",
                             detected=False, latency_s=None,
                             false_alarm=bool(t["hits"])))
    return pd.DataFrame(rows)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    m = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


df = parse(sys.argv[1])
df.to_csv("trials_parsed.csv", index=False)

summary = []
for dw, g in df.groupby("dwell"):
    r, c = g[g.kind == "rogue"], g[g.kind == "clean"]
    k, n = int(r.detected.sum()), len(r)
    lo, hi = wilson(k, n)
    summary.append(dict(dwell_ms=dw, n_rogue=n, TPR=k / n if n else None,
                        TPR_CI_lo=lo, TPR_CI_hi=hi,
                        n_clean=len(c), FPR=c.false_alarm.mean() if len(c) else None,
                        lat_median_s=r.latency_s.median(), lat_mean_s=r.latency_s.mean(),
                        lat_sd_s=r.latency_s.std()))
S = pd.DataFrame(summary)
print(S.round(3).to_string(index=False))
S.to_csv("summary.csv", index=False)

dw = sorted(df.dwell.unique())
if len(dw) >= 2:
    a = df[(df.kind == "rogue") & (df.dwell == dw[0])]
    b = df[(df.kind == "rogue") & (df.dwell == dw[1])]
    tab = [[int(a.detected.sum()), int((~a.detected).sum())],
           [int(b.detected.sum()), int((~b.detected).sum())]]
    print(f"\nFisher exact TPR {dw[0]} vs {dw[1]} ms:", stats.fisher_exact(tab))
    la, lb = a.latency_s.dropna(), b.latency_s.dropna()
    if len(la) > 1 and len(lb) > 1:
        u, pval = stats.mannwhitneyu(la, lb, alternative="two-sided")
        rbc = 1 - 2 * u / (len(la) * len(lb))  # rank-biserial effect size
        print(f"Mann-Whitney U latency: U={u:.1f}, p={pval:.4f}, rank-biserial={rbc:.2f}")

# Figures
fig, ax = plt.subplots(1, 2, figsize=(8, 3.2))
ax[0].bar([str(x) for x in S.dwell_ms], S.TPR,
          yerr=[S.TPR - S.TPR_CI_lo, S.TPR_CI_hi - S.TPR], capsize=4)
ax[0].set_xlabel("Dwell time (ms)"); ax[0].set_ylabel("True-positive rate"); ax[0].set_ylim(0, 1.05)
data = [df[(df.kind == "rogue") & (df.dwell == d)].latency_s.dropna() for d in dw]
ax[1].boxplot(data, labels=[str(d) for d in dw])
ax[1].set_xlabel("Dwell time (ms)"); ax[1].set_ylabel("Detection latency (s)")
plt.tight_layout(); plt.savefig("results.pdf")
