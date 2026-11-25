"""Compare two kicad-cli schematic netlists by connectivity.

Net names that KiCad makes up itself (`Net-(R1-Pad2)`, `unconnected-(…)`)
change whenever a part is renamed, so they cannot be compared by name. A
made-up net is matched to the old net it shares the most pins with; a net a
person named is compared by its name.
"""
from collections import Counter
from dataclasses import dataclass

from gate.facing import parse

Pin = tuple[str, str]
NONE = "(none)"


class DuplicateReference(ValueError):
    """Two parts share a reference, so their pins cannot be told apart."""


@dataclass(frozen=True)
class Netlist:
    parts: dict[str, dict[str, str]]
    pin_net: dict[Pin, str]


def _children(node, head):
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _value(node, head, default=""):
    found = _children(node, head)
    return found[0][1] if found and len(found[0]) > 1 else default


def read_netlist(text: str) -> Netlist:
    tree = parse(text)
    parts = {}
    for comps in _children(tree, "components"):
        for comp in _children(comps, "comp"):
            lib = _children(comp, "libsource")
            lib_id = f"{_value(lib[0], 'lib')}:{_value(lib[0], 'part')}" if lib else ""
            ref = _value(comp, "ref")
            if ref in parts:
                raise DuplicateReference(f"reference {ref} is used twice; cannot compare")
            parts[ref] = {"value": _value(comp, "value"),
                          "footprint": _value(comp, "footprint"),
                          "lib": lib_id}
    pin_net = {}
    for nets in _children(tree, "nets"):
        for net in _children(nets, "net"):
            name = _value(net, "name").lstrip("/")
            for node in _children(net, "node"):
                pin = (_value(node, "ref"), _value(node, "pin"))
                if pin in pin_net:
                    raise DuplicateReference(
                        f"pin {pin[0]}.{pin[1]} is on two nets; a reference is "
                        "probably used twice; cannot compare")
                pin_net[pin] = name
    return Netlist(parts, pin_net)


def _made_up(name: str) -> bool:
    """KiCad's own name; in a subsheet it follows the sheet path (sub/Net-(…))."""
    return name.rsplit("/", 1)[-1].startswith(("Net-(", "unconnected-("))


def _members(pin_net: dict[Pin, str]) -> dict[str, set[Pin]]:
    nets: dict[str, set[Pin]] = {}
    for pin, name in pin_net.items():
        nets.setdefault(name, set()).add(pin)
    return nets


def _shown(name: str, size: int) -> str:
    """A pin alone on a made-up net is not connected to anything."""
    return NONE if _made_up(name) and size == 1 else name


def _renames(old: Netlist, new: Netlist) -> dict[str, str]:
    """Old ref -> new ref, for a part that only changed its reference.

    The part's fields, its pin numbers and the named nets on its pins must all
    be the same, and there must be exactly one such candidate each way.
    """
    def signature(nl, ref):
        pins = sorted((p, None if _made_up(n) else n)
                      for (r, p), n in nl.pin_net.items() if r == ref)
        return (tuple(sorted(nl.parts[ref].items())), tuple(pins))

    gone = [r for r in old.parts if r not in new.parts]
    added = [r for r in new.parts if r not in old.parts]
    old_sigs = Counter(signature(old, r) for r in gone)
    new_sigs = Counter(signature(new, r) for r in added)
    by_sig = {signature(new, r): r for r in added}
    return {r: by_sig[s] for r in gone
            if (s := signature(old, r)) in by_sig and old_sigs[s] == 1 and new_sigs[s] == 1}


def _match_made_up(old_pin_net: dict[Pin, str], new_nets: dict[str, set[Pin]]) -> dict[str, str]:
    """New made-up net -> the old made-up net it continues, one to one.

    Most shared pins wins (at least two); on a tie the net that kept its name,
    then name order. A new net left unmatched is a new net, so when an old net
    splits, only one half carries its name on and the other half's pins show.
    """
    candidates = []
    for new_name, pins in new_nets.items():
        if not _made_up(new_name):
            continue
        shared = Counter(old_pin_net[p] for p in pins if p in old_pin_net)
        for old_name, count in shared.items():
            if _made_up(old_name) and count > 1:
                candidates.append((-count, new_name != old_name, new_name, old_name))
    matched, taken = {}, set()
    for _, _, new_name, old_name in sorted(candidates):
        if new_name not in matched and old_name not in taken:
            matched[new_name] = old_name
            taken.add(old_name)
    return matched


def compare(old: Netlist, new: Netlist) -> list[str]:
    renames = _renames(old, new)
    back = {n: o for o, n in renames.items()}
    lines = [f"rename {o} -> {n}" for o, n in renames.items()]

    for ref, fields in old.parts.items():
        if ref in renames:
            continue
        if ref not in new.parts:
            lines.append(f"- {ref} {fields['value']} ({fields['footprint']})")
            continue
        for key in ("value", "footprint", "lib"):
            if fields[key] != new.parts[ref][key]:
                lines.append(f"{ref} {key} {fields[key]} -> {new.parts[ref][key]}")
    for ref, fields in new.parts.items():
        if ref not in old.parts and ref not in back:
            lines.append(f"+ {ref} {fields['value']} ({fields['footprint']})")

    # The new netlist in old references, so pins line up.
    new_pin_net = {(back.get(r, r), p): n for (r, p), n in new.pin_net.items()}
    old_nets, new_nets = _members(old.pin_net), _members(new_pin_net)

    matched = _match_made_up(old.pin_net, new_nets)

    def as_old(name: str) -> str:
        """A new net's name as the old netlist would show it."""
        if not _made_up(name):
            return name
        if name in matched:
            return matched[name]
        # Unmatched: a new net, even if it happens to reuse an old name.
        return f"{name} (new net)" if name in old_nets else name

    for pin in sorted(set(old.pin_net) | set(new_pin_net)):
        was = old.pin_net.get(pin)
        now = new_pin_net.get(pin)
        was_shown = _shown(was, len(old_nets[was])) if was else NONE
        now_shown = _shown(now, len(new_nets[now])) if now else NONE
        if now_shown != NONE:
            now_shown = as_old(now_shown)
        # Pins of added or removed parts are covered by the +/- line.
        kept = pin[0] in old.parts and (pin[0] in new.parts or pin[0] in renames)
        if kept and was_shown != now_shown:
            lines.append(f"{pin[0]}.{pin[1]}: {was_shown} -> {now_shown}")
    return sorted(lines)
