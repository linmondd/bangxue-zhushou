"""Read-only reconciliation of a selected scope against freshly opened course tables."""
import time

from . import classes, state


def check(driver, scope_path, report_path, log=print):
    selected = state.selected(scope_path)
    report = {"started_at": time.time(), "selected": len(selected), "classes": []}
    for wid, title in selected.items():
        item = {"wid": wid, "title": title, "checked_at": time.time()}
        try:
            rows = classes.read_class_table(driver, wid)
            completed, total = classes.progress(rows)
            item.update(completed=completed, total=total, rows=rows,
                        status="complete" if classes.is_complete(rows) else "incomplete" if rows else "unverified")
        except (ValueError, RuntimeError, OSError) as exc:
            item.update(status="unverified", reason=str(exc))
        report["classes"].append(item)
        state.save(report_path, report)
        log(f"{title} · {item['status']} · {item.get('completed', '?')}/{item.get('total', '?')}")
    report["finished_at"] = time.time()
    state.save(report_path, report)
    return "attention" if any(c["status"] == "unverified" for c in report["classes"]) else "checked"
