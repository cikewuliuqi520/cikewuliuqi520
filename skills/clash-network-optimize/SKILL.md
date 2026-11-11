---
name: clash-network-optimize
description: Use when the user says “优化下网络问题” or reports slow or unstable OpenAI access on a Mac using Clash Party or mihomo. Diagnose local proxy routing and select a verified OpenAI node within 20 seconds.
---

# Clash network optimization

Find the failure point before choosing a node. A low delay from Clash's test URL is only a shortlist signal: a node can return 403 from OpenAI or fail TLS on real requests. The bundled script caps normal work at 16 seconds and reserves time to restore the original selection, keeping the whole run under 20 seconds. Its local node table accumulates results across runs.

## Run

1. If the user reports an OpenAI or ChatGPT network problem on Clash Party, run `python3 <skill-dir>/scripts/optimize.py --apply` when their request authorizes changing the node. For inspection only, omit `--apply`. This one command checks the core, rule mode, system proxy, OpenAI rules, existing selectable nodes, and real requests.
2. The script stores only node names, results, and a configuration fingerprint in `~/.cache/clash-network-optimize/nodes.json`. Fresh results help later runs skip the full initial node scan. The table is local to each computer and never includes subscription URLs, server credentials, or API keys.
3. Read the result. ChatGPT HTTP 200 and unauthenticated OpenAI API HTTP 401 count as accessible; HTTP 403, TLS errors, and timeouts fail. The script restores the original node if no candidate passes or an application check fails. A 20-second sample cannot prove all-day reliability; repeated runs strengthen the local table.
4. If the symptom is not OpenAI related, diagnose that application's route instead of using this script. If the script reports missing Clash, disabled system proxy, or unmatched rules, fix the reported cause in scope and rerun only when doing so still meets the user's time limit.

## Boundaries

- Use only existing selector options. Keep mode, subscriptions, DNS, and proxy settings unless the diagnosis shows they cause the reported problem.
- The script selects no winner if all candidates fail both real targets. Report that result instead of forcing a failing node.
