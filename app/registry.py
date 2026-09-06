"""Registrierung aller Engines und Wegesuche zwischen Formaten.

Die Konvertierer bilden einen gerichteten Graphen: Knoten sind Formate,
Kanten sind Umwandlungen. Dadurch entstehen automatisch auch mehrstufige
Wege - zum Beispiel MSG -> HTML -> PDF -> PDF/A -, ohne dass jede
Kombination von Hand gepflegt werden muss.
"""

from __future__ import annotations

import heapq
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache

from app import formats
from app.config import settings
from app.engines import archives, av, data, fonts, images, mail, markup, office, pdftools
from app.engines.base import Engine

log = logging.getLogger("converter.registry")

_MODULES = (office, markup, images, av, pdftools, data, mail, archives, fonts)


# Formatkategorien werden zu groben Domaenen zusammengefasst. Mehrstufige
# Wege duerfen eine Domaenengrenze nur ueberschreiten, wenn das fachlich Sinn
# ergibt. Sonst entstuenden Kuriositaeten wie "Video nach Word", weil sich
# ueber ein Standbild theoretisch jeder Weg konstruieren laesst.
DOMAINS: dict[str, str] = {
    "document": "dokument",
    "spreadsheet": "dokument",
    "presentation": "dokument",
    "markup": "dokument",
    "ebook": "dokument",
    "email": "dokument",
    "drawing": "dokument",
    "data": "dokument",
    "image": "bild",
    "video": "medien",
    "audio": "medien",
    "subtitle": "medien",
    "archive": "archiv",
    "font": "schrift",
}

# Erlaubte Domaenenwechsel fuer Wege mit mehr als einem Schritt.
ALLOWED_CROSS: frozenset[tuple[str, str]] = frozenset(
    {
        ("dokument", "bild"),  # Seitenvorschau, Scan-Ersatz
        ("bild", "dokument"),  # Scan nach PDF oder Word
        ("medien", "bild"),    # Standbild aus einem Video
    }
)

# Bei einem Domaenenwechsel sind nur gebraeuchliche Bildformate als Ziel
# sinnvoll - niemand braucht "Word nach OpenEXR".
COMMON_IMAGE_TARGETS: frozenset[str] = frozenset({"png", "jpg", "tiff", "webp", "gif", "bmp"})


def _domain(ext: str) -> str:
    fmt = formats.FORMATS.get(ext)
    return DOMAINS.get(fmt.category, "sonstiges") if fmt else "sonstiges"


def route_is_sensible(src: str, dst: str, hops: int) -> bool:
    """Filtert fachlich unsinnige Umwege aus dem Ergebnis der Wegesuche."""
    if hops <= 1:
        return True
    src_domain, dst_domain = _domain(src), _domain(dst)
    if src_domain == dst_domain:
        return True
    if (src_domain, dst_domain) not in ALLOWED_CROSS:
        return False
    if dst_domain == "bild" and dst not in COMMON_IMAGE_TARGETS:
        return False
    return True


@dataclass(frozen=True)
class Step:
    """Ein Schritt auf dem Weg vom Quell- zum Zielformat."""

    engine: Engine
    src_ext: str
    dst_ext: str

    def describe(self) -> str:
        return self.engine.describe(self.src_ext, self.dst_ext)


@dataclass(frozen=True)
class Route:
    """Ein vollstaendiger Weg zwischen zwei Formaten."""

    steps: tuple[Step, ...]
    cost: int

    @property
    def hops(self) -> int:
        return len(self.steps)

    @property
    def direct(self) -> bool:
        return len(self.steps) == 1

    def engine_names(self) -> list[str]:
        return [step.engine.label for step in self.steps]

    def describe(self) -> str:
        if not self.steps:
            return ""
        chain = [self.steps[0].src_ext.upper()] + [s.dst_ext.upper() for s in self.steps]
        return " → ".join(chain)


