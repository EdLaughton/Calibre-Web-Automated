"""Handle extra series fields submitted with CWA's normal metadata form."""

from .extra_series_store import CalibreSeriesStore


store = CalibreSeriesStore()


def prepare(book_id, form):
    """Validate the entire series form before CWA commits ordinary metadata."""
    if form.get("nova_series_form") != "1":
        return None
    try:
        count = int(form.get("nova_series_count", ""))
    except (TypeError, ValueError):
        raise ValueError("Invalid additional series form")
    if not 0 <= count <= 100:
        raise ValueError("Invalid additional series row count")
    existing = store.for_book(book_id)
    originals = {(row["kind"].casefold(), row["name"].casefold()): row for row in existing}
    seen_originals = set()
    seen_targets = set()
    changes = []
    for index in range(count):
        old_kind = form.get(f"nova_old_kind_{index}", "")
        old_name = form.get(f"nova_old_name_{index}", "")
        kind = form.get(f"nova_kind_{index}", "")
        if kind == "custom":
            kind = "custom:" + form.get(f"nova_custom_kind_{index}", "")
        name = form.get(f"nova_name_{index}", "")
        position = form.get(f"nova_position_{index}", "")
        remove = form.get(f"nova_remove_{index}") == "1"
        old_key = (old_kind.casefold(), old_name.casefold()) if old_kind or old_name else None
        if old_key:
            if old_key not in originals or old_key in seen_originals:
                raise ValueError("Series changed since this page loaded; reload and try again")
            seen_originals.add(old_key)
        elif remove:
            raise ValueError("Cannot remove an unknown series")
        if remove:
            changes.append((old_key, None))
            continue
        if not name.strip():
            if old_key or (position and position.strip()):
                raise ValueError("Enter a series name or mark the existing row for removal")
            continue
        target = store.validate(kind, name, position)
        target_key = (target[0].casefold(), target[1].casefold())
        if target_key in seen_targets:
            raise ValueError("The same additional series is listed twice")
        if target_key in originals and target_key != old_key:
            raise ValueError("That additional series is already assigned to this book")
        seen_targets.add(target_key)
        changes.append((old_key, target))
    if seen_originals != set(originals):
        raise ValueError("Series changed since this page loaded; reload and try again")
    return changes


def apply(book_id, changes):
    """Save validated rows after CWA has committed the normal metadata edit."""
    if changes is None:
        return False
    changed = False
    for old_key, target in changes:
        if old_key is not None and target is not None and old_key[0] == target[0].casefold():
            old = next((row for row in store.for_book(book_id)
                        if row["kind"].casefold() == old_key[0] and row["name"].casefold() == old_key[1]), None)
            if old is None:
                raise RuntimeError("Series changed during this save; reload and review")
            wanted = None if target[2] is None else float(target[2])
            if old["name"] != target[1] or old["position"] != wanted:
                store.replace_membership(book_id, old["kind"], old["name"], *target)
                changed = True
            continue
        if target is not None:
            kind, name, position = target
            current = store.for_book(book_id)
            found = next((row for row in current if row["kind"].casefold() == kind.casefold()
                          and row["name"].casefold() == name.casefold()), None)
            wanted = None if position is None else float(position)
            if found is None or found["position"] != wanted:
                store.set_membership(book_id, kind, name, position)
                changed = True
        if old_key is not None and (target is None or old_key != (target[0].casefold(), target[1].casefold())):
            old = next((row for row in store.for_book(book_id)
                        if row["kind"].casefold() == old_key[0] and row["name"].casefold() == old_key[1]), None)
            if old is None:
                raise RuntimeError("Series changed during this save; reload and review")
            store.remove_membership(book_id, old["kind"], old["name"])
            changed = True
    return changed
