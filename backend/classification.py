"""Demo summaries built on the same normalization as the integration package."""
from ticket_engine.normalization import RUBRIC_ID, fingerprint, normalize, number


def paired_summary(tickets, local_provider="laya-ft", current_models=None):
    # Only include the same fully-labelled, current-rubric pairs in both denominators.
    summary = {"paired": 0, "labelled": 0, "laya": {"correct": 0, "elapsed_ms": 0}, "jev": {"correct": 0, "elapsed_ms": 0}}
    for ticket in tickets:
        runs = ticket["runs"]
        a, b = runs[local_provider]["analysis"], runs["jev"]["analysis"]
        state_id = fingerprint({"subject": ticket["subject"], "message": ticket["message"]})
        if not a or not b or any(r.get("rubric_id") != RUBRIC_ID or r.get("input_id") != state_id for r in (a, b)):
            continue
        if current_models and any(current_models.get(name) and result.get("model") != current_models[name]
                                  for name, result in ((local_provider, a), ("jev", b))):
            continue
        summary["paired"] += 1
        for name, result in (("laya", a), ("jev", b)):
            summary[name]["elapsed_ms"] += result["elapsed_ms"]
        reference = ticket.get("reference")
        if reference:
            summary["labelled"] += 1
            for name, result in (("laya", a), ("jev", b)):
                summary[name]["correct"] += int(result["category"] == reference["category"])
    summary["local_provider"] = local_provider
    return summary