class Registry:
    def __init__(self, engines: list[Engine] | None = None, *, require_binaries: bool = True) -> None:
        self._all_engines: list[Engine] = engines if engines is not None else _load_engines()
        self._require_binaries = require_binaries
        self._lock = threading.Lock()
        self._graph: dict[str, dict[str, tuple[Engine, int]]] | None = None
        self._route_cache: dict[tuple[str, str], Route | None] = {}

    # -- Aufbau ------------------------------------------------------
    @property
    def engines(self) -> list[Engine]:
        if self._require_binaries:
            return [e for e in self._all_engines if e.available()]
        return list(self._all_engines)

    @property
    def graph(self) -> dict[str, dict[str, tuple[Engine, int]]]:
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    self._graph = self._build()
        return self._graph

    def _build(self) -> dict[str, dict[str, tuple[Engine, int]]]:
        graph: dict[str, dict[str, tuple[Engine, int]]] = {}
        skipped = [e.name for e in self._all_engines if e not in self.engines]
        if skipped:
            log.warning("Engines ohne installiertes Programm werden uebersprungen: %s", ", ".join(skipped))

        for engine in self.engines:
            for src in engine.sources():
                for dst in engine.targets():
                    if not engine.supports(src, dst):
                        continue
                    cost = engine.edge_cost(src, dst)
                    existing = graph.setdefault(src, {}).get(dst)
                    # Bei mehreren moeglichen Engines gewinnt die guenstigste.
                    if existing is None or cost < existing[1]:
                        graph[src][dst] = (engine, cost)
        log.info(
            "Konvertierungsgraph aufgebaut: %d Quellformate, %d direkte Wege",
            len(graph),
            sum(len(v) for v in graph.values()),
        )
        return graph

    def invalidate(self) -> None:
        with self._lock:
            self._graph = None
            self._route_cache.clear()
            self.targets_for.cache_clear()  # type: ignore[attr-defined]

    # -- Abfragen ----------------------------------------------------
    def input_formats(self) -> list[str]:
        """Alle Formate, die als Eingabe angenommen werden."""
        return sorted(ext for ext, edges in self.graph.items() if edges)

    def output_formats(self) -> list[str]:
        targets: set[str] = set()
        for edges in self.graph.values():
            targets.update(edges)
        return sorted(targets)

    def route(self, src_ext: str, dst_ext: str, max_hops: int | None = None) -> Route | None:
        """Guenstigster Weg von ``src_ext`` nach ``dst_ext`` oder None."""
        src = formats.canonical(src_ext)
        dst = formats.canonical(dst_ext)
        if not src or not dst or src == dst:
            return None
        limit = max_hops or settings.max_path_length
        key = (src, dst)
        cached = self._route_cache.get(key)
        if cached is not None or key in self._route_cache:
            return cached
        routes = self._search(src, limit)
        with self._lock:
            for target, route in routes.items():
                self._route_cache[(src, target)] = route
            self._route_cache.setdefault(key, None)
        return routes.get(dst)

    @lru_cache(maxsize=512)
    def targets_for(self, src_ext: str, max_hops: int | None = None) -> dict[str, Route]:
        """Alle erreichbaren Zielformate mit dem jeweils besten Weg."""
        src = formats.canonical(src_ext)
        if not src:
            return {}
        return self._search(src, max_hops or settings.max_path_length)

    def _search(self, src: str, limit: int) -> dict[str, Route]:
        """Dijkstra mit Begrenzung der Zwischenschritte."""
        graph = self.graph
        if src not in graph:
            return {}

        # best[(knoten, schritte)] = kosten
        best: dict[tuple[str, int], int] = {(src, 0): 0}
        # Bester bekannter Weg je Zielknoten.
        found: dict[str, Route] = {}
        queue: list[tuple[int, int, str, tuple[Step, ...]]] = [(0, 0, src, ())]

        while queue:
            cost, hops, node, steps = heapq.heappop(queue)
            if cost > best.get((node, hops), cost):
                continue
            if steps and route_is_sensible(src, node, hops):
                current = found.get(node)
                if current is None or cost < current.cost or (cost == current.cost and hops < current.hops):
                    found[node] = Route(steps=steps, cost=cost)
            if hops >= limit:
                continue
            for neighbour, (engine, edge_cost) in graph.get(node, {}).items():
                if neighbour == src:
                    continue
                if any(step.src_ext == neighbour for step in steps):
                    continue  # keine Schleifen ueber bereits benutzte Formate
                new_cost = cost + edge_cost
                state = (neighbour, hops + 1)
                if new_cost < best.get(state, 1 << 30):
                    best[state] = new_cost
                    heapq.heappush(
                        queue,
                        (new_cost, hops + 1, neighbour, steps + (Step(engine, node, neighbour),)),
                    )
        return found

    # -- Darstellung fuer die Oberflaeche -----------------------------
    def target_catalog(self, src_ext: str) -> list[dict[str, object]]:
        """Zielformate mit Beschreibung, sortiert nach Kategorie und Guete."""
        routes = self.targets_for(src_ext)
        entries: list[dict[str, object]] = []
        for ext, route in routes.items():
            fmt = formats.FORMATS.get(ext)
            if fmt is None or fmt.read_only:
                continue
            entries.append(
                {
                    "ext": ext,
                    "label": fmt.label,
                    "category": fmt.category,
                    "categoryLabel": formats.CATEGORIES.get(fmt.category, fmt.category),
                    "direct": route.direct,
                    "hops": route.hops,
                    "via": route.describe(),
                    "engines": route.engine_names(),
                    "note": fmt.note,
                }
            )
        entries.sort(
            key=lambda e: (
                formats.CATEGORY_ORDER.index(str(e["category"]))
                if e["category"] in formats.CATEGORY_ORDER
                else 99,
                int(e["hops"]),
                str(e["label"]).lower(),
            )
        )
        return entries


def _load_engines() -> list[Engine]:
    collected: list[Engine] = []
    for module in _MODULES:
        collected.extend(module.engines())
    return collected


registry = Registry()
